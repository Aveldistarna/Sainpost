"""Sainpost MCP server — the record of what was tried, and where you are.

The consumer of this server is an agent that has never read this repository.
Everything it needs in order not to misuse the record has to arrive through
the instructions block below and the tool docstrings.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sainpost import share  # noqa: E402
from sainpost.store import (GONE, NoteError, Store, clip,  # noqa: E402
                                default_db_path, standing_head, standing_words)

mcp = FastMCP("Sainpost", instructions=f"""
Sainpost — the lab notebook for long investigations, shared by every
project and agent on this machine. It stops one failure: an unverified
intermediate promoted to a fact, every later step reasoned correctly on top
of it, and killed hypotheses re-derived because nothing said they were dead.

  COMMITMENT BEFORE DATA. note_hypothesis records an attempt only with its
  falsifier and apparatus check written first; note_result takes numbers
  only for a pre-registered attempt. The record is append-only.
  A POSITION YOU CAN SEE. note_trunk prints where you are. Re-read it at
  every checkpoint; bodies come from note_open.

project -> question -> attempt. Reformulating the question (note_ask
supersedes=) is usually the finding; a question your answer will REST on
goes under it (parent=). prompted_by names the RESULT that sent you on.
Resting on another project's row, cite it (cites=), do not name it in
prose. A negative result is the most valuable row here.

START
  note_projects()     always first; it needs no name.
  note_path(project)  what was already ruled out. Read it before any new
                      line of attack.
LOOP
  note_trunk -> note_hypothesis, BEFORE measuring (it returns similar
  attempts from every project, settled and in flight) -> the work ->
  note_result -> note_answer once settled.

REACH FOR THESE -- nothing else will prompt you:
  note_blocked     no number came out (a crash, a missing build), or a
                   tool -- this notebook too, project sainpost-itself
                   -- returned something false. Never ABANDONED for that.
  note_request     a tool lacks what you need; the owner is its project.
  note_postscript  a closed result or answer later proved invalid, or the
                   user accepted or rejected an answer.
  note_import      before writing to a project last worked on another
                   machine; note_export when you stop.

