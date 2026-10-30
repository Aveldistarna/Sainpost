"""Self-bootstrapping launcher for the Sainpost MCP server.

.mcp.json (or `claude mcp add`) runs this with whatever `python` the machine
has. Its whole job is to make a fresh clone work with no manual steps:
guarantee a venv carrying the one dependency, then hand stdio to the server
inside it.

Standard library only -- this runs BEFORE any dependency exists.

STDOUT belongs to the MCP client from the first byte; a single stray print
here corrupts the handshake. Everything goes to stderr.
"""

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQS = ROOT / "requirements.txt"
PROBE = "import mcp"

#: Beside the venv, never inside it: the thing it guards is the venv's own
#: existence, and a lock that lives in what is being created cannot be held
#: while it is created.
LOCK = ROOT / ".venv.lock"

#: How long to wait for whoever is building, and how long to believe a lock
#: file at all. pip on a cold cache is minutes, so the wait is generous; a
#: process killed mid-build must not wedge every session on the machine
#: afterwards, so the belief expires.
LOCK_WAIT = 600
LOCK_STALE = 900


def log(msg: str) -> None:
    print(f"sainpost launcher: {msg}", file=sys.stderr, flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def deps_ok(py: Path) -> bool:
    if not py.exists():
        return False
    stamp = VENV / ".deps-verified"
    if stamp.exists() and stamp.stat().st_mtime >= REQS.stat().st_mtime:
        return True
    r = subprocess.run([str(py), "-c", PROBE], stdin=subprocess.DEVNULL,
                       capture_output=True)
    if r.returncode == 0:
        stamp.write_text("ok", encoding="utf-8")
        return True
    return False


@contextlib.contextmanager
def one_at_a_time():
    """Only one process builds the venv. The rest wait and then find it done.

    Nothing here was serialised, and "a fresh clone needs no manual steps"
    means every session on the machine reaches this at the same moment --
    four of them ran `python -m venv` and then `pip install` into one
    directory. Measured on a fresh checkout with four clients: they came up
    at 1.0, 3.0, 13.2 and 27.8 seconds, and the ones whose build lost the
    race fell back to whatever interpreter had launched them, which worked
    here only because this machine happened to have `mcp` installed globally.
    Twenty-eight seconds is past what several MCP clients wait for a server.

    An exclusive create is the lock, because it is one atomic operation on
    both platforms and needs no dependency -- which this file cannot have.
    """
    deadline = time.time() + LOCK_WAIT
    while True:
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            pass
        try:
            held = time.time() - LOCK.stat().st_mtime
        except OSError:
            continue                     # it was released; go for it
        if held > LOCK_STALE:
            log(f"the build lock is {held:.0f}s old -- taking it as abandoned")
            try:
                LOCK.unlink()
            except OSError:
                pass
            continue
        if time.time() > deadline:
            raise TimeoutError(f"another process has been building {VENV.name} "
                               f"for {held:.0f}s")
        time.sleep(0.25)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()}\n")
        yield
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


def build() -> Path:
    py = venv_python()
    if deps_ok(py):
        return py
    with one_at_a_time():
        # Asked again, inside the lock. This is the line that turns four
        # bootstraps into one: whoever waited arrives here after the winner
        # has finished and returns without running pip at all. It also covers
        # the ordinary case where nothing raced and requirements.txt merely
        # got a newer mtime from a checkout.
        py = venv_python()
        if deps_ok(py):
            return py
        if not py.exists():
            log(f"creating venv at {VENV}")
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True,
                           stdin=subprocess.DEVNULL,
                           stdout=sys.stderr, stderr=sys.stderr)
            py = venv_python()
        log("installing dependencies (once)")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(REQS)],
                       check=True, stdin=subprocess.DEVNULL,
                       stdout=sys.stderr, stderr=sys.stderr)
        # Inside the lock, with the install: released one line earlier, a
        # waiter could re-ask deps_ok in the gap and start a second pip
        # against the venv this one just finished.
        (VENV / ".deps-verified").write_text("ok", encoding="utf-8")
        return py


def main() -> None:
    try:
        py = build()
    except Exception as e:                                     # noqa: BLE001
        log(f"bootstrap failed: {e}")
        log("falling back to the interpreter that launched this")
        py = Path(sys.executable)
    server = str(ROOT / "sainpost" / "server.py")
    if os.name == "nt":
        # Windows has no exec. os.execv() there SPAWNS a replacement process
        # and exits this one, so the pid the MCP client launched and is
        # watching disappears during the handshake -- the client reads that
        # as the server having crashed, whatever the replacement goes on to
        # do. Stay as a thin parent instead: the child inherits this
        # process's stdio handles directly, so nothing is copied, buffered
        # or re-encoded between the client and the server.
        # stdin=None, said out loud: this is the ONE child here that has
        # to inherit it. It IS the server, and that pipe is the client. Every
        # other subprocess in this project passes DEVNULL, because a child
        # that inherits an MCP stdio pipe it does not read can hang on it --
        # see rig._git.
        sys.exit(subprocess.call([str(py), server], stdin=None))
    os.execv(str(py), [str(py), server])


if __name__ == "__main__":
    main()
