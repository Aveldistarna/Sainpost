"""Back the notebook up to git, as text.

The record lives outside this repository -- under ~/.local/share on Linux
and LOCALAPPDATA on Windows -- because it is shared by every project on
the machine. That makes it the one thing here with no copy anywhere.
This puts one in the repository.

WHY A DUMP AND NOT THE .db FILE
The record is append-only, so its SQL dump is append-only too: each backup
adds lines and changes none, which is exactly the diff git is good at. A
committed binary would instead store a fresh opaque blob every time, and
"what did the last week of work actually add" would stop being a question
anyone could ask of the history. The dump also restores with nothing but
sqlite3, which is the same promise the schema itself makes.

The file must be a pure function of the database -- no timestamp, no host --
or every run would produce a commit whether or not anything was learned.

Standard library only, and it never writes to the notebook.

    python backup.py              dump, then send it wherever it goes
    python backup.py restore      rebuild the database from the dump

WHERE IT GOES
SAINPOST_DRIVE names the destination, and takes either a local directory
-- any folder some sync client already watches, a OneDrive folder as
readily as ~/Dropbox -- or an rclone remote like "gdrive:Sainpost".
Unset, the dump is written and nothing is sent.

The copy is the second copy, and the point of it is that it is not on this
disk. It is also the whole backup when the dump is not in git: there is then
no history behind it, so a run that writes a truncated dump overwrites the
good one. Drive keeps its own versions of a file, which is the only thing
standing behind that.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DUMP = ROOT / "notebook" / "research.sql"


def snapshot_path() -> Path:
    """Derived, never a second constant: the two must move together, and a
    caller that redirects DUMP and gets the old .db is a trap."""
    return DUMP.with_suffix(".db")

sys.path.insert(0, str(ROOT))
from sainpost import rig  # noqa: E402
from sainpost.store import default_db_path  # noqa: E402


#: The dump is text this program owns end to end, so it fixes both things
#: the platform would otherwise decide for it.
#:
#: encoding: the default is the locale's, which is cp932 on a Japanese
#: Windows -- and a notebook that recorded "mesure de resistance" with the
#: accent, or any CJK, or an emoji, raises UnicodeEncodeError and the backup
#: does not happen. The record is free text from every project on the
#: machine; there is no character it is entitled to refuse.
#:
#: newline: write_text() turns every "\n" into CRLF on Windows, which would
#: make the file differ from the same record dumped on Linux. The module
#: promises the dump is a pure function of the database, and the machine it
#: ran on is not part of the database.
TEXT = {"encoding": "utf-8", "newline": "\n"}


def read_dump(path: Path) -> str:
    # newline= is not passed on the way in: universal newlines already fold
    # CRLF back to "\n", so a dump written by an older version on Windows
    # still compares equal to today's instead of looking like a rewrite.
    return path.read_text(encoding=TEXT["encoding"])


def write_dump(path: Path, text: str) -> None:
    with path.open("w", **TEXT) as f:
        f.write(text)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    # encoding, not the locale's: text=True alone decodes with the console
    # codepage, which is cp932 on a Japanese Windows and mangles or raises on
    # any git output that is not ASCII. git speaks UTF-8 on every platform.
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          stdin=subprocess.DEVNULL,   # see rig._git
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


# -- dumping ---------------------------------------------------------------

def snapshot(db: Path, into: Path) -> None:
    """A consistent copy of a live notebook, through sqlite's backup API.

    NEVER `cp`. WAL keeps recent writes in research.db-wal, so copying the
    .db of a notebook some agent has open yields a file that opens cleanly
    and contains nothing -- three sessions of records were lost here to
    exactly that. The backup API copies under the right locks, cannot catch a
    half-written transaction, and does not block the agent writing one.
    """
    into.parent.mkdir(parents=True, exist_ok=True)
    # Into a FRESH file, then move it into place. Backing up over an existing
    # database produces a different byte layout for identical content -- the
    # destination's own pages and freelist leak into the result -- so the
    # snapshot looked new on every run and every backup filed a spurious
    # version of it. Identical records must produce an identical file, or
    # "has this changed" cannot be asked of it.
    tmp = into.with_name(into.name + ".new")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(into)


def dump_text(db: Path) -> str:
    """The same snapshot, as SQL text.

    Both are kept. The .db restores by copying and is the thing itself; the
    text is what can be read, grepped and salvaged by hand if the binary is
    ever damaged, and it is the one that diffs if it is in git. Together they
    are under 150 KB.
    """
    tmp = Path(tempfile.mkdtemp()) / "snapshot.db"
    try:
        snapshot(db, tmp)
        snap = sqlite3.connect(str(tmp))
        try:
            return "\n".join(snap.iterdump()) + "\n"
        finally:
            snap.close()
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


#: What the commit message counts. Order is the shape of the record.
TABLES = ("projects", "questions", "attempts", "defects")


def counts(text: str) -> dict:
    return {t: text.count(f'INSERT INTO "{t}"') + text.count(f"INSERT INTO {t} ")
            for t in TABLES}


def summarise(new: str, old: str) -> str:
    n, o = counts(new), counts(old)
    parts = []
    for t in TABLES:
        delta = n[t] - o[t]
        parts.append(f"{n[t]} {t}" + (f" (+{delta})" if delta > 0 else ""))
    return "notebook: " + ", ".join(parts)


# -- the one guard that matters -------------------------------------------

#: One implementation of "is this remote private", shared with the code-state
#: push in rig.py. Two would eventually disagree, and the one that mattered
#: would be the lenient one.
remote_is_private = rig.remote_is_private


#: Lines google's API errors put the actual cause on. rclone prints the whole
#: JSON error body, and the first line of it is boilerplate.
_CAUSE = re.compile(r'"(reason|message)":\s*"([^"]{4,400})"')


def _why(stderr: str) -> str:
    """The cause, not the first line.

    A real failure was reported as `Error 403: Google Drive API has not been
    used in project 1234567...` -- truncated at 200 characters, one line, with
    the machine-readable reason (SERVICE_DISABLED) and the URL that fixes it
    both cut off. It was only diagnosable because the user had redirected the
    whole run to a file and opened it. An error message that has to be
    recovered from a log the caller happened to keep is not a message.
    """
    found, seen = [], set()
    for _, text in _CAUSE.findall(stderr):
        if text not in seen:
            seen.add(text)
            found.append("  " + text)
    if not found:
        found = ["  " + ln for ln in stderr.strip().splitlines()[:3]]
    return "\n".join(found[:4])


#: An rclone remote is "name:path"; a Windows destination is "C:\Users\...".
#: Both contain a colon, and the whole difference is that a drive letter is
#: exactly one character long. Deciding on the colon alone told a Windows
#: user that their own backup folder was "an rclone remote, and rclone is not
#: installed" -- an error about a program they had no reason to have, for a
#: directory that was sitting right there. A remote name of one letter is
#: legal in rclone and unreachable here; a path is the likelier reading of
#: "C:", and an existing path still wins outright below.
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:([\\/]|$)")


def names_an_rclone_remote(dest: str) -> bool:
    return ":" in dest and not _DRIVE_LETTER.match(dest)


def send(*paths: Path) -> str:
    """Copy the dump off this disk. Best effort, and it says which effort.

    Never fatal: the dump is already written locally, and a backup that
    refused to finish because the network was down would be the worse
    failure. The caller prints what came back so the difference is visible
    rather than assumed.
    """
    dest = os.environ.get("SAINPOST_DRIVE", "").strip()
    if not dest:
        return "not sent anywhere: SAINPOST_DRIVE names a directory or an " \
               "rclone remote"
    names = ", ".join(p.name for p in paths)
    # What a version history is for, once the dump is not in git: knowing
    # WHICH backup introduced a corruption. A destination that only ever holds
    # the latest copy is one bad write from useless, and Drive's own file
    # versions expire. So the copy being replaced is moved aside under a dated
    # folder first, and nothing is ever overwritten in place.
    keep = f"history/{datetime.now().astimezone().date().isoformat()}"
    if names_an_rclone_remote(dest) and not Path(dest).exists():
        if not shutil.which("rclone"):
            return f"NOT SENT: {dest!r} looks like an rclone remote and rclone is " \
                   f"not installed"
        # One file per call. `rclone copy` takes exactly one source and one
        # destination; handing it two sources is a usage error, which the
        # first real run produced and the test did not, because the test
        # mocked subprocess and only checked the command's prefix.
        for f in paths:
            # encoding="utf-8": _why() below reads google's JSON error body
            # out of this, and the console codepage would hand it back as
            # mojibake or raise on the way in -- losing the text of the one
            # message that exists because the first version of it was
            # unreadable.
            r = subprocess.run(["rclone", "copy", "--checksum",
                                "--backup-dir", f"{dest.rstrip('/')}/{keep}",
                                str(f), dest],
                               stdin=subprocess.DEVNULL,   # see rig._git
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                return (f"NOT SENT ({f.name}): rclone failed.\n"
                        + _why(r.stderr) or "  (rclone said nothing)")
        return f"sent {names} to {dest}"
    d = Path(dest).expanduser()
    if not d.is_dir():
        return f"NOT SENT: {str(d)!r} is not a directory"
    for f in paths:
        current = d / f.name
        if current.exists() and current.read_bytes() == f.read_bytes():
            continue
        # Beside it under a name of its own, then over it in one step. This
        # used to move the old copy aside and then copy the new one in, which
        # left the destination with no copy, or half of one, whenever the run
        # stopped between the two -- and once every write to the notebook
        # starts a backup, runs stop there. The old copy is COPIED into the
        # history for the same reason: there is never a moment with none.
        tmp = d / f".{f.name}.{os.getpid()}.new"
        try:
            shutil.copy2(f, tmp)
            if current.exists():
                (d / keep).mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, d / keep / f.name)
            os.replace(tmp, current)
        except OSError as e:
            # A sync client holding the file open refuses the replace on
            # Windows. The copy already there is intact; say so.
            tmp.unlink(missing_ok=True)
            return f"NOT SENT ({f.name}): {e}. The copy already at {d} is unchanged"
    return f"copied {names} to {d}"


# -- commands --------------------------------------------------------------

@contextmanager
def exclusive(timeout: float = 120.0):
    """One backup at a time on this machine.

    Every session runs its own server, and each starts a backup when it
    writes. Two at once share the snapshot beside the dump and the files at
    the destination, and whichever finished second could leave the older
    record in place. A run that waits is still wanted: it started after a
    write the running one may have snapshotted before.
    """
    path = DUMP.parent / ".backup.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as fh:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"another backup has held {path} for "
                                       f"{timeout:.0f}s")
                time.sleep(0.2)
        try:
            yield
        finally:
            if os.name == "nt":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh, fcntl.LOCK_UN)


def backup(push: bool, force_push: bool, commit: bool = True) -> int:
    try:
        with exclusive():
            return _backup(push, force_push, commit)
    except TimeoutError as e:
        log(f"NOT BACKED UP: {e}")
        return 1


def _backup(push: bool, force_push: bool, commit: bool) -> int:
    db = Path(os.environ.get("SAINPOST_DB") or default_db_path()).expanduser()
    if not db.exists():
        log(f"no notebook at {db} -- nothing to back up yet")
        return 0

    text = dump_text(db)
    snapshot(db, snapshot_path())
    old = read_dump(DUMP) if DUMP.exists() else ""
    unchanged = text == old
    if not unchanged:
        DUMP.parent.mkdir(parents=True, exist_ok=True)
        write_dump(DUMP, text)
        log(f"wrote {DUMP.relative_to(ROOT)}  ({summarise(text, old)})")

    # Always, even when the dump did not change. "Nothing to commit" is not
    # "nothing to send": the copy off this disk may be missing or stale --
    # the destination was only just configured, or the last run could not
    # reach it -- and that is exactly when it must not be skipped.
    log(send(snapshot_path(), DUMP))

    if unchanged:
        log(f"{DUMP.relative_to(ROOT)} was already current -- nothing to commit")
        return 0
    if not commit:
        return 0
    message = summarise(text, old)

    if git("check-ignore", "-q", str(DUMP), check=False).returncode == 0:
        # Deliberately outside git: the copy above is the backup, and there is
        # no history behind it.
        return 0

    git("add", str(DUMP))
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        log("nothing staged")
        return 0
    git("commit", "-m", message)
    log(f"committed: {message}")

    if not push:
        return 0
    if not git("remote", check=False).stdout.strip():
        log("no git remote -- commit made, nothing pushed")
        return 0

    private = remote_is_private()
    if private is False:
        log("REFUSING TO PUSH: the remote is PUBLIC.\n"
            "  This dump is every investigation on this machine. Make the "
            "repository private\n  (gh repo edit --visibility private) before "
            "pushing it anywhere.")
        return 2
    if private is None and not force_push:
        log("REFUSING TO PUSH: cannot confirm the remote is private (gh is not "
            "installed,\n  not authenticated, or the remote is not GitHub). The "
            "commit is made locally.\n  Re-run with --push-anyway once you have "
            "checked it yourself.")
        return 2

    r = git("push", check=False)
    if r.returncode != 0:
        log("push failed:\n" + (r.stderr.strip() or r.stdout.strip()))
        return 1
    log("pushed")
    return 0


def restore() -> int:
    """Rebuild the notebook from the dump. Never over an existing one.

    The record has no update path by design, and that has to hold for this
    file too: replaying a dump over a live notebook would silently overwrite
    whatever it did not know about. Move the old one aside deliberately.
    """
    db = Path(os.environ.get("SAINPOST_DB") or default_db_path()).expanduser()
    if not DUMP.exists():
        log(f"no dump at {DUMP}")
        return 1
    if db.exists():
        log(f"REFUSING: {db} already exists. Move it aside first -- restoring "
            f"over a live\n  notebook would discard whatever this dump predates.")
        return 2
    if snapshot_path().exists():
        log(f"note: {snapshot_path().name} beside the dump is the same record as "
            f"a database file.\n  Copying it is the shorter route; this rebuilds "
            f"from the text instead.")
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    try:
        con.executescript(read_dump(DUMP))
        con.commit()
    finally:
        con.close()
    log(f"restored {db} from {DUMP.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", default="backup",
                    choices=["backup", "restore"])
    ap.add_argument("--no-push", action="store_true",
                    help="dump and commit, but do not push")
    ap.add_argument("--no-commit", action="store_true",
                    help="dump and send, and leave git alone (what the server "
                         "runs after every write)")
    ap.add_argument("--push-anyway", action="store_true",
                    help="push even though the remote's visibility could not "
                         "be confirmed")
    a = ap.parse_args()
    if a.command == "restore":
        return restore()
    return backup(push=not a.no_push, force_push=a.push_anyway,
                  commit=not a.no_commit)


if __name__ == "__main__":
    sys.exit(main())
