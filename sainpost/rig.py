"""Which commit a node was created against. Observation, and nothing else.

`apparatus` asks for "the check that the rig is sound: versions, flags, which
build is actually running". When the rig is code, prose cannot answer the
last one and a commit id can. Two failures follow from not recording it, and
neither reports an error:

  * The code moves under a measurement. You pre-register at one commit,
    measure, close at another. The number then reads as a fact about the
    current code, and nothing in the record disagrees.
  * A number is taken against a working tree that differs from every commit.
    It cannot be repeated, so it is not a measurement -- but it looks exactly
    like one once it is written down.

WHY THIS MODULE ONLY READS
It used to capture the state as well: build a tree, write a commit, move a
ref, push it. That made a lab notebook write into the thing it was observing,
and every fault the design produced came from that one decision. It pushed a
working tree off the machine before saying so. It left refs in repositories it
did not own. And because a dirty tree got a fresh timestamped commit at every
capture, "the code moved under this measurement" fired on identical code --
destroying, with its own noise, the single signal the whole mechanism existed
to produce.

So it reads `git rev-parse HEAD` and `git status --porcelain` and stops. No
object is written, no ref is moved, nothing is pushed, nothing leaves the
machine. `dirty` is not a problem to be fixed by committing on somebody's
behalf; it is the finding. It means this number cannot be reproduced, and
saying so plainly is worth more than quietly making it false.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class RigError(Exception):
    """The code state could not be read. Never fatal to recording a node."""


def _git(repo: Path, *args: str) -> str:
    # --no-optional-locks so that "reads only" is exact rather than nearly
    # true: a plain `git status` refreshes the index's stat cache, which
    # rewrites .git/index. Nothing under .git changes because of this module.
    # encoding="utf-8", not the locale's: text=True alone decodes with the
    # console codepage -- cp932 on a Japanese Windows -- and `git status` on a
    # tree with one non-ASCII filename would then raise inside a module whose
    # entire promise is that it never costs the caller a recorded node.
    # stdin=DEVNULL is the whole difference between this returning in 30
    # milliseconds and never returning at all.
    #
    # subprocess leaves stdin alone unless told otherwise, so the child gets
    # the parent's. In this server the parent's stdin is the MCP pipe, opened
    # by anyio in overlapped mode, and a git that inherits it blocks forever
    # -- caught with three `git rev-parse --show-toplevel` processes minutes
    # old and still alive, each parented to a server that was never going to
    # answer. Measured: note_start(repo=...) never returned, from ONE client;
    # with this line, 0.05s. The same command run from a plain process with a
    # plain pipe for stdin comes back in 0.02s, which is why the shape of the
    # bug was "only through the server" and why it survived every test that
    # called the store directly.
    #
    # git has no business reading our stdin in any case. Nothing here does.
    r = subprocess.run(["git", "-C", str(repo), "--no-optional-locks", *args],
                       stdin=subprocess.DEVNULL,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RigError((r.stderr.strip() or r.stdout.strip() or "git failed")[:400])
    return r.stdout.strip()


def is_repo(path: Optional[str | Path]) -> Optional[Path]:
    if not path or not shutil.which("git"):
        return None
    p = Path(path).expanduser()
    if not p.is_dir():
        return None
    try:
        return Path(_git(p, "rev-parse", "--show-toplevel"))
    except RigError:
        return None


def observe(repo: Path) -> dict:
    """{"commit", "modified", "untracked"}. Writes nothing, anywhere.

    The two kinds of difference are separated because they mean opposite
    things and the first version conflated them into one alarm.

      modified  -- tracked files differ from HEAD. The code the number came
                   out of is in no commit. This is the real one.
      untracked -- files git has never been told about. Running a Python
                   program creates __pycache__/, so treating this as the same
                   thing made the alarm fire on essentially every Python
                   investigation, claiming the measurement was irreproducible
                   when the tracked source had not moved at all. Two agents
                   hit it; one of them passed the false claim on to another
                   team inside a defect.

    They are still both reported. An untracked file can perfectly well be the
    experiment -- it is just not evidence on its own that the code moved, so
    it is returned as a list of names for a reader to judge rather than as a
    verdict.

    .gitignore is respected, because git's own status respects it.
    """
    try:
        commit = _git(repo, "rev-parse", "HEAD")
    except RigError:
        commit = None                      # a repository with no commits yet
    modified, untracked = False, []
    for line in _git(repo, "status", "--porcelain").splitlines():
        if line.startswith("??"):
            untracked.append(line[3:].strip())
        elif line.strip():
            modified = True
    return {"commit": commit, "modified": modified, "untracked": untracked}


def remote_is_private(cwd: Optional[Path] = None) -> Optional[bool]:
    """True / False / None when gh cannot say. Used by the notebook's backup.

    None is not "probably fine". The dump is every investigation on this
    machine, and a public push is not a mistake anyone gets to take back, so
    not knowing is a reason to stop.
    """
    if not shutil.which("gh"):
        return None
    # gh emits UTF-8 JSON. Decoded with a Japanese console's cp932, a
    # repository whose description is not ASCII comes back as mojibake or
    # raises, json.loads fails, and this returns None -- which the backup
    # correctly reads as "cannot confirm the remote is private" and refuses
    # to push. A working setup would have looked like a security stop.
    r = subprocess.run(["gh", "repo", "view", "--json", "isPrivate"],
                       cwd=str(cwd or Path(__file__).resolve().parents[1]),
                       stdin=subprocess.DEVNULL,      # see _git
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return None
    try:
        return bool(json.loads(r.stdout)["isPrivate"])
    except (ValueError, KeyError):
        return None