Database: {default_db_path()}  (SAINPOST_DB moves it)
""".rstrip())

_STORE: Optional[Store] = None


def store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store(os.environ.get("SAINPOST_DB") or None)
    return _STORE


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


class _AutoBackup:
    """backup.py, run after every call that wrote to the notebook.

    Run by hand, it was not run: for three weeks every copy at the
    destination held nothing but a test fixture, and the notebook itself had
    no copy anywhere off this disk. So a write is what starts one.

    In the background, because a call that wrote has already answered, and
    at most one at a time per server: writes that land while one runs make
    ONE more run after it, which snapshots all of them. Across servers
    backup.py takes its own lock. A child process, not an import: its output
    must not reach stdout, which is this server's protocol channel, and its
    stdin must not be ours for the same reason (see rig._git).
    SAINPOST_AUTOBACKUP=0 turns it off.
    """

    SCRIPT = Path(__file__).resolve().parents[1] / "backup.py"

    def __init__(self):
        self._lock = threading.Lock()
        self._dirty = False
        self._running = False
        self.last: Optional[str] = None

    def changed(self) -> None:
        if os.environ.get("SAINPOST_AUTOBACKUP", "1") == "0" \
                or not self.SCRIPT.exists():
            return
        with self._lock:
            self._dirty = True
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._dirty:
                    self._running = False
                    return
                self._dirty = False
            self.last = self._once()
            if not self.last.startswith("ok"):
                print(f"sainpost: backup after write: {self.last}",
                      file=sys.stderr, flush=True)

    def _once(self) -> str:
        try:
            r = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--no-commit"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=300,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"failed: {e}"
        said = (r.stderr or "").strip()
        if r.returncode != 0 or "NOT SENT" in said:
            return f"failed ({r.returncode}): {said[-400:]}"
        return f"ok: {said[-400:]}"


_AUTO = _AutoBackup()


def _changes() -> int:
    return _STORE.db.total_changes if _STORE is not None else 0


def _guard(fn):
    """A refusal is an answer the caller can act on, not a stack trace.

    functools.wraps is load-bearing, not tidiness. FastMCP derives each
    tool's JSON schema with inspect.signature, which follows __wrapped__;
    without it every tool ships a schema of (*a, **kw) and the client is
    told to send two arguments named "a" and "kw". Nothing in-process
    notices, because calling the function directly skips validation
    entirely -- test_schema_advertises_the_real_parameters is the guard.
    """
    @functools.wraps(fn)
    def wrapped(*a, **kw):
        before = _changes()
        try:
            return fn(*a, **kw)
        except NoteError as e:
            return f"REFUSED: {e}"
        finally:
            # total_changes, not the tool's name: whether a call wrote is a
            # fact about the connection, and a list of "writing tools" is one
            # more thing to forget when a tool is added.
            if _changes() != before:
                _AUTO.changed()
    return wrapped


# --------------------------------------------------------------------------
# what each field is, said where the field is
#
# There are four places this server can teach the agent using it, and they
# are not equally strong:
#
#   a refusal      arrives at the moment of the mistake, about that mistake,
#                  and cannot be skimmed. Strongest by a distance -- but it
#                  can only reach a call that was made.
#   a field's own  arrives while the agent is filling that field in. Second,
#   description    and it was missing entirely: every parameter here used to
#                  advertise nothing but {"title": "Observed", "type":
#                  "string"}, while everything about what belongs in it sat
#                  in the tool description -- which is read when CHOOSING a
#                  tool, not when filling one in.
#   a tool's       arrives when choosing between tools. Good for that, and
#   description    a poor place for anything else.
#   the server     is read once, before any concrete situation exists, and
#   instructions   nothing goes wrong if it is skimmed. Weakest. Its one
#                  irreplaceable job is making an agent reach for a tool it
#                  would otherwise never call -- a call never made is the
#                  one thing no refusal can correct.
#
# So the commitments live here, on the fields, and the tool descriptions
# above them say when to reach for the tool rather than restating these.
# --------------------------------------------------------------------------

def _f(desc: str) -> object:
    return Annotated[str, Field(description=desc)]


def _fb(desc: str) -> object:
    """The same, for a flag. It exists because _f was used on one once, and
    the tool then advertised `{"type": "string", "default": false}` -- a
    schema that contradicts itself, to a client that fills in what it is
    asked for."""
    return Annotated[bool, Field(description=desc)]


Project = _f("The project this belongs to. Notebook-wide names; note_projects lists them.")
Hypothesis = _f("What you think is true, in one sentence.")
WhyNow = _f("Which prior RESULT sent you here. INTERPRETATION of n=1, stored and "
            "rendered as such -- never as measurement. Required once this project "
            "has a RESULT to name: before one exists -- the first attempt, and arms "
            "opened beside it -- there is none, and a paragraph saying so is not an "
            "answer. Leave it empty then.")
Headline = _f("This node in ONE line, at most 96 characters, written by you. "
              "Every view but note_open shows a node as one line; without this "
              "that line is your text with a machine's cut in it. Required only "
              "when the body is longer than the line -- a one-sentence node is "
              "already its own.")
Measure = _f("The quantity, and how it will be obtained.")
Cites = _f("What this stands on in ANOTHER project, as 'project/A4' or "
           "'project/Q2', comma-separated. A bare label means this project. "
           "Recorded as links, so every view reads the cited row as it stands "
           "now and warns when it has been annotated since -- which a name in "
           "prose cannot do. Prefix the role when it is not 'lean on this as a "
           "result': 'records:' cites what HAPPENED and warns on no verdict; "
           "'refutes:' leans on a rival having been killed, where FALSIFIED is "
           "the sound verdict and CONFIRMED or OPEN is the warning.")
Falsifier = _f("What the numbers look like IF THE HYPOTHESIS IS WRONG. Write the "
               "prediction that would make you drop it. If you cannot state one, "
               "this is not yet a measurement. Written now, before any data exists, "
               "because afterwards you will not be able to tell that you moved it.")
Apparatus = _f("The check that the rig itself is sound: versions, flags, which build "
               "is actually running, a control whose answer you already know. Most "
               "lost days are a stale or misconfigured rig producing plausible numbers.")
PromptedBy = _f("Label of the attempt whose RESULT sent you here, e.g. 'A3'. Not a "
                "taxonomic parent -- the one you had just read.")
ResultText = _f("The numbers. What was run, what came out, reproducible. Keep "
                "interpretation out of this field; it has its own.")
Verdict = _f("CONFIRMED | FALSIFIED | INCONCLUSIVE | ABANDONED. ABANDONED means a "
             "kill criterion fired -- a result about the budget. If nothing was "
             "measured at all because the rig broke, none of these apply: that is "
             "note_blocked.")
Invocation = _f("What you actually ran. Verbatim, the real call -- not 'I ran the "
                "router'. The owner reproduces from this.")
ObservedText = _f("What came back. VERBATIM -- the traceback, or the output that was "
                  "wrong. Do not summarise it: a summary is a reading you did not "
                  "check, and the owner cannot tell it apart from the output. A tool "
                  "that returned a plausible falsehood is reported here the same way "
                  "as one that crashed.")
Needed = _f("What your measurement needed in order to continue. About your attempt, "
            "not about their code.")
Owner = _f("The PROJECT that owns the broken apparatus. A project, not an agent -- "
           "and it may be your own. Filing against yourself is not a misuse: the "
           "fact BLOCKED records is that no measurement happened, which is true "
           "whoever has to fix it. Your own defect list is then what you must fix "
           "before you can measure.")
Cause = _f("What was actually wrong. Only you can write this -- the reporter saw a "
           "symptom and never measured a cause. For NOT_ACTIONABLE, say what is "
           "MISSING, so the re-filed one can carry it.")
Change = _f("What you altered.")
Verify = _f("What THEY run to confirm the fix before measuring again. Without it, "
            "'fixed' is a claim they have to take on trust.")
Invalidates = _f("NOTHING | EVERY_MEASUREMENT_ON_THIS_RIG -- whether numbers taken "
                 "on this rig BEFORE the fix still stand. It never asks about the "
                 "blocked attempt, which produced no number. A partial run can "
                 "leave plausible ones behind.")
#: Not a flag with a default. Both defaults are wrong for someone: true closed
#: a finished measurement as unmeasured, for good, when one reading in it was
#: false; false would leave a crashed one open. Only the reporter knows, so
#: with an attempt to touch and nothing said, the store refuses and asks.
Stopped = Annotated[Optional[bool], Field(description=(
    "Only when you have an attempt: did this stop its measurement? true -- no "
    "number came out; it closes as BLOCKED, 'not measured', and nothing "
    "reopens it. false -- it measured, and one reading in it was false; the "
    "defect is filed against that reading and the attempt stays open for "
    "note_result (a closed one keeps its verdict). Left out while an attempt "
    "is open, the call is refused and asks."))]


# --------------------------------------------------------------------------
# rendering -- the trunk is meant to be re-read constantly, so it is text
# rather than JSON: fewer tokens, and it reads like a whiteboard.
# --------------------------------------------------------------------------

def render_trunk(t: dict) -> str:
    if t.get("question") is None:
        head = [f"PROJECT {t['project']}", t.get("note", "no question yet")]
        for label, key in (("YOU ARE BLOCKED ON", "blocked_on"),
                           ("WAITING ON YOU", "waiting_on_you")):
            for d in t.get(key) or []:
                head.append(f"  {label}: {d}")
        return "\n".join(head)
    out = [f"PROJECT  {t['project']}"]
    for line in t.get("in_service_of") or []:
        out.append(f"  under  {line}")
    for r in t["reformulated_from"]:
        out.append(f"  was    {r['question']}  {r['text']}")
    head = f"QUESTION {t['question']}  {t['text']}"
    if t["status"] != "open":
        head += f"   [{t['status']}]"
    out.append(head)
    if t.get("superseded_by"):
        out.append(f"  became {t['superseded_by']}  (this question was replaced)")
    if t["answer"]:
        st = t.get("answer_is")
        said = (f", in their words: {st['user_said']}"
                if st and st.get("user_said") else "")
        if st and st["is"] in GONE:
            # Where it stands first, and the answer as one line under it. Whole,
            # it came to the front ahead of the note saying it no longer
            # stood -- and was cited again by whoever stopped reading there.
            out.append(f"  ANSWER {standing_head(st)}{said}")
            out.append("         It no longer stands. As written then, in one line: "
                       + (t.get("answer_headline") or _first_line(t["answer"], [])))
            out.append(f"         note_open('{t['project']}', '{t['question']}') "
                       f"gives it whole.")
        else:
            out.append(f"  ANSWER ({standing_head(st) if st else 'answered'}{said}) "
                       f"{t['answer']}")
    for ps in t.get("learned_later") or []:
        out.append(f"  LATER  ({ps['when'][:10]}{_moved(ps)}) {ps['text']}")
    for c in t.get("rests_on") or []:
        out.append(f"  RESTS ON {c}")
    out.append("")
    if not t["attempts"]:
        out.append("  (no attempts yet -- note_hypothesis pre-registers the first)")
    for a in t["attempts"]:
        arrow = f"  <-{a['prompted_by']}" if a["prompted_by"] else ""
        out.append(f"  {a['attempt']:<4} {a['verdict']:<12} {a['hypothesis']}{arrow}")
        if a["result"]:
            out.append(f"       -> {a['result']}")
        for n in a.get("learned_later") or []:
            src = f"shown by {n['shown_by']}" if n["shown_by"] else "INTERPRETATION"
            out.append(f"       LATER ({n['when'][:10]}, {src}) {n['text']}")
        for d in a.get("false_readings") or []:
            out.append(f"       a reading in it was false: {d}")
        for c in a.get("rests_on") or []:
            out.append(f"       RESTS ON {c}")
        if a["verdict"] == "OPEN":
            out.append(f"       falsifier: {a['falsifier']}")
            out.append(f"       apparatus: {a['apparatus']}")
            out.append(f"       open since {a['since']}")
    if t.get("opened_under_it"):
        out.append("")
        out.append("  OPENED UNDER IT -- this one cannot be answered until these are:")
        for line in t["opened_under_it"]:
            out.append(f"    {line}")
    if t["other_open_questions"]:
        out.append("")
        out.append("  other open questions in this project:")
        for q in t["other_open_questions"]:
            out.append(f"    {q}")
    # Why the front is empty, and whose front you are the reason for. Neither
    # is visible anywhere else the position gets read.
    if t.get("open_elsewhere"):
        out.append("")
        out.append("  STILL OPEN, under another question:")
        for o in t["open_elsewhere"]:
            out.append(f"    {o}")
    if t.get("blocked_on"):
        out.append("")
        out.append("  YOU ARE BLOCKED ON (note_open for the body):")
        for d in t["blocked_on"]:
            out.append(f"    {d}")
    if t.get("waiting_on_you"):
        out.append("")
        out.append("  WAITING ON YOU -- another project cannot measure until this is closed:")
        for d in t["waiting_on_you"]:
            out.append(f"    {d}")
    return "\n".join(out)


def _moved(ps: dict) -> str:
    """What a note did to the answer above it, beside its date. Empty for a
    note that left the answer where it stood."""
    return {"ENDORSED": ", the user ENDORSED the answer",
            "REJECTED": ", the user REJECTED the answer",
            "WITHDRAWN": ", answer WITHDRAWN"}.get(ps.get("answer_is") or "", "")


#: One line of a body, and a count of what is not shown. Answers are the bulk
#: of this render -- 94% of it on the project that hit the ceiling -- and the
#: rule was already written down two lines from the code that broke it: one
#: line per node, bodies from note_open.
def _first_line(text: str, tally: list, width: int = 96, line: bool = False) -> str:
    # `line` takes the first LINE rather than the first 96 characters of the
    # flattened body. An answer opens with its finding, so flattening reads
    # as a sentence; a question opens with the question and continues with
    # its materials, so flattening reads as the question running into a
    # bibliography.
    body = " ".join(((text.strip().splitlines() or [""])[0] if line
                     else text).split())
    tally.append(len(text))
    if len(body) <= width:
        return body
    return clip(body, width)[:-3] + f" ... (+{len(text) - width} chars)"


#: What one reply may spend, in UTF-8 bytes. Claude Code hands the model at
#: most 25,000 tokens of an MCP result and warns past 10,000; over the limit
#: the text goes to a file and the model gets a path instead -- the whole
#: trail, present as a filename. Bytes rather than characters because a
#: Japanese line is three bytes a character and roughly a token a character,
#: so counting characters passes three times too much of it.
BUDGET = 28_000

#: What a reply gives to the WHOLE trail before it stops trying. Past this,
#: the reply is the map instead: a project's record outgrows one reply long
#: before it outgrows the client's limit, and 28 KB of trail spent to answer
#: "where does this project stand" is 28 KB the work does not get. The map
#: names the branch to open, and one branch is the unit that fits.
FULL = 6_000

#: Room kept for the closing lines, which say what was left out. They are
#: the last thing that may be dropped: a view that quietly stops is the
#: failure this tool exists to prevent, arriving through the tool.
TAIL = 700


def render_path(t: dict) -> str:
    """The trail if it fits in one reply, and the map of it if it does not.

    Two shapes, one rule: a reply carries the whole thing while the whole
    thing is small, and otherwise carries what is needed to ask for the part
    you want. The record is a tree and this is the same move the tree made
    -- a line that says what is there, with the body one call below it.

    The digest comes FIRST and the chronology after it. An agent opening this
    is asking "what has already been ruled out here", not "what happened in
    what order" -- the order matters once you are already in the work. A
    FALSIFIED row is the most valuable kind in this record and it is worth
    nothing unread, so it is not left buried in the middle of a long trail.

    EACH FACT ONCE. The digest says what every attempt found and names the
    question it sits under; the tree is the shape -- one line per question,
    with what came of the attempts beneath it as a count. Printing the
    hypothesis in both put 275 attempts through twice and came to 170 KB,
    past what the client will hand the model at all.

    What does not fit is SAID, in nodes and in labels, with the call that
    opens it. A view that quietly stops is the failure this tool exists to
    prevent, arriving through the tool.
    """
    whole = _render_whole(t)
    if len(whole.encode()) <= FULL:
        return whole
    return _render_map(t, len(whole.encode()))


def _q_head(q: dict, full: list, width: int = 72) -> str:
    return q.get("headline") or _first_line(q["text"], full, width, line=True)


def _render_map(t: dict, size: int) -> str:
    """What is here and how to open it -- a page, not a trail.

    The branch being worked, then the open questions, then whatever was
    worked most recently. What is left is counted rather than listed: a
    label is enough to open a branch with, and note_search finds one by
    what it is about.
    """
    full: list = []
    qs = t["trail"]
    out = [f"PROJECT  {t['project']}" + (f"   {t['repo']}" if t["repo"] else ""),
           f"         {t['tally']}",
           f"         the whole trail is {size:,} bytes; this is the map of it"]
    for chain in t["reformulated"]:
        out.append(f"         reformulated:  " + " -> ".join(chain))
    # The tally counts them; this names them. A map lists a dozen questions,
    # and an answer that no longer stands is the one a reader must not
    # pick up from a branch the map left out.
    gone = [q for q in qs if (q.get("answer_is") or {}).get("is") in GONE]
    if gone:
        names = [f"{q['question']} ("
                 + ("REJECTED by the user" if q["answer_is"]["is"] == "REJECTED"
                    else "WITHDRAWN") + ")" for q in gone]
        out.append("         answers that no longer stand: " + ", ".join(names[:12])
                   + (f", and {len(names) - 12} more" if len(names) > 12 else ""))

    def line(q: dict, tag: str = "") -> str:
        counts = q.get("verdicts") or {}
        tail = ("  " + ", ".join(f"{n} {v}" for v, n in sorted(counts.items()))
                if counts else "  (nothing tried)")
        # Whose the answer is, on the one line a map gives a question: the
        # map is what a resuming agent reads, and "[answered]" read as a
        # settled claim.
        state = f"  [{q['state']}]" if q.get("state") else ""
        return f"  {tag:<7}{q['question']:<5}{_q_head(q, full)}{state}{tail}"

    def labels(q: dict) -> list:
        """A branch read on its own is usually one question with everything
        under it, and its attempts ARE its content: counted and not named,
        there is nothing left to open."""
        rows, by = [], {}
        for a in q["attempts"]:
            by.setdefault(a["verdict"], []).append(a["attempt"])
        for v, names in sorted(by.items()):
            line = f"         {v:<13}"
            for n in names:
                if len(line) + len(n) > 96:
                    rows.append(line)
                    line = " " * 22
                line += n + " "
            rows.append(line.rstrip())
        return rows

    seen, rows = set(), []
    live = [q for q in qs if q.get("live")]
    for q in live:
        seen.add(q["question"])
        rows.append(line(q, "NOW" if q is live[0] else ""))
        if t.get("branch"):
            rows += labels(q)
    openq = [q for q in qs if q["status"] == "open" and q["question"] not in seen]
    for i, q in enumerate(openq[:6]):
        seen.add(q["question"])
        rows.append(line(q, "OPEN" if not i else ""))
    worked = sorted((q for q in qs if q["question"] not in seen),
                    key=lambda q: q.get("last_touch") or "", reverse=True)
    for i, q in enumerate(worked[:4]):
        seen.add(q["question"])
        rows.append(line(q, "RECENT" if not i else ""))
    out += rows
    left = len(qs) - len(seen)
    if left:
        out.append(f"         ... and {left} more question(s), by label")
    p = t["project"]
    out.append(f"  READ   note_path('{p}', question='Q<n>')   one branch, closer in: "
               f"what each attempt found, while that fits")
    out.append(f"         note_trunk('{p}')   where the work is now, with the "
               f"falsifiers it committed to")
    out.append(f"         note_open('{p}', 'A12,Q7')   any node whole")
    out.append(f"         note_search('<what you are about to try>')   across every "
               f"project")
    return "\n".join(out)


def _render_whole(t: dict) -> str:
    full: list = []
    out = [f"PROJECT  {t['project']}" + (f"   {t['repo']}" if t["repo"] else ""),
           f"         {t['tally']}"]
    for line in t.get("in_service_of") or []:
        out.append(f"         under  {line}")
    if t.get("branch"):
        out.append(f"         one branch: {t['branch']} and what is under it. "
                   f"note_path without question= for the project.")
    for chain in t["reformulated"]:
        out.append("         reformulated:  " + " -> ".join(chain))

    # The map is bounded by the number of questions; the digest is bounded
    # by nothing, so it is the one that has to be told what it may spend.
    # Half each, and whatever the map does not use goes to the digest -- a
    # project with three questions should not have its dead ends cut to keep
    # room for a map that is four lines long.
    tree, tree_dropped = _render_tree(t, full, BUDGET // 2)
    # The header, the map and the closing lines are spoken for before the
    # digest is offered what is left. Counted in the rendered bytes rather
    # than estimated: an over-budget reply is one the client keeps out of
    # the model's hands entirely, so the number has to be the real one.
    spend = len("\n".join(out + tree).encode()) + TAIL
    digest, dropped = _render_digest(t, full, BUDGET - spend)
    if tree_dropped:
        dropped["questions whose answer and notes are not shown"] = tree_dropped
    out += digest + tree

    kept = sum(full)
    tail = []
    if dropped:
        tail.append("  NOT SHOWN: " + "; ".join(f"{n} {what}"
                                                 for what, n in dropped.items()) + ".")
        tail.append("  note_path(question='Q<n>') opens one branch whole; note_open "
                    "gives any label its body.")
    if kept:
        tail.append(f"  {len(full)} node(s) carry no headline and are cut to "
                    f"their first line here, {kept:,} characters in all.")
        tail.append("  note_open gives any of them whole, never truncated.")
    return "\n".join(out + ([""] + tail if tail else []))


def _digest_row(a: dict, full: list, verdict: bool = True) -> list:
    # The edge comes with it: prompted_by names the result that sent
    # somebody here, and that edge IS the path. It used to sit in the tree,
    # beside a copy of the hypothesis that is now printed only here.
    line = (f"      {a['attempt']:<5}{a.get('under', ''):<5}"
            + (f"{a['verdict']:<11} " if verdict else "")
            + (a.get("headline") or _first_line(a["hypothesis"], full))
            + (f"  <-{a['prompted_by']}" if a.get("prompted_by") else ""))
    rows = [line]
    if a.get("result"):
        rows.append(f"           -> {a['result']}")
    if a.get("defect"):
        rows.append(f"           {a['defect']}")
    # What was learned about the measurement afterwards belongs with the
    # measurement. It says the number should not be believed, which is the
    # one thing a reader scanning verdicts must not miss.
    for n in a.get("learned_later") or []:
        src = f"shown by {n['shown_by']}" if n["shown_by"] else "INTERPRETATION"
        rows.append(f"           LATER ({n['when'][:10]}, {src}) "
                    + (n.get("headline") or _first_line(n["text"], full)))
    for d in a.get("false_readings") or []:
        rows.append(f"           a reading in it was false: {d}")
    return rows


def _cost(lines: list) -> int:
    return len("\n".join(lines).encode()) + 1


def _render_digest(t: dict, full: list, budget: int) -> tuple:
    """What each attempt found. The branch being worked first, then the rest
    newest first, until the budget runs out.

    NOT SETTLED leads and is never cut: it is live work, it is short, and it
    is the half of the record somebody is standing in. Then what is
    standing, then the dead ends -- and within each, the question being
    worked now is the one whose neighbourhood is about to be re-derived.
    """
    out: list[str] = []
    dropped: dict = {}
    spent = 0
    for key, title, verdict in (
            ("open_now", "\n  NOT SETTLED", True),
            ("standing", "\n  STANDING -- what anything you do next will be resting on",
             False),
            # Confirmed, under an answer the user rejected or that was
            # withdrawn. Left in STANDING, hypotheses that WERE a rejected
            # claim sat in the list of what to rest on, and the note saying
            # so was one call away.
            ("no_longer_standing",
             "\n  NO LONGER STANDING -- confirmed, under an answer the user rejected "
             "or that was withdrawn. Do not rest on these as that answer.",
             False),
            ("closed_off",
             "\n  CLOSED OFF -- carried to a verdict already. Do not re-derive these.",
             True)):
        rows = sorted(t.get(key) or [],
                      key=lambda a: (not a.get("live"), -_seq(a["attempt"])))
        if not rows:
            continue
        section, left = [title], 0
        spent += len(title.encode())
        for i, a in enumerate(rows):
            block = _digest_row(a, full, verdict)
            if spent + _cost(block) > budget and (key != "open_now" or i):
                left = len(rows) - i
                break
            section += block
            spent += _cost(block)
        if left:
            section.append(f"      ... and {left} more; note_path(question=) opens "
                           f"a branch, note_open a label")
            dropped[title.split("--")[0].strip().lower()] = left
        out += section
    return out, dropped


def _seq(label: str) -> int:
    """The number in A12, or in A12@k7m -- a row from another notebook."""
    return int(label[1:].split("@")[0])


def _render_tree(t: dict, full: list, budget: int) -> tuple:
    """The shape of the project: one line per question, and what came of the
    attempts under it as a count. Bounded by the number of questions, which
    is what makes it the part that is never cut -- the attempts it counts
    are listed once, above, each naming the question it belongs to.

    An answer and a note are bodies, and a project with twenty answers spends
    its whole reply on them. The branch being worked keeps them; elsewhere
    they are named as the call that opens them.
    """
    ladder = [q for q in t["trail"] if q.get("live")] + \
             [q for q in reversed(t["trail"]) if not q.get("live")]
    extras, spent, dropped = set(), 0, 0
    for q in ladder:
        cost = len(str(q.get("answer") or "").encode()[:300]) + sum(
            len(str(ps["text"]).encode()[:300]) for ps in q.get("learned_later") or [])
        if not cost:
            continue
        if spent + cost > budget:
            dropped += 1
            continue
        extras.add(q["question"])
        spent += cost

    out = ["\n  THE PATH"]
    for q in t["trail"]:
        # Indented under the question it serves. An argument is a tree, and
        # printed flat it reads as a list of unrelated questions -- or worse,
        # as a chain of reformulations, which is what the digest above used
        # to call it.
        pad = "    " + "  " * q.get("depth", 0)
        head = (f"{pad}{q['question']}  "
                + (q.get("headline") or _first_line(q["text"], full, line=True)))
        if q.get("state"):
            head += f"  [{q['state']}]"
        out.append("\n" + head)
        body = pad + "    "
        counts = q.get("verdicts") or {}
        if not counts:
            out.append(f"{body}(nothing tried under this one)")
        else:
            out.append(f"{body}{sum(counts.values())} attempt(s): "
                       + ", ".join(f"{n} {v}" for v, n in sorted(counts.items())))
        if q["question"] not in extras:
            if q["answer"] or q.get("learned_later"):
                out.append(f"{body}[answer and notes: note_path(question="
                           f"'{q['question']}')]")
            continue
        if q["answer"]:
            st = q.get("answer_is")
            out.append(f"{body}ANSWER  "
                       + (f"({standing_words(st)}) " if st else "")
                       + (q.get("answer_headline") or _first_line(q["answer"], full)))
        for ps in q.get("learned_later") or []:
            out.append(f"{body}LATER   ({ps['when'][:10]}{_moved(ps)}) "
                       + (ps.get("headline") or _first_line(ps["text"], full)))
    return out, dropped


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

@mcp.tool()
@_guard
def note_projects() -> str:
    """Every project in the record, with its current position.

    Cheap, and the right first call in a session that is resuming work.
    """
    rows = store().projects()
    if not rows:
        return "No projects yet. note_start creates one."
    return _j(rows)


@mcp.tool()
@_guard
def note_start(project: Project,
               description: _f("What this investigation is about.") = "",
               repo: _f("Absolute path to the git repository this investigation "
                        "is about, if it is about code. Every node then records "
                        "the commit it was created against, and whether the "
                        "working tree differed from it. Read only: the notebook "
                        "never commits, moves a ref, or pushes. Leave empty for "
                        "an investigation that is not about a repository.") = ""
               ) -> str:
    """Create a project. Projects are never re-created, only added to.

    `description` says what is being investigated, in one or two sentences,
    for a reader six months from now who has none of your context.
    """
    return _j(store().start_project(project, description, repo))


@mcp.tool()
@_guard
def note_trunk(project: Project,
               question: _f("A Q-label to read instead of the current "
                            "position, e.g. 'Q1'.") = "") -> str:
    """WHERE YOU ARE. Re-read this at every checkpoint.

    Prints the current question, the chain of reformulations that led to it,
    and one line per attempt underneath -- hypothesis, verdict, and the
    measured result. An attempt that is still open also shows its falsifier
    and apparatus check, so you can see what you committed to before you
    started measuring.

    Deliberately small: this is meant to be re-read constantly. Full bodies
    come from note_open with the labels you see here.

    An answer prints with whose it is -- "not endorsed by the user" unless
    their own words were recorded. One that no longer stands (REJECTED by
    the user, or WITHDRAWN) prints that first, and itself as one line.

    `question` (a label like "Q2") reads a question other than the current
    one; omit it for where you actually are.
    """
    return render_trunk(store().trunk(project, question.strip() or None))


@mcp.tool()
@_guard
def note_path(project: Project,
              question: _f("Q-label, e.g. 'Q7': read that branch -- the "
                           "question, everything opened under it, and what it "
                           "serves. Omit for the project.") = "") -> str:
    """The whole path of trial and error in one project: what was ruled out,
    what is standing, and how the question moved to get here.

    note_trunk answers "where am I" and stays small by showing one question.
    This answers the other thing an agent arrives wanting: what has already
    been tried, so the days that bought those verdicts are not spent again.
    Read it when you pick up work you did not start, and before opening a
    line of attack in a project with any history.

    Each fact once: the digest says what every attempt found, the tree says
    where it sits. One line per node; bodies come from note_open. A project
    too big for one reply keeps the tree and the branch being worked, and
    names what it left out with the call that opens it -- `question=` reads
    one branch whole.

    Every answered question says whose its answer is: "not endorsed by the
    user" unless the user's own words were recorded with it. One the user
    REJECTED, or that was WITHDRAWN, no longer stands; what was confirmed
    under it is listed as NO LONGER STANDING instead of STANDING.
    """
    return render_path(store().trail(project, question.strip() or None))


@mcp.tool()
@_guard
def note_ask(project: Project,
             question: _f("What you do not know, as a question."),
             supersedes: _f("Q-label this replaces, e.g. 'Q1'. Reformulating the "
                            "question is usually the finding, so it is a node, "
                            "not a rename.") = "",
             parent: _f("Q-label this one is opened UNDER, e.g. 'Q1': a "
                        "requirement its answer will rest on. That question "
                        "cannot be answered while this one is open.") = "",
             headline: Headline = "") -> str:
    """Open a question and make it the project's current position.

    `supersedes` takes a question label (e.g. "Q1") when the OLD QUESTION
    TURNED OUT TO BE WRONG. Use it -- reformulating the question is usually
    the real finding ("is it the routing order?" -> "the pad frontage is
    blocked"), and the chain of reformulations is the most reusable thing in
    the record. Superseding closes the old question and links both ways, so
    its attempts stay readable instead of dangling under a dead question.

    `parent` says the opposite of `supersedes`: the earlier question was not
    wrong, this one is part of answering it -- "what does this claim
    require" under "what does it claim". The parent cannot be answered while
    anything under it is open, so an answer cannot skip a requirement it
    rests on, and note_path prints the tree instead of one flat chain.

    Opening a fresh, unrelated question needs neither; it stays in the
    trunk's footer.
    """
    return _j(store().ask(project, question, supersedes.strip() or None,
                          parent.strip() or None, headline.strip() or None))


@mcp.tool()
@_guard
def note_hypothesis(project: Project, hypothesis: Hypothesis, measure: Measure,
                    falsifier: Falsifier, apparatus: Apparatus,
                    why_now: WhyNow = "", prompted_by: PromptedBy = "",
                    question: _f("Q-label to open this under, e.g. 'Q3'. Defaults "
                                 "to the current question; naming one moves the "
                                 "position there. Refused while work is open under "
                                 "another question.") = "",
                    headline: Headline = "") -> str:
    """Pre-register an attempt, BEFORE measuring anything. This is the gate.

    Call it when you are about to go and find something out. Nothing has been
    measured at this point, and that is the whole point: the commitments on
    these fields are written while you are still clear-headed, and afterwards
    you would not be able to tell that you had moved one.

    RETURNS TWO SEARCHES, both across every project, because the only route
    to recording passes through them:

      already_tried -- hypotheses like this one that somebody carried to a
                       verdict. Read them before spending the time; a
                       FALSIFIED row here is days you do not spend.
      in_flight     -- hypotheses like this one that another agent has OPEN
                       right now, with their falsifier and apparatus. This
                       is not a refusal. Two measurements of one claim on
                       different apparatus is a replication and worth
                       having; the same measurement twice by accident is
                       waste, and only you can tell which from what is
                       returned.

    SEVERAL MAY BE OPEN AT ONCE UNDER THE CURRENT QUESTION -- competing
    hypotheses measured in parallel, each with its own falsifier. The reply
    lists the arms already open beside this one; compare their `measure`
    before you measure, or the two numbers will not answer the question
    together. Refuses while work is open under a DIFFERENT question, when
    prompted_by names an attempt with no result yet, and when any required
    field is blank.
    """
    return _j(store().hypothesis(project, hypothesis, why_now, measure,
                                 falsifier, apparatus,
                                 prompted_by.strip() or None,
                                 question.strip() or None,
                                 headline.strip() or None))


@mcp.tool()
@_guard
def note_result(project: Project, result: ResultText, verdict: Verdict,
                attempt: _f("Label, e.g. 'A3'. May be omitted only when one attempt is open.") = "",
                cites: Cites = "", headline: Headline = "") -> str:
    """Close the open attempt with what was measured. Once, and never edited.

    IF NOTHING WAS MEASURED, THIS IS THE WRONG TOOL. A crash, a wrong flag, a
    build that was never there -- no number came out, so no verdict here can
    be true, and ABANDONED is the tempting wrong answer: it means a kill
    criterion fired, which is a result about the budget, and a TypeError says
    nothing about the budget. Use note_blocked; it frees your front and files
    the defect against whoever owns the apparatus. Nothing refuses an
    ABANDONED you meant honestly, so this paragraph is the only thing
    standing between a lost day and a row that looks settled.

    A FALSIFIED row is the most valuable kind here. It is what stops the
    next session -- or the next agent -- spending days on something that
    looks like it obviously should work.

    The returned record includes the falsifier you committed to beforehand,
    so the call can be checked against the prediction rather than against
    memory of it.
    """
    return _j(store().result(project, result, verdict, attempt.strip() or None,
                             cites.strip() or None, headline.strip() or None))


#: Whose words count as the user's. Said on both fields that take them,
#: because the field is where it is read while being filled in.
_USER_WORDS = ("the USER's own words, VERBATIM, and where they said them -- e.g. "
               "「1にしよう。」 (chat, 2026-09-30). The user is the person this "
               "work is for. A message from an agent -- yours, or the one that "
               "delegated to you -- is not theirs, and a paraphrase is your "
               "reading of them, not their words.")


@mcp.tool()
@_guard
def note_answer(project: Project,
                answer: _f("What it turned out to be. Write it so it survives "
                           "without the path."),
                question: _f("Q-label. Defaults to the current question.") = "",
                cites: Cites = "", headline: Headline = "",
                user_said: _f(
                    "Only when the user decided this answer or accepted it as "
                    "theirs: " + _USER_WORDS + " Leave it empty otherwise: the "
                    "answer then shows in every view as 'not endorsed by the "
                    "user', which is the true state of an answer nobody has put "
                    "to them. If they accept or reject it later, note_postscript "
                    "records that.") = "") -> str:
    """Close a question with what it turned out to be. Answered is final.

    Write the answer so it survives without the path: state the finding, and
    state what the path adds that the finding alone does not (the near-miss
    that looks right and is not, the number that turned out to be an
    artefact). Refuses while an attempt under it is still open, and while
    any question opened under it is.

    WHOSE ANSWER IT IS. You write it, so it is an agent's answer, and every
    view marks it "not endorsed by the user" until the user's own words say
    otherwise (user_said). The next agent reads an answer back as settled:
    where the question was the user's to settle -- what a paper claims, what
    is in scope -- an agent's answer read that way is taken for theirs. One
    paper project traced part of its drafts' drift away from what its author
    had said to exactly that.
    """
    return _j(store().answer(project, answer, question.strip() or None,
                             cites.strip() or None, headline.strip() or None,
                             user_said.strip() or None))


@mcp.tool()
@_guard
def note_postscript(project: Project,
                    label: _f("What this attaches to: an answered question "
                              "('Q2'), a closed attempt ('A3'), a decided "
                              "request ('R3') or a closed defect ('D2'). R and "
                              "D are notebook-wide; only the two projects on "
                              "either side of one may add to it."),
                    text: _f("What turned out to be true later. Say what "
                             "changed the picture and what the record above "
                             "now misses -- not a rewrite of it."),
                    shown_by: _f("A-label of the attempt that DEMONSTRATED "
                                 "this, e.g. 'A9', read within `project`. Not "
                                 "on a question. Leave empty "
                                 "if nothing measured it -- the note then "
                                 "renders as INTERPRETATION, because a claim "
                                 "that a measurement was invalid is itself a "
                                 "claim.") = "",
                    headline: Headline = "",
                    answer_is: _f(
                        "Only on an answered question, and only when this note "
                        "changes where its answer stands. ENDORSED -- the user "
                        "accepted it as theirs. REJECTED -- the user said it is "
                        "not theirs, or is wrong. Both need user_said: whether "
                        "the user holds something is their call, and their words "
                        "are the record of it. WITHDRAWN -- your own finding that "
                        "it no longer stands (replaced, or wrong); no user_said. "
                        "Every view then marks the answer on its own line, and "
                        "confirmed attempts under a rejected or withdrawn answer "
                        "leave note_path's STANDING. Empty: the answer stands "
                        "where it did, and the note is only text.") = "",
                    user_said: _f("With answer_is ENDORSED or REJECTED, and only "
                                  "then: " + _USER_WORDS) = "") -> str:
    """Add what was learned later. Nothing already written is touched.

    ON A QUESTION ('Q2'): what its answer turned out to miss -- and, with
    answer_is, where the answer stands now: the user ENDORSED it as theirs
    or REJECTED it (their words in user_said), or you WITHDREW it. Every
    view then marks the answer on its own line. Said only in the text, a
    correction sat under an answer whose line still read as settled, and
    the next agent cited the answer again.

    ON AN ATTEMPT ('A3'): what its result turned out to be worth -- for the
    measurement that was INVALID and nobody noticed. A sweep against a
    broken rig gives a plausible number, indistinguishable from a sound one
    once written down. A finding that merely went out of date is a new
    attempt with prompted_by pointing at the old one. The verdict is not
    revised: it is bound to a falsifier written before the data. A note
    adds that the number should not be believed, and why.

    The original and the note are both kept, each with its own date, and
    both print wherever the original does. Rewriting the original to look
    like what you know now destroys what made it worth recording: what was
    believed at the time, and on what evidence.

    ON A REQUEST ('R3') OR A DEFECT ('D2'): what the decision or the fix
    turned out to rest on -- a count, a named cause, that turned out wrong.
    The decision stands, as a verdict does. Only its two sides may write
    one, and the note says which side wrote it.

    Not a comment thread, and not for anything still open: keep working
    under an open question, or supersede it; a live defect has note_query.
    """
    return _j(store().postscript(project, label, text, shown_by.strip() or None,
                                 headline.strip() or None,
                                 answer_is.strip() or None,
                                 user_said.strip() or None))


@mcp.tool()
@_guard
def note_open(project: Project,
              labels: _f("Comma-separated labels from the trunk, mixed: "
                         "'A3', 'A3,A5,Q1', 'D2', 'R4'. Q and A labels are per "
                         "project and are read within `project`. D and R "
                         "labels are notebook-wide and resolve the same from "
                         "anywhere, so you can open a defect or a request "
                         "filed by another project. One carried from another "
                         "notebook under a number held here is 'R4@3fa2c1'.")
              ) -> str:
    """Full bodies for named nodes. Nothing is truncated.

    `labels` is a comma-separated list of labels from the trunk: questions,
    attempts, defects and requests mixed, "A3", "A3,A5,Q1", "D2", "R4". A
    defect shows what the reporter observed and, once closed, what the owner
    found. A request shows what was wanted and why, and once decided, the
    decision. An attempt shows its
    pre-registered falsifier and apparatus alongside the measured result,
    and lists the attempts it went on to prompt.

    Text written in another machine's notebook cites that notebook's
    numbers. Where a bare "R6" in it is a different record here, the body
    names the one it meant ("labels in text from another notebook"); the
    text itself is as written.
    """
    names = [s for s in (x.strip() for x in labels.split(",")) if s]
    if not names:
        return "REFUSED: give at least one label, e.g. labels=\"A3,Q1\""
    return _j(store().open(project, names))


@mcp.tool()
@_guard
def note_blocked(project: Project, invocation: Invocation, observed: ObservedText,
                 needed: Needed, owner: Owner,
                 attempt: _f("Label, e.g. 'A3'. May be omitted only when one "
                             "attempt is open. 'none' when no measurement of "
                             "yours is involved -- a bug in a tool you are only "
                             "using -- which omitting cannot mean while arms are "
                             "open. With stopped=false it may be a closed one: "
                             "the attempt the false reading was taken in.") = "",
                 supersedes: _f("Re-file one that came back unresolved, e.g. 'D1'.") = "",
                 stopped: Stopped = None) -> str:
    """The apparatus broke, or told you something false, and the fix belongs
    to its owner. Files the defect; `stopped` says what it did to your
    attempt.

    stopped=true: no number came out -- a crash, a wrong flag, a missing
    build. The attempt closes as BLOCKED, the only verdict that says NOTHING
    about the hypothesis, and your front is freed. Not for a measurement
    that ran and disappointed you: that is INCONCLUSIVE, via note_result.

    IT ALSO COVERS A TOOL THAT WORKED AND TOLD YOU SOMETHING FALSE -- a
    position that is not the position, a headline that says the opposite of
    what it holds. A plausible wrong answer is worse than a crash, and it
    belongs here, not in note_request. The same goes for any tool with a
    project here, this notebook included. If the rest of the measurement
    stands, stopped=false: the defect is linked to the attempt as a reading
    inside it, and the attempt stays open for note_result. With no attempt
    of yours, nothing is closed; where you were is read from the record.

    WHAT YOU WRITE IS WHAT YOU SAW. There is no field for the cause or the
    fix, deliberately: you measured a symptom, not a cause. A cause asserted
    without measurement and acted on by another agent is an unverified
    intermediate promoted to a fact across an agent boundary -- the failure
    this record exists to prevent. Keep it out of `observed` too; `cause`
    lives on the closing side, in note_fixed.

    The rig, the measure and the hypothesis are inherited from the attempt;
    do not restate them. When it comes back FIXED, run the `verify` it gives
    you, then open a NEW attempt with prompted_by pointing at the blocked
    one. `supersedes` re-files one that came back unresolved.
    """
    return _j(store().blocked(project, invocation, observed, needed, owner,
                              attempt.strip() or None, supersedes.strip() or None,
                              stopped))


@mcp.tool()
@_guard
def note_fixed(defect: _f("The defect label, e.g. 'D1'."),
               resolution: _f("FIXED | NOT_REPRODUCIBLE | NOT_ACTIONABLE | "
                              "NOT_A_DEFECT. Each tells the stopped party something "
                              "different about whether to measure again."),
               cause: Cause, change: Change = "", verify: Verify = "",
               invalidates: Invalidates = "") -> str:
    """Close a defect from the side that owns the apparatus. Once, never edited.

    Somebody else's measurement is standing still until you do. note_defects
    lists what is waiting on you, and it appears in your own trunk.

      FIXED            -- also requires change, verify and invalidates.
      NOT_REPRODUCIBLE -- also requires verify. It running here and not there
                          means the two rigs differ, and that difference is an
                          apparatus finding they need; "works for me" is not.
      NOT_ACTIONABLE   -- you cannot act on what you were given. They re-file
                          with supersedes=; nothing here is edited.
      NOT_A_DEFECT     -- the rig is sound and was used wrongly. Saying how
                          unblocks them just as well as a fix would.
    """
    return _j(store().fixed(defect, resolution, cause, change, verify, invalidates))


@mcp.tool()
@_guard
def note_query(defect: _f("The defect label, e.g. 'D1'. Labels are notebook-wide, "
                          "not per project."),
               project: _f("Your side of it -- either the project that filed the "
                           "defect or the one that owns the apparatus."),
               question: _f("What you need from the other side before you can "
                            "act. One question -- make it the one that is "
                            "actually in your way.")) -> str:
    """Ask the other side of a defect something, WITHOUT closing it.

    EITHER SIDE. If you own it: the crash is one line but nothing says what the
    thing was supposed to do, and every other lever here is a resolution --
    NOT_ACTIONABLE is untrue when the defect is actionable and yours. If you
    filed it: `needed` was a one-shot at filing time and could not carry a
    question that only they can answer.

    Exactly one question, and one reply from the other side. A second exchange
    means the report itself was wrong: close it NOT_ACTIONABLE and let them
    re-file. This is a round trip, not a thread; nothing here grows a comment
    box.
    """
    return _j(store().query(defect, project, question))


@mcp.tool()
@_guard
def note_reply(defect: _f("The defect label, e.g. 'D1'."),
               project: _f("Your side of it. You cannot answer a question you "
                           "asked yourself."),
               answer: _f("Your answer. If the honest answer is that nobody "
                          "knows, say that -- it is the answer that stops them "
                          "inventing one.")) -> str:
    """Answer the one question the other side asked. Closes nothing either.

    They are stopped until you do: it appears in your trunk, and note_defects
    on your project shows it.
    """
    return _j(store().reply(defect, project, answer))


@mcp.tool()
@_guard
def note_request(project: Project,
                 wanted: _f("What you want to be able to do. Name the shape if "
                            "you have one -- batching, a different default, a "
                            "field that is missing. You know your own need, and "
                            "saying so is allowed here."),
                 because: _f("What you were DOING when you wanted it, and what "
                             "not having it cost. Not that it would be nice: "
                             "\"writing one at a time is tedious\" is a "
                             "preference, \"Q1 through Q13 went in as thirteen "
                             "separate calls\" is an observation."),
                 owner: _f("The PROJECT that owns the tool. This notebook's own "
                           "project is sainpost-itself.")) -> str:
    """Ask the owner of a tool to make it do something it does not do.

    Nothing is broken, so this is not a defect and does not need a
    measurement of yours to be stopped. What keeps it from being a wish is
    `because`: a defect proves it happened by pasting what came back, and a
    request has no output to paste, so the cost of not having the thing is
    what carries the weight.

    NAMING THE SHAPE YOU WANT IS FINE HERE, unlike on a defect. What stays
    forbidden everywhere is telling an owner how to fix something that BROKE
    -- that is a claim about code you do not own. Wanting a tool to do
    something is not that claim.

    It appears in the owner's trunk beside the defects, and they close it with
    note_decide.
    """
    return _j(store().request(project, wanted, because, owner))


@mcp.tool()
@_guard
def note_decide(request: _f("The request label, e.g. 'R1'."),
                decision: _f("ACCEPTED | DECLINED. It is your call: you own "
                             "the tool."),
                why: _f("Required on both. DECLINED with no reason reads as "
                        "nobody looked. ACCEPTED with none loses what was "
                        "actually agreed to, which is rarely the whole of "
                        "what was asked.")) -> str:
    """Take a request or turn it down. Once, with the reason either way."""
    return _j(store().decide(request, decision, why))


@mcp.tool()
@_guard
def note_defects(project: _f("Your project, to see both directions -- what you "
                             "owe and what you are owed. Empty for the whole "
                             "machine.") = "",
                 closed: _fb("Include defects that have been resolved. They are "
                             "real history -- what broke and what it turned out "
                             "to be -- and they leave every other view once "
                             "closed.") = False) -> str:
    """Every measurement currently stopped on somebody else, machine-wide.

    This is the list to read when you want to know what is waiting on you:
    pass your project to see both directions (what you owe, what you are
    owed), or nothing to see the whole machine.

    It cannot turn into a wishlist. A row exists only while a specific
    pre-registered measurement is stopped by it, and it disappears the moment
    that is resolved -- which is the difference between this and a backlog.
    """
    return _j(store().defects(project.strip() or None, closed))


@mcp.tool()
@_guard
def note_export(project: Project,
                path: _f("Where to write it. Empty: <repo>/.sainpost/"
                         "<project>.json in the repository the project "
                         "records. A directory is taken as a repository root; "
                         "a path ending in .json is used as given.") = ""
                ) -> str:
    """Write one project's record into a file, for another machine's notebook.

    The notebook is per machine; the file travels however the code does --
    commit it, and the other machine pulls it and runs note_import. Export
    when you stop working on the project here.

    It refuses to overwrite a file that carries records this notebook does
    not have yet: that is the other machine's work on its way here. Import
    it first. The file is a pure function of the record -- no timestamp, no
    host -- so an export that learned nothing changes nothing.

    This is the one thing the notebook writes into a repository it
    observes. Committed while an attempt is open, the file moves HEAD, and
    that attempt will close against a different commit than it opened on.
    """
    return _j(share.export_project(store(), project, path.strip() or None))


#: A name the other notebook writes, read as a project here. Not a string:
#: it is a mapping, and advertising it as one is what lets a client send it.
Rename = Annotated[Optional[dict[str, str]], Field(description=(
    "Read a project the file names as a project here: {name in the file: "
    "project here}, e.g. {\"cadbridge\": \"CadBridge\"}. It applies to the "
    "file's own card and to every request and defect naming it as a side, "
    "and it is recorded, so later imports read that name the same way. A "
    "question or attempt that differs is still refused at its label, so "
    "what it can join is a card with nothing to renumber."))]


@mcp.tool()
@_guard
def note_import(path: _f("A file note_export wrote, or a repository root -- "
                         "every .sainpost/*.json it carries is imported, "
                         "each on its own."),
                dry_run: _fb("Write nothing; say what the import would do -- "
                             "which project it lands in, what it adds, which "
                             "numbers it finds already held here, and which "
                             "carried text cites a label that is another "
                             "record here.") = False,
                rename: Rename = None) -> str:
    """Merge a project's record from another machine into this notebook.

    Call it BEFORE writing anything to that project here: at the start of a
    session on a machine that was not the last to work on it. Rows this
    notebook lacks are added; attempts closed, questions answered, requests
    decided over there are closed here too. Nothing already here is
    overwritten. dry_run=True runs the same merge and rolls it back.

    A project is matched by its exact name, or by rename=. A file whose
    project is new here becomes a new project, and the result says when
    another one already records the same repository or differs only in case.

    Questions and attempts are matched by what they were made with, not by
    number. Both machines adding to the project without importing first is
    the ordinary case: a number both used arrives after the name of the
    notebook that wrote it -- Q20@k7m -- and nothing is renumbered, since
    labels are cited inside other records. Refused, with nothing written,
    where the two are not one project: its card was made separately on each
    side (rename= brings the file in beside it; note_merge joins two records
    that are one investigation), or a row closed differently on each side.

    Requests and defects are numbered per machine, so their numbers collide
    as a matter of course. One whose number is held here by a different
    record comes across anyway, keeping its number, labelled with its hash:
    R6@3fa2c1. The record already here keeps its bare label. Carried text
    is not rewritten; note_open on it names what each bare label it cites
    means here.
    """
    return _j(share.import_path(store(), path, dry_run, rename))


@mcp.tool()
@_guard
def note_merge(into: _f("The project that continues. Its name is the one kept."),
               absorbed: _f("The project whose questions and attempts move into "
                            "`into`. Its name is read as `into` from then on -- "
                            "by every tool here and by imports of files that "
                            "still use it.")) -> str:
    """Join two projects that are one investigation, written on two machines.

    Every question and attempt moves and keeps its number, because text
    cites numbers and a renumbered row changes what that text says. A number
    both projects hold prints bare for the row written in THIS notebook and
    after its notebook's name for the other (Q12@k7m). A bare label inside
    moved text still means the row its writer meant; note_open on it says
    which. note_export(into) carries the merge: the other notebook makes the
    same merge when it imports that file.

    Refused where that cannot hold: a row carried in before files said
    which notebook wrote it (import that notebook's current export first), a
    number one notebook used in both, or one notebook with work open under a
    question in each. Not undone -- it is a claim that the two were always
    one investigation.
    """
    return _j(store().merge(into, absorbed))


@mcp.tool()
@_guard
def note_search(query: str, project: str = "") -> str:
    """Search hypotheses, questions and answers across every project.

    Cross-project by default -- the point of one shared record is that a
    hypothesis killed on one board is killed for the next one too. Pass
    `project` to stay inside one.

    Note that you do not have to remember to call this before starting work:
    note_hypothesis runs the same search on the way in.
    """
    return _j(store().search(query, project.strip() or None))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
