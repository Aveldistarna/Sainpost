"""The backup, and the two things it must never do.

It must never produce a commit for work that did not happen -- that is what
makes the git history readable as "what was learned this week" rather than
"how often the script ran". And it must never push a record of every
investigation on the machine to somewhere anyone can read.
"""

import subprocess

import pytest

import backup as bk
from sainpost.store import Store


@pytest.fixture()
def notebook(tmp_path, monkeypatch):
    db = tmp_path / "research.db"
    monkeypatch.setenv("SAINPOST_DB", str(db))
    s = Store(db)
    s.start_project("ddr", "escape routing under a 0.5mm BGA")
    s.ask("ddr", "why do U2's four byte lanes jam")
    s.hypothesis("ddr", hypothesis="via price is too high",
                 why_now="A0 showed order does not matter",
                 measure="sweep via_cost_mm 0.1..8.0",
                 falsifier="joined-span count does not move",
                 apparatus="stale=false; repair=False")
    s.result("ddr", "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    s.close()
    return db


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A throwaway repository standing in for this one."""
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True)
    monkeypatch.setattr(bk, "ROOT", root)
    monkeypatch.setattr(bk, "DUMP", root / "notebook" / "research.sql")
    return root


# -- the dump ---------------------------------------------------------------

def test_the_dump_is_a_pure_function_of_the_record(notebook):
    """A timestamp or a hostname in here would mean a commit every run,
    whether or not anything was learned."""
    assert bk.dump_text(notebook) == bk.dump_text(notebook)


def test_the_dump_carries_what_was_measured(notebook):
    text = bk.dump_text(notebook)
    assert "6/8 unchanged across 0.1..8.0" in text
    assert "FALSIFIED" in text
    assert bk.counts(text) == {"projects": 1, "questions": 1, "attempts": 1,
                               "defects": 0}


def test_a_restore_reproduces_the_record(notebook, repo, monkeypatch):
    bk.backup(push=False, force_push=False)
    notebook.unlink()
    assert bk.restore() == 0
    s = Store(notebook)
    t = s.trunk("ddr")
    assert t["attempts"][0]["verdict"] == "FALSIFIED"
    assert t["attempts"][0]["result"] == "6/8 unchanged across 0.1..8.0"
    s.close()


def test_a_restore_never_lands_on_a_live_notebook(notebook, repo):
    """There is no update path anywhere in this record, and replaying a dump
    over a notebook that has moved on would be exactly that."""
    bk.backup(push=False, force_push=False)
    assert bk.restore() == 2
    assert "why do U2" in notebook.read_bytes().decode("utf-8", "replace")


# -- committing -------------------------------------------------------------

def test_work_becomes_one_commit_naming_what_it_added(notebook, repo):
    assert bk.backup(push=False, force_push=False) == 0
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "1 projects" in log and "1 attempts" in log


def test_running_again_with_no_new_work_makes_no_commit(notebook, repo):
    bk.backup(push=False, force_push=False)
    before = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout
    assert bk.backup(push=False, force_push=False) == 0
    after = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    assert before == after


def test_the_next_commit_message_counts_only_what_is_new(notebook, repo):
    bk.backup(push=False, force_push=False)
    s = Store(notebook)
    s.hypothesis("ddr", hypothesis="the pad frontage is blocked",
                 why_now="A1 was falsified", prompted_by="A1",
                 measure="count blocked pads",
                 falsifier="every pad has clear frontage",
                 apparatus="same board, repair=False")
    s.result("ddr", "5 of 8 pads blocked", "CONFIRMED")
    s.close()
    bk.backup(push=False, force_push=False)
    subject = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                             capture_output=True, text=True).stdout
    assert "2 attempts (+1)" in subject
    assert "1 projects" in subject and "(+" not in subject.split("projects")[0]


# -- the push guard ---------------------------------------------------------

def with_remote(repo, monkeypatch, private):
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "https://example.invalid/x.git"], check=True, capture_output=True)
    monkeypatch.setattr(bk, "remote_is_private", lambda: private)


def test_a_public_remote_is_refused(notebook, repo, monkeypatch):
    """This file is every investigation on the machine. A public push is not
    a mistake anyone gets to take back."""
    with_remote(repo, monkeypatch, False)
    assert bk.backup(push=True, force_push=False) == 2


def test_an_unconfirmable_remote_is_refused_too(notebook, repo, monkeypatch):
    """Not knowing is not the same as it being fine."""
    with_remote(repo, monkeypatch, None)
    assert bk.backup(push=True, force_push=False) == 2


def test_a_refused_push_still_leaves_the_work_committed_locally(notebook, repo,
                                                               monkeypatch):
    with_remote(repo, monkeypatch, False)
    bk.backup(push=True, force_push=False)
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "notebook:" in log


def test_the_override_only_covers_not_knowing_never_a_public_remote(notebook, repo,
                                                                   monkeypatch):
    with_remote(repo, monkeypatch, False)
    assert bk.backup(push=True, force_push=True) == 2


# -- the copy off this disk -------------------------------------------------

def test_a_local_directory_destination_receives_the_dump(notebook, repo, tmp_path,
                                                         monkeypatch):
    """Any folder a sync client already watches. No credentials, no daemon."""
    dest = tmp_path / "drive"
    dest.mkdir()
    monkeypatch.setenv("SAINPOST_DRIVE", str(dest))
    bk.backup(push=False, force_push=False)
    assert (dest / "research.sql").read_text() == bk.DUMP.read_text()


def test_it_is_sent_even_when_there_was_nothing_to_commit(notebook, repo, tmp_path,
                                                          monkeypatch):
    """"Nothing to commit" is not "nothing to send". The copy off this disk can
    be missing or stale -- the destination was only just configured, or the
    last run could not reach it -- and that is exactly the run that must not
    skip it."""
    dest = tmp_path / "drive"
    dest.mkdir()
    monkeypatch.setenv("SAINPOST_DRIVE", str(dest))
    bk.backup(push=False, force_push=False)
    (dest / "research.sql").unlink()                 # the copy goes missing
    assert bk.backup(push=False, force_push=False) == 0
    assert (dest / "research.sql").exists(), "a run with no new work still sends"


def test_an_unreachable_destination_never_costs_the_backup(notebook, repo,
                                                           monkeypatch):
    """The dump is already written locally. Refusing to finish because the
    network was down would be the worse failure."""
    monkeypatch.setenv("SAINPOST_DRIVE", "/nowhere/at/all")
    assert bk.backup(push=False, force_push=False) == 0
    assert bk.DUMP.exists()


def test_an_rclone_remote_without_rclone_says_so(notebook, repo, monkeypatch):
    monkeypatch.setenv("SAINPOST_DRIVE", "gdrive:Sainpost")
    monkeypatch.setattr(bk.shutil, "which", lambda n: None)
    assert "rclone is not installed" in bk.send(bk.snapshot_path(), bk.DUMP)


def test_each_file_is_a_separate_rclone_call(notebook, repo, monkeypatch):
    """`rclone copy` takes exactly ONE source and one destination. Handing it
    two produced a usage error on the first real run, while the test passed --
    it mocked subprocess and checked only the command's prefix, so arity was
    never looked at. Every argument is checked here now.

    --checksum, not timestamps: the dump is rewritten byte-identically on
    every run that learned nothing, and mtime alone would re-upload it.
    """
    calls = []
    monkeypatch.setenv("SAINPOST_DRIVE", "gdrive:Sainpost")
    monkeypatch.setattr(bk.shutil, "which", lambda n: "/usr/bin/rclone")

    class Done:
        returncode, stderr, stdout = 0, "", ""

    monkeypatch.setattr(bk.subprocess, "run",
                        lambda cmd, **kw: (calls.append(cmd), Done())[1])
    assert "gdrive:Sainpost" in bk.send(bk.snapshot_path(), bk.DUMP)
    assert len(calls) == 2, "one call per file, not one call with two sources"
    from datetime import datetime
    day = datetime.now().astimezone().date().isoformat()
    for cmd, f in zip(calls, (bk.snapshot_path(), bk.DUMP)):
        assert cmd == ["rclone", "copy", "--checksum", "--backup-dir",
                       f"gdrive:Sainpost/history/{day}", str(f),
                       "gdrive:Sainpost"]


def test_a_failed_file_is_named_and_the_rest_is_not_claimed_sent(notebook, repo,
                                                                 monkeypatch):
    monkeypatch.setenv("SAINPOST_DRIVE", "gdrive:Sainpost")
    monkeypatch.setattr(bk.shutil, "which", lambda n: "/usr/bin/rclone")

    class Failed:
        returncode, stdout = 1, ""
        stderr = "Failed to create file system: quota exceeded\nmore detail"

    monkeypatch.setattr(bk.subprocess, "run", lambda cmd, **kw: Failed())
    got = bk.send(bk.snapshot_path(), bk.DUMP)
    assert got.startswith("NOT SENT (research.db)") and "quota exceeded" in got
    # Bounded, but not truncated to one line: an earlier version cut at 200
    # characters and threw away the cause. Short enough to read, long enough
    # to act on.
    assert len(got.splitlines()) <= 6, "not a wall of rclone usage text"


def test_nothing_is_sent_when_no_destination_is_configured(notebook, repo,
                                                           monkeypatch):
    monkeypatch.delenv("SAINPOST_DRIVE", raising=False)
    assert "not sent anywhere" in bk.send(bk.snapshot_path(), bk.DUMP)


def test_both_the_database_and_the_dump_are_sent(notebook, repo, tmp_path,
                                                 monkeypatch):
    """The .db restores by copying and is the thing itself. The text is what
    can be read, grepped and salvaged by hand if the binary is ever damaged.
    Together they are under 150 KB, so choosing between them buys nothing."""
    dest = tmp_path / "drive"
    dest.mkdir()
    monkeypatch.setenv("SAINPOST_DRIVE", str(dest))
    bk.backup(push=False, force_push=False)
    assert (dest / "research.sql").exists() and (dest / "research.db").exists()
    again = Store(dest / "research.db")
    assert [p["project"] for p in again.projects()] == ["ddr"]
    again.close()


def test_the_database_copy_goes_through_sqlites_backup_api(notebook, repo,
                                                           tmp_path, monkeypatch):
    """Never `cp`. WAL keeps recent writes in research.db-wal, so copying the
    .db of a notebook an agent has open yields a file that opens cleanly and
    holds nothing -- three sessions of records were lost here to exactly that.
    Here the notebook is left open and mid-write while the backup runs."""
    live = Store(notebook)                      # still attached, WAL not folded in
    live.start_project("late", "written after the last checkpoint")
    live.db.commit()
    dest = tmp_path / "drive"
    dest.mkdir()
    monkeypatch.setenv("SAINPOST_DRIVE", str(dest))
    bk.backup(push=False, force_push=False)
    live.close()

    copied = Store(dest / "research.db")
    assert "late" in [p["project"] for p in copied.projects()], \
        "the copy missed a write that was still in the write-ahead log"
    copied.close()


def test_the_snapshot_follows_the_dump_rather_than_being_a_second_constant(
        tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "DUMP", tmp_path / "elsewhere" / "record.sql")
    assert bk.snapshot_path() == tmp_path / "elsewhere" / "record.db"


def test_a_failure_reports_the_cause_not_the_first_line(notebook, repo, monkeypatch):
    """A real failure came back as `Error 403: Google Drive API has not been
    used in project 1234567...` -- cut at 200 characters, with the reason
    (SERVICE_DISABLED) and the URL that fixes it both past the cut. It was
    diagnosable only because the run had been redirected to a file that the
    user happened to open. An error that must be recovered from a log is not
    a message."""
    monkeypatch.setenv("SAINPOST_DRIVE", "gdrive:Sainpost")
    monkeypatch.setattr(bk.shutil, "which", lambda n: "/usr/bin/rclone")

    class Failed:
        returncode, stdout = 1, ""
        stderr = ('2026/09/07 21:16:00 Failed to create file system for '
                  '"gdrive:Sainpost": couldn\'t find root directory ID: '
                  'googleapi: Error 403: Google Drive API has not been used in '
                  'project 123456789012 before or it is disabled.\n'
                  'Details:\n[\n  {\n    "reason": "SERVICE_DISABLED"\n  },\n'
                  '  {\n    "message": "Enable it by visiting '
                  'https://console.developers.google.com/apis/api/'
                  'drive.googleapis.com/overview?project=123456789012 then retry."'
                  '\n  }\n]\n')

    monkeypatch.setattr(bk.subprocess, "run", lambda cmd, **kw: Failed())
    got = bk.send(bk.snapshot_path(), bk.DUMP)
    assert "SERVICE_DISABLED" in got, "the machine-readable cause"
    assert "console.developers.google.com" in got, "the thing that fixes it"
    assert got.startswith("NOT SENT (research.db)")


def test_the_copy_being_replaced_is_kept_under_a_date(notebook, repo, tmp_path,
                                                      monkeypatch):
    """Once the dump is not in git, this is the only thing that can answer
    "which backup introduced this corruption". A destination that only ever
    holds the latest copy is one bad write from useless, and Drive's own file
    versions expire."""
    from datetime import datetime
    dest = tmp_path / "drive"
    dest.mkdir()
    monkeypatch.setenv("SAINPOST_DRIVE", str(dest))
    bk.backup(push=False, force_push=False)
    first = (dest / "research.sql").read_text()

    s = Store(notebook)
    s.ask("ddr", "and then what blocked the frontage")
    s.close()
    bk.backup(push=False, force_push=False)

    day = datetime.now().astimezone().date().isoformat()
    kept = dest / "history" / day / "research.sql"
    assert kept.read_text() == first, "the replaced copy is still readable"
    assert (dest / "research.sql").read_text() != first, "and the current one moved on"


def test_an_unchanged_copy_is_not_filed_as_a_version(notebook, repo, tmp_path,
                                                     monkeypatch):
    """A run that learned nothing must not fill the history with duplicates."""
    dest = tmp_path / "drive"
    dest.mkdir()
    monkeypatch.setenv("SAINPOST_DRIVE", str(dest))
    bk.backup(push=False, force_push=False)
    bk.backup(push=False, force_push=False)
    assert not (dest / "history").exists()


def test_rclone_is_told_to_keep_what_it_replaces(notebook, repo, monkeypatch):
    from datetime import datetime
    calls = []
    monkeypatch.setenv("SAINPOST_DRIVE", "gdrive:Sainpost")
    monkeypatch.setattr(bk.shutil, "which", lambda n: "/usr/bin/rclone")

    class Done:
        returncode, stderr, stdout = 0, "", ""

    monkeypatch.setattr(bk.subprocess, "run",
                        lambda cmd, **kw: (calls.append(cmd), Done())[1])
    bk.send(bk.snapshot_path(), bk.DUMP)
    day = datetime.now().astimezone().date().isoformat()
    assert ["--backup-dir", f"gdrive:Sainpost/history/{day}"] == calls[0][3:5]


def test_the_same_record_produces_the_same_file_every_time(notebook, repo):
    """Backing up over an existing database gives a different byte layout for
    identical content, so the snapshot looked new on every run and every
    backup filed a spurious version of it. "Has this changed" cannot be asked
    of a file that is never the same twice."""
    import hashlib
    seen = set()
    for _ in range(3):
        bk.snapshot(notebook, bk.snapshot_path())
        seen.add(hashlib.sha256(bk.snapshot_path().read_bytes()).hexdigest())
    assert len(seen) == 1
    assert not bk.snapshot_path().with_name("research.db.new").exists()


# -- the machine it runs on -------------------------------------------------

def test_a_drive_letter_is_a_directory_and_not_an_rclone_remote():
    """"C:\\Users\\..." and "gdrive:Sainpost" both contain a colon, and
    deciding on the colon alone told a Windows user that their own backup
    folder was "an rclone remote, and rclone is not installed" -- an error
    about a program they had no reason to have, for a directory that was
    sitting right there. The difference is that a drive letter is exactly one
    character long."""
    assert not bk.names_an_rclone_remote(r"C:\Users\me\OneDrive\Sainpost")
    assert not bk.names_an_rclone_remote("D:/backups")
    assert not bk.names_an_rclone_remote("/home/me/Dropbox")
    assert bk.names_an_rclone_remote("gdrive:Sainpost")
    assert bk.names_an_rclone_remote("onedrive:")


def test_a_missing_windows_folder_is_reported_as_a_missing_folder(repo, monkeypatch):
    """The destination the user actually configured, named in the terms they
    configured it in. Anything about rclone here sends them after the wrong
    thing entirely."""
    monkeypatch.setenv("SAINPOST_DRIVE", r"C:\no\such\folder")
    monkeypatch.setattr(bk.shutil, "which", lambda n: None)
    got = bk.send(bk.snapshot_path(), bk.DUMP)
    assert "is not a directory" in got and "rclone" not in got


def test_the_dump_is_utf8_with_lf_whatever_the_machine_says(notebook, repo):
    """The locale is no more part of the database than the hostname is.

    Text is written in the console codepage by default, which is cp932 on a
    Japanese Windows -- so a notebook that had recorded one accented word
    ended the backup with UnicodeEncodeError instead of a file, and the
    record is free text from every project on the machine: there is no
    character it is entitled to refuse. The newline is the same argument in
    quieter form -- the default would give the same record CRLF here and LF
    on Linux, and the module promises the dump is a pure function of the
    database.
    """
    s = Store(notebook)
    s.start_project("accents", "mesure de résistance — 日本語 🔧")
    s.close()
    bk.backup(push=False, force_push=False)

    raw = bk.DUMP.read_bytes()
    assert "résistance".encode("utf-8") in raw
    assert b"\r\n" not in raw
    assert "🔧" in bk.read_dump(bk.DUMP)


# -- a backup started by every write ----------------------------------------

def test_a_second_backup_waits_for_the_first(notebook, repo):
    """Every session's server backs up after its own writes. Two at once share
    the snapshot beside the dump and the files at the destination."""
    import threading
    got = []
    with bk.exclusive():
        def other():
            try:
                with bk.exclusive(timeout=0.3):
                    got.append("ran")
            except TimeoutError:
                got.append("waited")
        t = threading.Thread(target=other)
        t.start()
        t.join()
    assert got == ["waited"]
    with bk.exclusive(timeout=0.3):
        pass                                         # and it is released after


def test_the_destination_never_holds_half_a_copy(notebook, repo, tmp_path,
                                                 monkeypatch):
    """A replace that fails -- a sync client holding the file open, a run
    killed partway -- leaves the copy that was there, whole."""
    dest = tmp_path / "drive"
    dest.mkdir()
    monkeypatch.setenv("SAINPOST_DRIVE", str(dest))
    bk.backup(push=False, force_push=False)
    first = (dest / "research.sql").read_bytes()

    s = Store(notebook)
    s.ask("ddr", "and then what blocked the frontage")
    s.close()

    def refused(a, b):
        raise PermissionError("in use by another process")
    bk.snapshot(notebook, bk.snapshot_path())
    bk.write_dump(bk.DUMP, bk.dump_text(notebook))
    monkeypatch.setattr(bk.os, "replace", refused)
    said = bk.send(bk.snapshot_path(), bk.DUMP)
    assert said.startswith("NOT SENT")
    assert (dest / "research.sql").read_bytes() == first
    assert not [p for p in dest.iterdir() if p.name.endswith(".new")]


def test_the_servers_run_leaves_git_alone(notebook, repo, monkeypatch):
    """The server runs this after every write. Where the dump is tracked,
    that would be a commit per write in somebody's repository."""
    monkeypatch.setattr(bk, "git", lambda *a, **k: pytest.fail(f"git {a}"))
    assert bk.backup(push=False, force_push=False, commit=False) == 0
    assert bk.DUMP.exists()
