"""Sainpost store — the append-only record. No MCP in this module.

WHY THIS EXISTS
A long investigation does not fail by running out of context. It fails when
an unverified intermediate gets promoted to a fact and every later step is
reasoned correctly on top of it. The observed shape, over and over, is not
"the thinking diverged" but "the footing dropped out and nobody noticed".

Humans did not solve that with better filing. They solved it with two things
a reference cannot do: a commitment made BEFORE the data (protocol,
pre-registration, positive control, kill criteria), and something that
arrives from outside on a schedule (seminar, advisor, referee, deadline).
This module is the first of those, in schema:

  * An attempt is created with its hypothesis, what will be measured, WHAT
    RESULT WOULD FALSIFY IT, and the check that the apparatus is sound --
    all before any number exists. It is then closed exactly once with the
    result and a verdict. There is no update path. You physically cannot
    record an outcome you did not pre-register a falsifier for.

  * The record is a TREE, not a list. A flat index answers "is this known?".
    A tree answers "where am I?", and being lost is precisely the loss of
    position. The edge is not a taxonomic parent -- you do not know the
    parent while you are still lost. The edge is `prompted_by`: which prior
    RESULT made you try this. That you always know at write time, and the
    tree assembles itself afterwards.

  * A question can be SUPERSEDED by another question. Reformulating the
    question is usually the actual finding ("is it the order?" -> "the pad
    frontage is blocked"), so it is a first-class node rather than a rename
    that silently orphans every child.

MEASUREMENT AND INTERPRETATION ARE SEPARATE FIELDS
`result` is numbers, reproducible. `verdict` is the call. `why_now` is
interpretation of n=1 and is labelled as such wherever it is rendered. The
narrative of a path is exactly where interpretation gets promoted to
measurement, so the three never share a field.

IDENTITY
Labels are per project and stable: Q1, Q2 ... for questions, A1, A2 ... for
attempts. They are what the trunk prints and what `open` takes back. A
number is not unique, though: two notebooks working one project each number
their own work, so a row is its number and what it was made with (`ident`),
and it carries the notebook that wrote it (`origin`). A number held twice
prints bare for the first holder here and after the writer's name for the
other -- Q20@k7m -- and nothing is ever relabelled to fit.

Requests and defects are numbered notebook-wide (R1, D1 ...), and a record
carried from another machine's notebook keeps its number, so one number can
name two records here. A row is its number and what it was created with; the
first to hold a number here prints it bare, and a later one prints it with
that content's hash: R6@3fa2c1. Nothing already here is ever relabelled.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from sainpost import rig

#: Verdicts an attempt can close with. ABANDONED is not a failure of the
#: hypothesis -- it is a kill criterion firing, which is a result about the
#: budget and worth keeping for the same reason a falsification is. BLOCKED
#: is the one verdict that says nothing whatever about the hypothesis: the
#: measurement did not happen, because the apparatus broke. It cannot be
#: reached through `result` -- only through `blocked`, which will not accept
#: it without a defect naming who owns the fix.
VERDICTS = ("CONFIRMED", "FALSIFIED", "INCONCLUSIVE", "ABANDONED", "BLOCKED")

#: `result` is for measurements. This one is not a measurement.
_VERDICTS_BY_HAND = tuple(v for v in VERDICTS if v != "BLOCKED")

#: How a request closes. Not the defect vocabulary: a request is not broken
#: and cannot be fixed, it is wanted or it is not, and either way the reason
#: is what the asker gets back.
DECISIONS = ("ACCEPTED", "DECLINED")

#: How a defect closes. Each says something different to the party who is
#: still stopped, which is the only reason the vocabulary is closed.
RESOLUTIONS = ("FIXED", "NOT_REPRODUCIBLE", "NOT_ACTIONABLE", "NOT_A_DEFECT")

#: Whether numbers already recorded on this rig survive the fix. Closed
#: vocabulary rather than prose, because it is written on every fix and
#: prose written on every fix stops being read.
#:
#: It asks about OTHER measurements, never the blocked one. The blocked
#: attempt produced no number by definition, so "this invalidates the
#: blocked attempt" is a sentence with nothing in it -- a cold agent hit
#: that value, could not make it mean anything, and picked NOTHING while
#: saying it was unsure what was being asked.
INVALIDATES = ("NOTHING", "EVERY_MEASUREMENT_ON_THIS_RIG")

#: What a citation does with the row it names, which decides only which
#: warnings are true of it.
#:
#: `supports` leans on it as a result: a verdict that is not CONFIRMED is a
#: warning. `records` cites it as something that happened -- a falsified
#: attempt cited BECAUSE it was falsified -- and no verdict warns; nine such
#: citations produced six warnings, five of them "not a standing result",
#: and the one that mattered was a line among them. `refutes` leans on it
#: the way this record says to: a FALSIFIED row is the most valuable kind
#: here, and an argument standing on a rival explanation having been killed
#: is standing on exactly that. There the warning turns around -- CONFIRMED,
#: OPEN or INCONCLUSIVE means there is no refutation to lean on. Filed as
#: `records` instead, it would stop warning, and also stop saying that
#: anything was leaning on it.
ROLES = ("supports", "records", "refutes")

#: A question that has been answered or replaced accepts no further work.
QUESTION_STATES = ("open", "answered", "superseded", "abandoned")

#: What a note can say about the answer it is written under. The first two
#: are the user's call and carry their words; the third is the writer's own
#: finding. An answer no note has spoken to is NOT_ENDORSED -- not stored,
#: because it is what every answer an agent writes is until the user says
#: otherwise.
ANSWER_IS = ("ENDORSED", "REJECTED", "WITHDRAWN")

#: The two after which an answer no longer stands.
GONE = ("REJECTED", "WITHDRAWN")


class NoteError(Exception):
    """A refusal the caller can act on. The message says how to proceed."""


def data_home() -> Path:
    """Where this machine keeps per-user application data.

    The notebook is machine-wide -- every project on the host shares one
    record, which is the whole reason it lives outside any repository -- so
    this has to answer the same thing no matter what launched the server.

    That is why Windows does not consult XDG_DATA_HOME. A git-bash, msys or
    WSL-interop shell exports it, so honouring it would open a SECOND
    notebook whenever the server happened to be started from one, and the
    two are not distinguishable from inside: each looks like a complete
    record that is simply missing the other's work. SAINPOST_DB stays
    the one deliberate way to move it.
    """
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) if local else Path.home() / "AppData" / "Local"
    return Path(os.environ.get("XDG_DATA_HOME")
                or Path.home() / ".local" / "share")


def default_db_path() -> Path:
    env = os.environ.get("SAINPOST_DB")
    if env:
        return Path(env).expanduser()
    return data_home() / "sainpost" / "research.db"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    description      TEXT NOT NULL DEFAULT '',
    current_question INTEGER,
    -- A question asked while work was open here, waiting for the front to
    -- clear. Written when it is asked, because that is where "asked in the
    -- meantime" is a fact rather than something reconstructed from the
    -- numbering or from a clock that ticks in whole seconds.
    waiting_question INTEGER,
    repo             TEXT NOT NULL DEFAULT '',
    -- 1 while this project exists only because a defect had to be filed
    -- against it. Its own team has not written its card yet, and until they
    -- do, note_start will let them -- once.
    stub             INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    -- Set on a project whose rows were moved into another (Store.merge).
    -- The row stays so its name keeps meaning something: a call, a file or
    -- another machine that still says it is read as the project it joined.
    merged_into      INTEGER REFERENCES projects(id),
    merged_at        TEXT
);

-- This notebook's own name: three characters, made the first time it is
-- opened and never changed. A row written here carries it (origin), and a
-- row from elsewhere whose number is taken here prints it: Q12@k7m. It is in
-- the labels agents copy into text, so changing it would change what that
-- text says. One row, and a second insert is ignored: every session opens
-- the notebook at once, and only one of them names it.
CREATE TABLE IF NOT EXISTS notebook (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id),
    seq           INTEGER NOT NULL,
    text          TEXT NOT NULL,
    -- One line, written by whoever wrote the body, saying what this asks.
    -- Every view but note_open shows a node as one line, and that line used
    -- to be the body with a machine's cut in it -- a summary nobody wrote
    -- and nobody checked, which is the one kind of claim this record does
    -- not allow anywhere else. It also cut badly: a 97-character Japanese
    -- question came out as its four-character tag. Required only where the
    -- cut would happen, so a one-sentence question still needs nothing.
    headline      TEXT,
    status        TEXT NOT NULL DEFAULT 'open',
    answer        TEXT,
    answer_headline TEXT,
    -- The user's own words, verbatim, accepting the answer as theirs when it
    -- was written. "The user" is the person the work is for; no agent's
    -- message is theirs. NULL: nothing records them accepting it, and every
    -- view shows it as not endorsed by the user -- which is what an answer
    -- an agent wrote is. A paper's claim was one such answer, read back by
    -- each resumed session as the author's, and the paper moved further
    -- from what its author had said every time. A note can change this
    -- later (postscripts.answer_is); the latest one is where it stands.
    answer_user_said TEXT,
    supersedes    INTEGER REFERENCES questions(id),
    superseded_by INTEGER REFERENCES questions(id),
    -- The question this one was opened UNDER: what it has to settle before
    -- its parent can be answered. An argument is a tree -- "what does this
    -- claim require" hangs off "what does it claim" -- and the only relation
    -- there used to be said the earlier question was WRONG. Used for a
    -- requirement that would be a lie, and left off, the requirement became
    -- a question related to nothing, which the digest then printed as one
    -- more reformulation. A replacement keeps the parent of what it replaced.
    parent        INTEGER REFERENCES questions(id),
    created_at    TEXT NOT NULL,
    closed_at     TEXT,
    -- Q and A numbers were unique in a project, and that is what made two
    -- records of one investigation impossible to join: both had a Q1..Q19,
    -- and their text cites those numbers, so neither could be renumbered.
    -- Requests and defects had met the same thing a fortnight later and been
    -- given the answer this now shares: a row is its number AND what it was
    -- made with (`ident`, the same on every machine), and a number held twice
    -- prints the later holder qualified.
    ident         TEXT,
    -- The notebook that wrote it (notebook.name). NULL only on a row carried
    -- in before files said where their rows were written.
    origin        TEXT,
    -- How THIS notebook prints it after its number: '' is bare, anything
    -- else is the origin of a row whose number a row here already held.
    -- Set when the row arrives -- by import, or by a merge -- and never
    -- after, so a label, once printed here, keeps meaning the same row.
    qual          TEXT NOT NULL DEFAULT '',
    UNIQUE (project_id, seq, qual)
);

CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    seq         INTEGER NOT NULL,
    hypothesis  TEXT NOT NULL,
    headline    TEXT,            -- the claim in one line; see questions.headline
    why_now     TEXT NOT NULL,
    prompted_by INTEGER REFERENCES attempts(id),
    measure     TEXT NOT NULL,
    falsifier   TEXT NOT NULL,
    apparatus   TEXT NOT NULL,
    result      TEXT,
    result_headline TEXT,        -- what fell over, in one line
    verdict     TEXT,
    -- the exact code this was pre-registered against, and closed against.
    -- Two different commits mean the code moved under the measurement.
    open_commit     TEXT,
    open_dirty      INTEGER,     -- tracked files differed from the commit
    open_untracked  TEXT,        -- files in no commit, by name
    close_commit    TEXT,
    close_dirty     INTEGER,
    close_untracked TEXT,
    created_at  TEXT NOT NULL,
    closed_at   TEXT,
    ident       TEXT,            -- see questions.ident
    origin      TEXT,            -- see questions.origin
    qual        TEXT NOT NULL DEFAULT '',   -- see questions.qual
    UNIQUE (project_id, seq, qual)
);

-- What was learned about a question AFTER it was answered.
--
-- The answer is never touched. An answer quietly improved is the failure
-- this whole record exists to stop, wearing its own clothes: you lose the
-- one thing that made it worth writing down, which is what was believed at
-- the time and on what evidence. So a later finding is a separate row with
-- its own date, and both are rendered, in order, forever.
--
-- Not a comment thread. A postscript says what turned out to be true, and
-- an answered question can accrue more than one over years -- but each is
-- written once and never edited, like everything else here.
--
-- `answer_is` is what the note does to the answer, when it does something:
-- 'ENDORSED' (the user accepted it as theirs) and 'REJECTED' (the user said
-- it is not theirs, or is wrong) carry `user_said`, their words verbatim;
-- 'WITHDRAWN' is the writer's own finding that it no longer stands. A
-- correction written only in `text` sat under an answer whose own line went
-- on reading as settled, and an agent that did not open the note cited the
-- answer again. The latest note that sets it says where the answer stands
-- now; every one is kept.
CREATE TABLE IF NOT EXISTS postscripts (
    id          INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    text        TEXT NOT NULL,
    headline    TEXT,            -- see questions.headline
    answer_is   TEXT,            -- NULL | ENDORSED | REJECTED | WITHDRAWN
    user_said   TEXT,            -- the user's words, with ENDORSED or REJECTED

    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS postscripts_by_question ON postscripts (question_id, id);

-- What was learned about an ATTEMPT after it closed. The verdict is never
-- touched, and neither is the result.
--
-- The case this exists for is not an outdated finding -- that is a new
-- attempt with an edge back -- but a measurement that was INVALID and that
-- nobody noticed. A sweep run against a broken rig produces a plausible
-- number, and once written down it is indistinguishable from a sound one.
-- Nothing could mark it. A record that is quietly wrong is worse than one
-- that is merely old, and it is the exact failure this notebook exists for.
--
-- `shown_by` names the attempt that demonstrated it. It is optional, because
-- sometimes you simply read the rig and see it -- but a note without one is
-- rendered as INTERPRETATION, the same way why_now is, because a claim that
-- a measurement was invalid is itself a claim and it is not free.
CREATE TABLE IF NOT EXISTS attempt_notes (
    id         INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    shown_by   INTEGER REFERENCES attempts(id),
    text       TEXT NOT NULL,
    headline   TEXT,             -- see questions.headline

    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS attempt_notes_by_attempt ON attempt_notes (attempt_id, id);

-- A result or an answer standing on a record in ANOTHER project.
--
-- Prose could already name one, and that is the problem: a name in a
-- sentence is not checked and does not change when what it names does. A
-- paper's claim rested on twenty attempts in a board's notebook; one of
-- them had since been annotated -- the number it reported was an artefact --
-- and the citing text went on reading as sound. That is this record's own
-- failure, an unverified intermediate promoted to a fact, crossing a
-- project boundary where nothing was watching for it.
--
-- So a citation is a row, and what it names is read at the moment it is
-- read: the cited verdict as it stands now, and anything learned about it
-- since `created_at` here. Nothing about the cited record changes, and
-- nothing about this one: the warning is computed, never stored.
CREATE TABLE IF NOT EXISTS citations (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,          -- 'A' or 'Q': what is doing the citing
    node_id      INTEGER NOT NULL,
    to_project   TEXT NOT NULL,
    to_kind      TEXT NOT NULL,
    to_seq       INTEGER NOT NULL,
    to_created   TEXT,                   -- identity of the cited row across machines
    to_id        INTEGER,                -- NULL: not in this notebook
    -- What the citation is DOING with the cited row. 'supports' leans on it
    -- as a result, so a verdict that is not a standing one is a warning.
    -- 'records' cites it as an event that happened -- a falsified attempt
    -- cited BECAUSE it was falsified -- where that warning is true and
    -- means nothing. Nine such citations produced six warnings, five of
    -- them "it is FALSIFIED, which is not a standing result", and the one
    -- that mattered was a line among them. A warning stops being one when
    -- it is always there.
    role         TEXT NOT NULL DEFAULT 'supports',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS citations_by_node ON citations (kind, node_id, id);

-- What somebody wants the apparatus to DO, from the project that uses it.
--
-- Kept apart from defects because nothing is broken and the guard has to be
-- different. A defect proves it happened by pasting what came back; a
-- request has no output to paste, so what stops it being a wish is `because`
-- -- what you were doing when you wanted it, and what not having it cost.
-- "Writing one at a time is tedious" is a preference. "Q1 through Q13 went
-- in as thirteen separate calls" is an observation, and it can be checked.
--
-- Naming the shape you want IS allowed here, unlike on a defect. You are the
-- one who knows your own need. What stays forbidden is telling the owner how
-- to fix something that broke: that is a claim about code you do not own,
-- and it has no field anywhere in this record.
--
-- `seq` is the label, and it is not unique: a request carried from another
-- machine's notebook keeps the number it was filed under there, and that
-- number can already be taken here. Renumbering it would change what every
-- sentence citing it means, and leaving it behind was going to drop 42 of
-- the 45 records two files carried. So a row is (seq, ident) -- its number
-- and what it was created with -- and `ident` is that content's hash, the
-- same on every machine.
-- It is NULL only on a row written by a server older than this column,
-- until the next open fills it in.
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY,
    seq         INTEGER NOT NULL,
    ident       TEXT,
    asked_by    INTEGER NOT NULL REFERENCES projects(id),
    owner_id    INTEGER NOT NULL REFERENCES projects(id),
    wanted      TEXT NOT NULL,
    because     TEXT NOT NULL,
    context     TEXT,
    decision    TEXT,
    why         TEXT,
    created_at  TEXT NOT NULL,
    closed_at   TEXT
);

CREATE INDEX IF NOT EXISTS requests_by_owner ON requests (owner_id, closed_at);

-- A defect is not a research question and not a backlog item. It is the
-- record of a measurement that could not be taken, routed to whoever owns
-- the apparatus that broke.
--
-- The two sides of it are separated on purpose, and the separation is the
-- whole design. The reporter is blocked: it saw a symptom and does not know
-- the cause, because if it knew, this would not be somebody else's bug. It
-- therefore writes OBSERVATION ONLY -- what was run and what came back, both
-- verbatim -- and there is no column here for a suggested fix. A proposed
-- cause from the reporter is an unverified claim about code it does not own,
-- with no falsifier and no measurement behind it, and acting on one is this
-- record's own failure mode crossing an agent boundary. `cause` exists only
-- on the closing side, where the apparatus is owned.
--
-- Labels are machine-wide (D1, D2 ...) unlike Q and A, which are per project.
-- A defect crosses projects by definition, so a per-project label would be
-- ambiguous the moment it was routed. Not unique, for the same reason as a
-- request's: see `ident` there.
CREATE TABLE IF NOT EXISTS defects (
    id          INTEGER PRIMARY KEY,
    seq         INTEGER NOT NULL,
    ident       TEXT,
    reported_by INTEGER NOT NULL REFERENCES projects(id),
    owner_id    INTEGER NOT NULL REFERENCES projects(id),
    -- NULL when the reporter had no measurement of its own to stop: a bug
    -- report about the apparatus itself, from somebody who was using it
    -- rather than measuring with it.
    attempt_id  INTEGER REFERENCES attempts(id),
    -- The attempt a false reading was taken in, when it was NOT stopped:
    -- the tool answered, one answer was untrue, and the rest of the
    -- measurement stands. Not attempt_id, which is the measurement this
    -- stopped. The two were one column, and filing a false seam reading
    -- closed an attempt whose seven predictions had all been measured.
    reading_in  INTEGER REFERENCES attempts(id),
    -- written by the reporter. observation only.
    invocation  TEXT NOT NULL,
    observed    TEXT NOT NULL,
    needed      TEXT NOT NULL,
    supersedes  INTEGER REFERENCES defects(id),
    -- written by the owner of the apparatus, once.
    resolution  TEXT,
    cause       TEXT,
    change      TEXT,
    verify      TEXT,
    invalidates TEXT,
    -- where the reporter was when it happened, when there is no attempt to
    -- read that from. Captured, not typed.
    context        TEXT,
    seen_commit    TEXT,
    seen_dirty     INTEGER,
    seen_untracked TEXT,
    fix_commit     TEXT,
    fix_dirty      INTEGER,
    fix_untracked  TEXT,
    -- one question back to the reporter, and one answer. Not a thread: a
    -- second exchange means the report was wrong, and re-filing exists.
    query          TEXT,
    asked_by       INTEGER REFERENCES projects(id),
    queried_at     TEXT,
    reply          TEXT,
    replied_at     TEXT,
    created_at  TEXT NOT NULL,
    closed_at   TEXT
);

-- What was learned about a DECIDED request, or a CLOSED defect, afterwards.
--
-- A decision's `why` and a fix's `cause` carry claims -- "16 of 89 near
-- constraints were affected", "the cause was the pad-edge fixture" -- and a
-- claim can turn out wrong the same afternoon. The decision stands, like a
-- verdict: it was made on what was known then. What had no home was the
-- correction, and it went into a commit message and a CLAUDE.md that nobody
-- arriving through the notebook reads. The next reader of the request got
-- the wrong figure as "decided".
--
-- Labels here are notebook-wide and the two sides are different projects,
-- so unlike a question's postscript the writer is recorded: a note from the
-- owner and a note from the asker are different claims. Only those two may
-- write one -- a third project leaving notes on somebody else's decision is
-- writing their record for them. `shown_by` is an attempt of the writer's
-- own project; without one the note renders as INTERPRETATION.
CREATE TABLE IF NOT EXISTS request_notes (
    id         INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES requests(id),
    written_by INTEGER NOT NULL REFERENCES projects(id),
    shown_by   INTEGER REFERENCES attempts(id),
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS defect_notes (
    id         INTEGER PRIMARY KEY,
    defect_id  INTEGER NOT NULL REFERENCES defects(id),
    written_by INTEGER NOT NULL REFERENCES projects(id),
    shown_by   INTEGER REFERENCES attempts(id),
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- What arrived from another machine's notebook, and when. Local to this
-- notebook: note_export never writes it, since it names files on this disk.
CREATE TABLE IF NOT EXISTS imports (
    id         INTEGER PRIMARY KEY,
    file       TEXT NOT NULL,
    project    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Which writing arrived by import: a row's making, or one of its one-time
-- transitions ('closed', 'queried', 'replied'). Anything with no row here
-- was written in this notebook.
--
-- It exists because a bare label in a text means the record the WRITER'S
-- notebook gave that number, and two notebooks number requests and defects
-- independently. Trace-from-photos wrote "R6 のカメラ読み返し" eleven times
-- about its own R6, and here R6 is a board request. The text is never
-- rewritten -- R6 is as often a resistor -- so what it names is worked out
-- where it is read, and that needs to know where each text was written.
-- Per writing, not per row: an attempt opened on one machine and closed on
-- the other is the ordinary handover.
CREATE TABLE IF NOT EXISTS carried (
    tbl       TEXT NOT NULL,
    row_id    INTEGER NOT NULL,
    event     TEXT NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    PRIMARY KEY (tbl, row_id, event)
);

-- A project another notebook knows by a different name. Recorded by the
-- import that was told so (rename=), and read by every import after it: the
-- other machine goes on writing its own name, and one import that forgot to
-- say so would file that machine's next requests under a blank card, for
-- good.
CREATE TABLE IF NOT EXISTS aliases (
    name       TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    import_id  INTEGER NOT NULL REFERENCES imports(id)
);

-- (seq, id) and not the UNIQUE (seq) this replaced: a server older than
-- `ident` asks for a label with "WHERE seq=?" and takes the first row back,
-- and through this index the first row is the one that held the number here
-- first -- the one a bare label names.
CREATE INDEX IF NOT EXISTS requests_by_seq ON requests (seq, id);
CREATE INDEX IF NOT EXISTS defects_by_seq ON defects (seq, id);
CREATE INDEX IF NOT EXISTS request_notes_by_request ON request_notes (request_id, id);
CREATE INDEX IF NOT EXISTS defect_notes_by_defect ON defect_notes (defect_id, id);
CREATE INDEX IF NOT EXISTS defects_by_owner ON defects (owner_id, closed_at);
CREATE INDEX IF NOT EXISTS defects_by_reporter ON defects (reported_by, closed_at);
CREATE INDEX IF NOT EXISTS attempts_by_question ON attempts (question_id, seq);
CREATE INDEX IF NOT EXISTS questions_by_project ON questions (project_id, seq);
"""


# --------------------------------------------------------------------------
# requests and defects: one number, possibly two records
# --------------------------------------------------------------------------

#: The table behind each notebook-wide label.
_RD = {"R": "requests", "D": "defects"}

#: What a request or defect was created with, and so what identifies it on
#: every machine. Never a project name: an import may read another
#: notebook's name as one of this notebook's (rename=), and the same row
#: must hash the same on both sides. A defect's context is left out too --
#: an import writes where the stopped attempt lives into it.
IDENT = {"R": ("wanted", "because", "context", "created_at"),
         "D": ("invocation", "observed", "needed", "seen_commit", "seen_dirty",
               "seen_untracked", "created_at"),
         # A question or attempt by what was written into it, and never by
         # what it points at: those are other rows, named by numbers that are
         # not unique any more, and the same row has to hash the same in a
         # notebook that numbers its neighbours differently.
         "Q": ("text", "created_at"),
         "A": ("hypothesis", "why_now", "measure", "falsifier", "apparatus",
               "created_at")}

#: The table behind each per-project label.
_QA = {"Q": "questions", "A": "attempts"}

#: How much of the hash a qualified label prints. Two records sharing a
#: number are told apart by it; six hex digits make a clash between them a
#: one-in-sixteen-million event, and a label that did clash is refused with
#: both candidates rather than guessed.
_SHORT = 6


#: Columns a notebook older than them is missing, in the order they came.
#: The ordinary open adds them; a read-only one can only say they are not
#: there yet.
ADDED_COLUMNS = (
    ("projects", "repo", "TEXT NOT NULL DEFAULT ''"),
    ("projects", "stub", "INTEGER NOT NULL DEFAULT 0"),
    ("attempts", "open_untracked", "TEXT"),
    ("attempts", "close_untracked", "TEXT"),
    ("defects", "seen_untracked", "TEXT"),
    ("defects", "fix_untracked", "TEXT"),
    ("defects", "query", "TEXT"),
    ("defects", "asked_by", "INTEGER"),
    ("defects", "queried_at", "TEXT"),
    ("defects", "reply", "TEXT"),
    ("defects", "replied_at", "TEXT"),
    ("attempts", "open_commit", "TEXT"),
    ("attempts", "open_dirty", "INTEGER"),
    ("attempts", "close_commit", "TEXT"),
    ("attempts", "close_dirty", "INTEGER"),
    ("defects", "seen_commit", "TEXT"),
    ("defects", "seen_dirty", "INTEGER"),
    ("defects", "fix_commit", "TEXT"),
    ("defects", "fix_dirty", "INTEGER"),
    ("defects", "reading_in", "INTEGER"),
    ("questions", "parent", "INTEGER REFERENCES questions(id)"),
    ("citations", "role", "TEXT NOT NULL DEFAULT 'supports'"),
    ("projects", "waiting_question", "INTEGER"),
    ("questions", "headline", "TEXT"),
    ("questions", "answer_headline", "TEXT"),
    ("attempts", "headline", "TEXT"),
    ("attempts", "result_headline", "TEXT"),
    ("postscripts", "headline", "TEXT"),
    ("attempt_notes", "headline", "TEXT"),
    ("projects", "merged_into", "INTEGER REFERENCES projects(id)"),
    ("projects", "merged_at", "TEXT"),
    ("questions", "answer_user_said", "TEXT"),
    ("postscripts", "answer_is", "TEXT"),
    ("postscripts", "user_said", "TEXT"),
)


#: What a notebook's name is made of. No 0/o, 1/l/i: it is read off a
#: screen and typed back.
_NAME_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"


def new_notebook_name() -> str:
    """Three characters: short enough to sit after every label that needs it.
    Two notebooks drawing the same one is about one in thirty thousand, and
    an import that meets it says so rather than mixing their rows."""
    import secrets
    return "".join(secrets.choice(_NAME_CHARS) for _ in range(3))


def _statements(script: str) -> list[str]:
    """The script's statements, cut where SQLite would cut them.

    Not on every ";" -- the comments in SCHEMA carry semicolons ("pasting
    what came back; a request has no output"), and a piece cut after one of
    those starts in the middle of a comment. The reshape built a table from
    such a piece and failed on the first real notebook it met, with "near
    'a': syntax error"."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return out


def ident(kind: str, row) -> str:
    """The hash of what a row was created with: a request ('R'), a defect
    ('D'), a question ('Q') or an attempt ('A')."""
    payload = json.dumps([kind] + [row[f] for f in IDENT[kind]],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


#: A request or defect label inside prose. Bare ("R6") or qualified
#: ("R6@3fa2c1"). A pad ("D4.1") is not one: no label is written that way.
_CITE = re.compile(r"(?<![A-Za-z0-9_])([RD])(\d+)(?:@([0-9a-f]{4,64}))?"
                   r"(?![0-9@]|\.[0-9])")

#: A question or attempt label inside prose. Not one after "project/": that
#: names another project's row, and says so.
_QA_CITE = re.compile(r"(?<![A-Za-z0-9_/])([QA])(\d+)(?:@([a-z0-9]+))?"
                      r"(?![0-9@]|\.[0-9])")

#: The text each kind of row carries, by the one-time writing that put it
#: there. A text is read in the numbering of the notebook that wrote it, and
#: one row can be written in two: opened on one machine, closed on the other.
_TEXTS = {
    "questions": {"made": ("text",), "closed": ("answer", "answer_user_said")},
    "postscripts": {"made": ("text", "user_said")},
    "attempts": {"made": ("hypothesis", "why_now", "measure", "falsifier",
                          "apparatus"),
                 "closed": ("result",)},
    "attempt_notes": {"made": ("text",)},
    "requests": {"made": ("wanted", "because", "context"), "closed": ("why",)},
    "request_notes": {"made": ("text",)},
    "defects": {"made": ("invocation", "observed", "needed", "context"),
                "queried": ("query",), "replied": ("reply",),
                "closed": ("cause", "change", "verify")},
    "defect_notes": {"made": ("text",)},
}


# --------------------------------------------------------------------------
# similarity -- deliberately not FTS
#
# FTS5's default tokenizer splits on non-alphanumerics, so an entire Japanese
# sentence arrives as ONE token and never matches anything. The trigram
# tokenizer handles that, but the ranking would still be opaque. This record
# is thousands of rows at the very most, so character bigrams scored in
# Python are instant, work the same for Japanese and English, and let the
# threshold be a number someone chose rather than bm25 internals.
# --------------------------------------------------------------------------

_STRIP = re.compile(r"[\s　。、,.:;・/()\[\]{}「」『』\"'`?!？！-]+")


def _bigrams(text: str) -> set[str]:
    t = _STRIP.sub("", text.lower())
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard over character bigrams, plus a bonus for outright containment.

    Returns 0.0 .. 1.0. Chosen over token overlap because the strings being
    compared are hypothesis sentences a person typed months apart, in two
    languages, about the same idea.
    """
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    j = len(ga & gb) / len(ga | gb)
    sa, sb = _STRIP.sub("", a.lower()), _STRIP.sub("", b.lower())
    if sa and sb and (sa in sb or sb in sa):
        j = max(j, 0.75)
    return j


class Store:
    """The record. Every write is an insert or a one-time close."""

    def __init__(self, path: Optional[Path | str] = None):
        self.path = Path(path) if path else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None moves transaction control into this file
        # rather than the driver's implicit BEGIN, which is the whole point:
        # every guard here is a read that authorises the write after it, and
        # the driver would open its transaction at the write -- after the
        # guard had already read. See _writing.
        self.db = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # Before anything that can block: two agents opening the notebook at
        # once both run the schema script, and setting WAL itself takes a lock.
        self.db.execute("PRAGMA busy_timeout = 30000")
        self._ensure_wal()
        self.db.execute("PRAGMA foreign_keys = ON")
        # Tables, then the columns an older notebook is missing, then indexes.
        # An index names columns, so building them before the migration made
        # opening an old notebook fail on the first index over a column that
        # had been added since -- the schema would refuse to open the very
        # database it was meant to grow.
        # partition() would cut at the FIRST index and leave every table
        # declared after it unbuilt, which is worse than the fault being
        # fixed. Split by statement.
        stmts = _statements(SCHEMA)
        # A comment above an index travels with it, and must not make it read
        # as a table -- then it is built before the reshape drops it, and
        # never again.
        is_index = lambda st: "\n".join(
            ln for ln in st.splitlines() if not ln.strip().startswith("--")
        ).lstrip().upper().startswith("CREATE INDEX")
        self.db.executescript("".join(st for st in stmts if not is_index(st)))
        self._migrate()
        self.db.executescript("".join(st for st in stmts if is_index(st)))

    @classmethod
    def read_only(cls, path: Optional[Path | str] = None) -> "Store":
        """The record opened for reading, and nothing else.

        For a reader that is not an agent -- a person looking at the tree.
        The ordinary open grows the schema and puts the file into WAL, which
        is right for a writer and wrong for something that only looks: a
        viewer left running beside two agents would be one more party taking
        write locks on a record it never writes. SQLite refuses every write
        on this connection, so no method reached through it can make one,
        and every read method here is the same code the tools run.

        A notebook no server has opened since the schema last grew is missing
        columns these reads name; open it once through the server first.
        """
        self = cls.__new__(cls)
        self.path = Path(path) if path else default_db_path()
        if not self.path.is_file():
            raise NoteError(f"no notebook at {self.path}. SAINPOST_DB moves it.")
        self.db = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True,
                                  timeout=30.0, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout = 30000")
        # Found out here rather than by the first read that names a missing
        # column: that surfaced as `IndexError: No item with that key` from
        # deep inside trail(), about a notebook that was only behind.
        tables = {r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA)
                   if t not in tables]
        missing += [f"{t}.{c}" for t, c, _ in ADDED_COLUMNS if t in tables
                    and c not in {r["name"] for r in
                                  self.db.execute(f"PRAGMA table_info({t})")}]
        missing += [f"{t} (its shape)" for t in self._needs_reshape()]
        if not missing and self.db.execute("SELECT 1 FROM notebook").fetchone() is None:
            missing.append("its name")
        if missing:
            self.db.close()
            raise NoteError(
                f"the notebook at {self.path} was last opened by an older server "
                f"and is missing {', '.join(missing)}. A reader cannot grow it -- "
                f"that is a write. Restart the sainpost MCP server (or run "
                f"`python -c \"from sainpost.store import Store; "
                f"Store().close()\"`) and read it again.")
        self.name = self.db.execute("SELECT name FROM notebook").fetchone()["name"]
        return self

    def _migrate(self) -> None:
        """Grow an older notebook to the current schema.

        Adding columns is almost the only migration this record needs --
        nothing is dropped or rewritten, because nothing here is edited. The
        exceptions are constraints SQLite cannot relax in place:
        `defects.attempt_id` was NOT NULL (a bug report from somebody USING
        the apparatus has no attempt of its own to stop), and `seq` was
        UNIQUE on requests and defects (a record carried from another
        notebook keeps its number, which can already be taken here). Those
        rebuild the table and copy every row across, verifying the count. No
        recorded fact changes; only what the schema will accept next."""
        for table, column, decl in ADDED_COLUMNS:
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                self._add_column(table, column, decl)
        self._reshape()
        self._fill_idents()
        self.name = self._named()
        self._fill_origins()

    def _named(self) -> str:
        """This notebook's name, made on its first open. INSERT OR IGNORE and
        then a read: every session opens a fresh notebook at once, and the
        name is whichever of them got there first."""
        self.db.execute("INSERT OR IGNORE INTO notebook (id, name, created_at)"
                        " VALUES (1, ?, ?)", (new_notebook_name(), _now()))
        return self.db.execute("SELECT name FROM notebook WHERE id=1").fetchone()["name"]

    def _fill_origins(self) -> None:
        """Say where every question and attempt was written: here, for each
        one no import brought. Those an import brought before files said so
        stay unknown until a file that does say arrives. NULL to value, once.
        Also catches rows a server older than the column wrote after this
        one opened: they were written here too."""
        for table in _QA.values():
            if self.db.execute(
                    f"SELECT 1 FROM {table} WHERE origin IS NULL AND id NOT IN"
                    f" (SELECT row_id FROM carried WHERE tbl=? AND event='made')"
                    f" LIMIT 1", (table,)).fetchone():
                with self._writing():
                    self.db.execute(
                        f"UPDATE {table} SET origin=? WHERE origin IS NULL AND id"
                        f" NOT IN (SELECT row_id FROM carried WHERE tbl=?"
                        f" AND event='made')", (self.name, table))

    def _add_column(self, table: str, column: str, decl: str) -> None:
        try:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        except sqlite3.OperationalError as e:
            # Every session on the machine opens the notebook at once after a
            # reload, and more than one can read "missing" before any of them
            # has added it. The goal is the column, not being the one who
            # added it.
            if "duplicate column" not in str(e):
                raise

    def _needs_reshape(self) -> list[str]:
        """Tables whose shape an ALTER cannot reach: a constraint to relax, or
        a reference to a table that no longer exists."""
        tables = {r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        out = []
        for t in ("requests", "defects"):
            cols = {r["name"]: r for r in self.db.execute(f"PRAGMA table_info({t})")}
            if "ident" not in cols or (t == "defects" and cols["attempt_id"]["notnull"]):
                out.append(t)
        # UNIQUE (project_id, seq) is the constraint that made two records
        # of one investigation impossible to join; it goes with `qual`.
        for t in _QA.values():
            if "qual" not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({t})")}:
                out.append(t)
        # The rebuild this replaced renamed the old table BEFORE building the
        # new one. SQLite then rewrites every REFERENCES to it -- defect_notes
        # came out pointing at "defects_was", dropped a moment later, and any
        # note on a defect after that fails with "no such table". A notebook
        # that went through it is repaired here.
        for t in sorted(tables - set(out)):
            if any(fk["table"] not in tables for fk in
                   self.db.execute(f"PRAGMA foreign_key_list({t})")):
                out.append(t)
        return out

    def _reshape(self) -> None:
        """Rebuild each table in `_needs_reshape` into its shape in SCHEMA.

        SQLite's own order, and not the obvious one: build the new table,
        copy, drop the old, rename the new into place. Renaming the OLD one
        out of the way first is what stranded defect_notes (see above). Ids
        are copied, so every reference into these rows still holds. One
        transaction, re-checked inside the lock: every session opens the
        notebook at once, and only the first may do this."""
        if not self._needs_reshape():
            return
        self.db.execute("PRAGMA foreign_keys = OFF")      # a no-op inside BEGIN
        try:
            with self._writing():
                # Only what the rebuild itself broke stops it. A row that
                # already pointed nowhere is the record as it stands, and
                # refusing the reshape over it would refuse every session
                # this notebook, for a fault this cannot repair.
                was = {(r[0], r[1]) for r in self.db.execute("PRAGMA foreign_key_check")}
                for table in self._needs_reshape():
                    self._rebuild(table)
                broken = [r for r in self.db.execute("PRAGMA foreign_key_check")
                          if (r[0], r[1]) not in was]
                if broken:
                    raise NoteError(f"reshaping the notebook would break "
                                    f"{len(broken)} reference(s); nothing was changed")
        finally:
            self.db.execute("PRAGMA foreign_keys = ON")

    def _rebuild(self, table: str) -> None:
        new = f"{table}_reshaped"
        create = next(st for st in _statements(SCHEMA)
                      if f"CREATE TABLE IF NOT EXISTS {table} (" in st)
        self.db.execute(create.replace(f"EXISTS {table} (", f"EXISTS {new} (", 1))
        keep = [r["name"] for r in self.db.execute(f"PRAGMA table_info({new})")]
        cols = [c for c in (r["name"] for r in
                            self.db.execute(f"PRAGMA table_info({table})")) if c in keep]
        before = self.db.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        self.db.execute(f"INSERT INTO {new} ({', '.join(cols)})"
                        f" SELECT {', '.join(cols)} FROM {table}")
        after = self.db.execute(f"SELECT COUNT(*) c FROM {new}").fetchone()["c"]
        if after != before:
            raise NoteError(f"reshaping {table} would have lost rows: "
                            f"{before} -> {after}; nothing was changed")
        self.db.execute(f"DROP TABLE {table}")
        self.db.execute(f"ALTER TABLE {new} RENAME TO {table}")

    def _fill_idents(self) -> None:
        """Hash every row that has no `ident` yet: all of them once, after
        the reshape, and afterwards only rows a server older than the column
        wrote. NULL to value, once, like every change here."""
        todo = [(k, t) for k, t in {**_RD, **_QA}.items() if self.db.execute(
            f"SELECT 1 FROM {t} WHERE ident IS NULL LIMIT 1").fetchone()]
        if not todo:
            return
        with self._writing():
            for kind, table in todo:
                for r in self.db.execute(
                        f"SELECT * FROM {table} WHERE ident IS NULL").fetchall():
                    self.db.execute(f"UPDATE {table} SET ident=? WHERE id=?",
                                    (ident(kind, r), r["id"]))

    #: The busy timeout above does not cover the next PRAGMA, and that is
    #: not an oversight in SQLite: changing the journal mode wants the
    #: exclusive lock, and running a busy handler while holding what other
    #: writers are waiting for is how you build a deadlock. It returns
    #: SQLITE_BUSY at once instead. So the wait has to be out here.
    #:
    #: Measured before this existed: three sessions calling note_start on a
    #: notebook that did not exist yet -- two of them came back in ONE
    #: MILLISECOND with "database is locked", to an agent that had done
    #: nothing wrong and had no way to read that as "try again". The first
    #: use of a shared notebook is exactly when every session reaches it at
    #: once, so this is the common case wearing the mask of a rare one.
    #:
    #: Seconds to keep asking. A count of attempts would not have bounded
    #: anything: every statement in the negotiation can block for the
    #: busy_timeout above, so forty tries of a thirty-second wait is a
    #: twenty-minute hang wearing a fix's clothing. The wait is lowered while
    #: negotiating and put back afterwards, so this loop -- and not the
    #: driver -- decides how long the caller stands there.
    _WAL_SECONDS = 20.0
    _WAL_PAUSE = 0.05
    _WAL_NEGOTIATING_MS = 250

    def _journal_mode(self) -> str:
        return str(self.db.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def _ensure_wal(self) -> None:
        """WAL, without the race that asking for it unconditionally creates.

        Asked before it is set, because from the notebook's second open
        onwards the answer is already "wal" and no lock is taken at all.
        That alone removes every session from this contention except the
        ones present at creation, and those retry.

        Somebody else winning is not a failure -- the goal is the notebook
        being in WAL, not this connection being the one that said so -- so
        the mode is re-read after each refusal.
        """
        if self._journal_mode() == "wal":
            return
        self.db.execute(f"PRAGMA busy_timeout = {self._WAL_NEGOTIATING_MS}")
        try:
            deadline = time.monotonic() + self._WAL_SECONDS
            while True:
                try:
                    self.db.execute("PRAGMA journal_mode = WAL")
                    return
                except sqlite3.OperationalError as e:
                    if "locked" not in str(e) and "busy" not in str(e):
                        raise
                if time.monotonic() >= deadline:
                    break
                time.sleep(self._WAL_PAUSE * (1.0 + random.random()))
                try:
                    if self._journal_mode() == "wal":
                        return
                except sqlite3.OperationalError:
                    pass                    # still locked; the loop decides
            raise NoteError(
                f"the notebook at {self.path} could not be put into WAL mode: "
                f"something has held it locked for {self._WAL_SECONDS:.0f}s. "
                f"WAL is what lets two agents share one record, so this is not "
                f"a thing to work around -- find the process still holding it.")
        finally:
            self.db.execute("PRAGMA busy_timeout = 30000")

    def close(self) -> None:
        """Fold the write-ahead log back in before letting go.

        WAL is what lets two agents share the notebook, and it has a trap:
        the recent writes live in research.db-wal, so `cp research.db
        somewhere` produces a file that opens cleanly and contains nothing.
        Three sessions of trial records were lost to exactly that. Checkpoint
        on close means a notebook nobody is attached to is complete in the
        one file, which is what "plain SQLite, anyone can read it" has to
        mean. (backup.py never had the bug -- it uses sqlite's own backup
        API -- but nothing makes a person or an agent reach for it.)
        """
        try:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass                       # closing matters more than tidiness
        self.db.close()

    # -- fixing the state of the code -------------------------------------

    def _code_state(self, project: sqlite3.Row) -> dict:
        """Which commit this node is being created against. Reads only.

        Never raises. A node whose code state could not be read is worth less
        than one whose could, and far more than no node at all, so the failure
        is recorded in words and the write goes ahead.
        """
        repo = rig.is_repo(project["repo"])
        if repo is None:
            return {"commit": None, "modified": None, "untracked": [],
                    "note": None if not project["repo"] else
                    f"no git repository at {project['repo']!r}; no commit recorded"}
        try:
            return {**rig.observe(repo), "note": None}
        except rig.RigError as e:
            return {"commit": None, "modified": None, "untracked": [],
                    "note": f"could not read the code state: {e}"}

    @staticmethod
    def _untracked_text(names: list) -> Optional[str]:
        if not names:
            return None
        head = ", ".join(names[:8])
        return head + (f", and {len(names) - 8} more" if len(names) > 8 else "")

    @classmethod
    def _state_out(cls, st: dict) -> Optional[dict]:
        if st.get("note"):
            return {"code_state": st["note"]}
        if not st.get("commit"):
            return None
        out = {"commit": st["commit"][:12]}
        if st.get("modified"):
            # The real one, and still not a thing to repair by committing on
            # somebody's behalf: that would make the sentence false without
            # making the number reproducible by anyone else.
            out["TRACKED FILES DIFFER FROM THIS COMMIT"] = (
                "this number came out of code that is in no commit and cannot "
                "be returned to. Recorded, not a task -- the notebook does not "
                "commit and does not expect you to")
        if st.get("untracked"):
            # Stated, not alarmed about. Running a Python program creates
            # __pycache__/, and an alarm that fires on that is an alarm that
            # gets ignored -- while an untracked file can equally BE the
            # experiment. Only a reader can tell which, so name them.
            out["untracked files, in no commit"] = cls._untracked_text(
                st["untracked"])
        return out

    @contextmanager
    def _writing(self):
        """One write lock over a guard AND the write that guard authorises.

        Every refusal in this file is a read: is an attempt already open,
        does this question exist, what is the next seq. Under a deferred
        transaction those reads run before any lock is taken, so two agents
        sharing one notebook can both read "nothing is open", both pass, and
        both insert. The one-open-front rule then fails silently -- which is
        the exact shape of failure this server exists to prevent, arriving
        through the server itself. BEGIN IMMEDIATE takes the write lock
        first, so the second agent waits and then reads what the first one
        actually wrote.
        """
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()

    # -- projects ---------------------------------------------------------

    def start_project(self, name: str, description: str = "",
                      repo: str = "") -> dict:
        name = name.strip()
        if not name:
            raise NoteError("a project needs a name")
        with self._writing():
            existing = self._project_row(name, required=False)
            # A repo path is not a claim about the world at a moment, which is
            # what everything else here is and why none of it can be edited.
            # It is a pointer, and pointers go stale: the trial records that
            # found half the faults in this server name commits that live in a
            # directory which will be cleaned up. Re-pointing is allowed for
            # exactly that case -- the recorded path no longer resolves -- so
            # it cannot quietly become a general edit path.
            repointing = bool(
                existing and not existing["stub"] and repo.strip()
                and existing["repo"] and not Path(existing["repo"]).exists()
                and Path(repo.strip()).exists())
            if existing and not existing["stub"] and not repointing:
                raise NoteError(
                    f"project {name!r} already exists. Projects are never "
                    f"re-created, only added to -- note_trunk({name!r}) shows "
                    f"where it stands, which is where you start."
                    + (f"\nIts repo is recorded as {existing['repo']!r}, which "
                       f"still exists. A path that resolves is not stale, and "
                       f"there is no other way to change one."
                       if existing["repo"] and repo.strip() else "")
                )
            was = existing["repo"] if repointing else None
            if repointing:
                # The pointer, and nothing else. Falling through to the stub
                # branch below would let a re-point rewrite the description,
                # which is a claim and is not correctable.
                self.db.execute("UPDATE projects SET repo=? WHERE id=?",
                                (repo.strip(), existing["id"]))
            elif existing:
                # It exists only because somebody had to file a defect against
                # it, and they left the card blank on purpose: an account of
                # your investigation written by another team is exactly the
                # unverified intermediate this record refuses everywhere else.
                # This is the first time its own team has spoken, so it is not
                # an edit, and it happens once.
                self.db.execute(
                    "UPDATE projects SET description=?, repo=?, stub=0 WHERE id=?",
                    (description.strip(), repo.strip(), existing["id"]),
                )
                cur = None
            else:
                cur = self.db.execute(
                    "INSERT INTO projects (name, description, repo, created_at)"
                    " VALUES (?,?,?,?)",
                    (name, description.strip(), repo.strip(), _now()),
                )
        out = {"project": name,
               "description": description.strip()}
        if repointing:
            return {"project": name, "repo": repo.strip(),
                    "repointed": f"the recorded path {was!r} no longer exists. "
                                 f"The commits this project's nodes name are "
                                 f"expected to be reachable from the new one; "
                                 f"nothing else about the record changed."}
        if cur is None:
            out["adopted"] = ("this project already existed as a referral stub -- "
                              "another project filed a defect against it before "
                              "you arrived. It is yours now, and this description "
                              "and repo are the first its own team has written.")
        # Said now, not on the first attempt that silently records nothing.
        found = rig.is_repo(repo)
        if repo and found is None:
            out["repo"] = f"NOT A GIT REPOSITORY: {repo!r}. Nodes in this project "\
                          f"will record no code state."
        elif found is not None:
            out["repo"] = str(found)
            out["code state"] = ("every node here records the commit it was "
                                 "created against, and whether the working tree "
                                 "differed from it. Read only -- nothing is "
                                 "committed, no ref is moved, nothing is pushed.")
        else:
            out["repo"] = ("none given -- nodes will record no code state. Pass repo= "
                           "if this investigation is about code.")
        return out

    def projects(self) -> list[dict]:
        out = []
        for p in self.db.execute(
                "SELECT * FROM projects WHERE merged_into IS NULL ORDER BY name"):
            q = self._current_question(p["id"])
            opens = self._open_attempts(p["id"])
            blocked_on, waiting = self._defect_lines(p["id"])
            aw, ow = self._request_lines(p["id"])
            blocked_on, waiting = blocked_on + aw, waiting + ow
            out.append({
                "project": p["name"],
                "description": p["description"],
                "questions": self._count("questions", p["id"]),
                "attempts": self._count("attempts", p["id"]),
                "repo": p["repo"] or None,
                "current_question": (f"{_lab('Q', q)}  {q['text']}" if q else None),
                "open_attempts": [f"{_lab('A', a)}  {a['hypothesis']}" for a in opens],
                **({"merged_from": gone} if (gone := [r["name"] for r in self.db.execute(
                    "SELECT name FROM projects WHERE merged_into=? ORDER BY name",
                    (p["id"],))]) else {}),
                **({"open_on_other_notebooks": away}
                   if (away := self._open_away(p["id"])) else {}),
                "blocked_on": blocked_on,
                "waiting_on_you": waiting,
            })
        return out

    def _count(self, table: str, project_id: int) -> int:
        return self.db.execute(
            f"SELECT COUNT(*) c FROM {table} WHERE project_id=?", (project_id,)
        ).fetchone()["c"]

    def _project_row(self, name: str, required: bool = True,
                     follow: bool = True) -> Optional[sqlite3.Row]:
        """The project by name -- and a name that was merged into another is
        that other one. Every agent, file and machine that learned the old
        name goes on using it, and what it writes belongs where the record
        went. `follow=False` is the row itself, for the merge."""
        row = self.db.execute(
            "SELECT * FROM projects WHERE name=?", (name.strip(),)
        ).fetchone()
        seen = set()
        while follow and row is not None and row["merged_into"] is not None \
                and row["id"] not in seen:
            seen.add(row["id"])
            row = self.db.execute("SELECT * FROM projects WHERE id=?",
                                  (row["merged_into"],)).fetchone()
        if row is None and required:
            known = [r["name"] for r in self.db.execute(
                "SELECT name FROM projects WHERE merged_into IS NULL ORDER BY name")]
            raise NoteError(
                f"no project named {name!r}. Known: {known or '(none yet)'}. "
                f"note_start creates one."
            )
        return row

    # -- two records of one investigation ---------------------------------

    def merge(self, into: str, absorbed: str) -> dict:
        """Move every question and attempt of `absorbed` into `into`, and
        keep every number.

        Two machines working one investigation without importing each other
        left two projects: PcbRouter written on one, pcbrouter on the other,
        both numbered from Q1. The text of each cites its own numbers, so
        neither can be renumbered -- and since a number now names a row only
        together with the notebook that wrote it, neither has to be. A
        number both hold prints bare for the row written HERE (or, failing
        that, the one `into` held) and after its notebook's name for the
        other. What was written as a bare label inside the moved text still
        means the row its writer meant, and note_open says which.

        Refused where that cannot be true: a row whose notebook is unknown
        (carried before files said), a number the SAME notebook used in
        both, or a notebook with open work under a question in each.
        """
        with self._writing():
            return self._merge(into, absorbed)

    def _merge(self, into: str, absorbed: str) -> dict:
        """The merge, inside a transaction the caller holds -- an import
        applies one it was told about as part of its own."""
        a = self._project_row(absorbed, follow=False)
        b = self._project_row(into, follow=False)
        if a["id"] == b["id"]:
            raise NoteError(f"{into!r} and {absorbed!r} are one project already")
        for r in (a, b):
            if r["merged_into"] is not None:
                raise NoteError(
                    f"{r['name']!r} was already merged into "
                    f"{self._project_name(r['merged_into'])!r} on {r['merged_at']}.")
        both = (a["id"], b["id"])
        unknown = sum(self.db.execute(
            f"SELECT COUNT(*) c FROM {t} WHERE project_id IN (?,?) AND origin IS NULL",
            both).fetchone()["c"] for t in _QA.values())
        if unknown:
            raise NoteError(
                f"{unknown} question(s) and attempt(s) in these two projects were "
                f"carried in before files said which notebook wrote them, and a "
                f"number both projects hold is told apart by exactly that. Import "
                f"a file of each exported by this version on the machine that "
                f"wrote it -- the rows are matched by what they are and their "
                f"notebook is recorded -- then merge.")
        for kind, table in _QA.items():
            twice = self.db.execute(
                f"SELECT x.seq, x.origin FROM {table} x JOIN {table} y"
                f" ON x.seq=y.seq AND x.origin=y.origin"
                f" WHERE x.project_id=? AND y.project_id=? ORDER BY x.seq",
                (a["id"], b["id"])).fetchall()
            if twice:
                raise NoteError(
                    f"{', '.join(f'{kind}{r[0]}' for r in twice[:8])} "
                    f"{'is' if len(twice) == 1 else 'are'} numbered in both "
                    f"projects by the same notebook ({twice[0]['origin']}), so the "
                    f"notebook's name cannot tell them apart. These are two "
                    f"investigations numbered in one place, not one written in two.")
        fronts: dict = {}
        for r in self.db.execute(
                "SELECT origin, question_id FROM attempts WHERE project_id IN (?,?)"
                " AND closed_at IS NULL", both):
            fronts.setdefault(r["origin"], set()).add(r["question_id"])
        split = [o for o, qs in fronts.items() if len(qs) > 1]
        if split:
            raise NoteError(
                f"{', '.join(split)} has attempts open under a question in each "
                f"project; merged, that is one notebook with two fronts. Close "
                f"one side's first (ABANDONED counts).")

        mine_there = self.db.execute(
            "SELECT 1 FROM attempts WHERE project_id=? AND closed_at IS NULL"
            " AND origin IS ?", (a["id"], self.name)).fetchone()
        before = {(k, r["id"]): _lab(k, r) for k, t in _QA.items()
                  for r in self.db.execute(
                      f"SELECT id, seq, qual FROM {t} WHERE project_id IN (?,?)", both)}
        held_by_into = {(k, r["id"]) for k, t in _QA.items()
                        for r in self.db.execute(
                            f"SELECT id FROM {t} WHERE project_id=?", (b["id"],))}
        for kind, table in _QA.items():
            # Every row after its notebook first -- (seq, origin) is unique
            # across the two, checked above -- then the move, then the one
            # bare holder of each number.
            self.db.execute(f"UPDATE {table} SET qual=origin WHERE project_id IN (?,?)",
                            both)
            self.db.execute(f"UPDATE {table} SET project_id=? WHERE project_id=?",
                            (b["id"], a["id"]))
            holders: dict = {}
            for r in self.db.execute(f"SELECT id, seq, origin FROM {table}"
                                     f" WHERE project_id=? ORDER BY id", (b["id"],)):
                holders.setdefault(r["seq"], []).append(r)
            for rows in holders.values():
                bare = (next((r for r in rows if r["origin"] == self.name), None)
                        or next((r for r in rows if (kind, r["id"]) in held_by_into),
                                None) or rows[0])
                self.db.execute(f"UPDATE {table} SET qual='' WHERE id=?", (bare["id"],))
        for table, cols in (("requests", ("asked_by", "owner_id")),
                            ("defects", ("reported_by", "owner_id", "asked_by")),
                            ("request_notes", ("written_by",)),
                            ("defect_notes", ("written_by",))):
            for col in cols:
                self.db.execute(f"UPDATE {table} SET {col}=? WHERE {col}=?",
                                (b["id"], a["id"]))
        self.db.execute("UPDATE aliases SET project_id=? WHERE project_id=?",
                        (b["id"], a["id"]))
        # This notebook's position goes with this notebook's open work.
        if mine_there or b["current_question"] is None:
            self.db.execute("UPDATE projects SET current_question=? WHERE id=?",
                            (a["current_question"], b["id"]))
        if b["waiting_question"] is None:
            self.db.execute("UPDATE projects SET waiting_question=? WHERE id=?",
                            (a["waiting_question"], b["id"]))
        if not b["repo"] and a["repo"]:
            self.db.execute("UPDATE projects SET repo=? WHERE id=?", (a["repo"], b["id"]))
        self.db.execute(
            "UPDATE projects SET merged_into=?, merged_at=?, current_question=NULL,"
            " waiting_question=NULL WHERE id=?", (b["id"], _now(), a["id"]))

        moved = relabelled = 0
        changed = []
        for k, t in _QA.items():
            for r in self.db.execute(f"SELECT id, seq, qual FROM {t} WHERE project_id=?",
                                     (b["id"],)):
                if (k, r["id"]) not in held_by_into:
                    moved += 1
                if before[(k, r["id"])] != _lab(k, r):
                    relabelled += 1
                    if len(changed) < 12:
                        changed.append(f"{before[(k, r['id'])]} -> {_lab(k, r)}")
        return {
            "merged": f"{a['name']} into {b['name']}",
            "moved": f"{moved} question(s) and attempt(s); every number kept",
            "printed differently now": (
                {"count": relabelled, "for example": changed,
                 "read this": f"a number both held prints bare for the row "
                              f"written in this notebook ({self.name}) and after "
                              f"its notebook's name for the other. Text written "
                              f"with a bare label still means the row its writer "
                              f"meant; note_open on it says which"}
                if relabelled else "nothing"),
            "the old name": (f"{a['name']!r} is read as {b['name']!r} from now on -- "
                             f"by every tool here, and by imports of the other "
                             f"machine's files. note_export({b['name']!r}) carries "
                             f"this merge to the other notebook, which makes it "
                             f"there on import."),
        }

    # -- questions --------------------------------------------------------

    def ask(self, project: str, text: str, supersedes: Optional[str] = None,
            parent: Optional[str] = None, headline: Optional[str] = None) -> dict:
        """Open a question and make it the project's current position.

        `supersedes` takes a Q-label. The old question is closed as
        superseded and the two are linked in both directions, so the chain
        of reformulations stays readable -- that chain is usually the finding.

        `parent` takes a Q-label too, and says the opposite thing: the
        earlier question is not wrong, it is what this one serves. The parent
        cannot be answered while anything under it is open, so an answer
        cannot skip a requirement it rests on. A replacement inherits the
        parent of what it replaces, which is why the two cannot be passed
        together.
        """
        p = self._project_row(project)
        text = text.strip()
        if not text:
            raise NoteError("a question needs text")
        head = headline_for(headline, text, "question", first_line_only=True)
        if supersedes and parent:
            raise NoteError(
                "supersedes and parent say different things, and a replacement "
                "already keeps the parent of what it replaces. Pass supersedes "
                "alone to replace a question, parent alone to open one under it.")

        with self._writing():
            over = None
            if parent:
                over = self._question_by_label(p["id"], parent)
                if over["status"] != "open":
                    raise NoteError(
                        f"{_lab('Q', over)} is {over['status']}, so nothing can be "
                        f"opened under it: what it rests on was settled when it "
                        f"was. Open this one under a question that is still open, "
                        f"or supersede {_lab('Q', over)} and put it under the "
                        f"replacement.")
            old = None
            if supersedes:
                old = self._question_by_label(p["id"], supersedes)
                # Answered is not the same state as superseded, and the two
                # were refused by one message that named the wrong one. A
                # question that was settled is exactly the kind whose frame
                # later turns out to have been wrong: the measurements under
                # it stay valid and stop meaning what they were taken to
                # mean. Replacing it is how that gets recorded, and blocking
                # it left the case with nowhere to go at all -- the answer
                # could be annotated but never re-opened for measurement.
                if old["superseded_by"] is not None:
                    raise NoteError(
                        f"{_lab('Q', old)} was already replaced by "
                        f"{self._q_label(old['superseded_by'])}. Supersede that "
                        f"one instead; the chain is what makes it readable."
                    )

            seq = self._next_seq("questions", p["id"])
            # A replacement stands where the replaced one stood: the tree is
            # about what an answer rests on, and reformulating a requirement
            # does not move it out from under what required it.
            under = over["id"] if over is not None else (old["parent"] if old else None)
            made = {"text": text, "created_at": _now()}
            cur = self.db.execute(
                "INSERT INTO questions (project_id, seq, text, headline, supersedes,"
                " parent, created_at, ident, origin) VALUES (?,?,?,?,?,?,?,?,?)",
                (p["id"], seq, text, head, old["id"] if old else None, under,
                 made["created_at"], ident("Q", made), self.name),
            )
            new_id = cur.lastrowid
            if old is not None:
                if old["status"] == "answered":
                    # It really was answered, and that answer really was
                    # reached. Only the link is added; the status, the answer
                    # and the date it closed stay as they were.
                    self.db.execute(
                        "UPDATE questions SET superseded_by=? WHERE id=?",
                        (new_id, old["id"]))
                else:
                    self.db.execute(
                        "UPDATE questions SET status='superseded', superseded_by=?,"
                        " closed_at=? WHERE id=?", (new_id, _now(), old["id"]))
                    self._fall_back(p["id"], old["id"])
            # The position does not move while a measurement is open here.
            # Open attempts ARE the position, and the trunk lists only the
            # current question's attempts, so moving it made the falsifier
            # somebody had committed to vanish from the view they re-read at
            # every checkpoint. It fired when another project filed a
            # question here, and equally when you superseded your own
            # question mid-measurement. _after_close moves it once the last
            # of them closes.
            opens = self._open_attempts(p["id"])
            self.db.execute(
                "UPDATE projects SET current_question=?, waiting_question=? WHERE id=?",
                (new_id, None, p["id"]) if not opens
                else (p["current_question"], new_id, p["id"]))
        return {
            "project": project,
            "question": f"Q{seq}",
            "text": text,
            "position": (f"unchanged -- {_labels(opens)} "
                         f"{'is' if len(opens) == 1 else 'are'} open here, and open "
                         f"work is the position. Q{seq} is recorded and waiting; it "
                         f"becomes current when the last of them closes."
                         if opens else f"now Q{seq}"),
            "supersedes": f"{_lab('Q', old)}" if old else None,
            "under": (f"{self._q_label(under)}  {_one_line(self._q_text(under), 96)}"
                      if under else None),
            "note": (f"{_lab('Q', old)} was answered and stays answered -- its answer "
                     f"and its attempts are untouched. This one replaces it as the "
                     f"live question, so new measurement goes here."
                     if old is not None and old["status"] == "answered" else None),
        }

    def answer(self, project: str, answer: str, question: Optional[str] = None,
               cites: Optional[str | list] = None,
               headline: Optional[str] = None,
               user_said: Optional[str] = None) -> dict:
        """Close a question with its answer. Answered questions are final.

        `user_said` is the user's own words accepting it as theirs. Without
        them the answer is an agent's, and every view says so: the answer
        an agent writes is read back by the next one as settled, and when
        the question was the user's to settle -- what a paper claims -- that
        reading put the agent's words in the author's mouth.
        """
        p = self._project_row(project)
        head = headline_for(headline, answer, "answer")
        said = (user_said or "").strip() or None
        with self._writing():
            q = (self._question_by_label(p["id"], question) if question
                 else self._current_question(p["id"]))
            if q is None:
                raise NoteError(f"{project} has no current question. note_ask opens one.")
            if q["status"] != "open":
                # Where an agent lands that comes back to record the user
                # accepting an answer: it reaches for the call that wrote it.
                # One line of the answer, not the whole of it -- the caller
                # can open it, and a refusal is not the place for a body.
                raise NoteError(
                    f"{_lab('Q', q)} is already {q['status']}"
                    + (f": {q['answer_headline'] or _one_line(q['answer'], LINE)}"
                       if q["answer"] else "")
                    + ". The record is append-only, so it is not answered again. "
                      f"If the user has accepted or rejected that answer, "
                      f"note_postscript('{_lab('Q', q)}', text, answer_is='ENDORSED' "
                      f"or 'REJECTED', user_said=<their words>) puts it beside the "
                      f"answer. If the question itself was the wrong one, "
                      f"note_ask(..., supersedes='{_lab('Q', q)}') replaces it."
                )
            under = [a for a in self._open_attempts(p["id"], everywhere=True)
                     if a["question_id"] == q["id"]]
            if under:
                raise NoteError(
                    f"{_labels(under)} {'is' if len(under) == 1 else 'are'} still "
                    f"open under this question ({under[0]['hypothesis']}). Close "
                    f"{'it' if len(under) == 1 else 'each'} with note_result first "
                    f"-- ABANDONED is a legitimate verdict."
                )
            # The same rule one level up: an answer written over work that is
            # still open is a summary, not a conclusion. A question opened
            # under this one is a requirement this answer rests on.
            below = self._open_below(q["id"])
            if below:
                raise NoteError(
                    f"{len(below)} question(s) under {_lab('Q', q)} are still open, "
                    f"and this answer would rest on them:\n"
                    + "\n".join(f"  {self._q_line(b)}" for b in below)
                    + f"\nAnswer them first, or supersede the ones that turned "
                      f"out to be the wrong question."
                )
            self.db.execute(
                "UPDATE questions SET status='answered', answer=?, answer_headline=?,"
                " answer_user_said=?, closed_at=? WHERE id=?",
                (answer.strip(), head, said, _now(), q["id"]),
            )
            cited = self._cite("Q", q["id"], project, cites)
            self._fall_back(p["id"], q["id"])
        # Not the answer back. note_result echoes its falsifier for a stated
        # reason -- the call gets checked against the prediction rather than
        # against memory of it -- and there is no equivalent here: nothing
        # was committed to in advance for this to be checked against. What it
        # cost was measured by the agent that hit it: writing up one history
        # sent roughly four thousand characters of its own text back into a
        # context that already held it, on a single call.
        out = {"project": project, "question": f"{_lab('Q', q)}",
               "recorded": f"{len(answer.strip())} characters",
               # Their words are not echoed: the caller just wrote them.
               "whose": ("endorsed by the user, in the words given as user_said"
                         if said else
                         f"not endorsed by the user -- every view shows it so. "
                         f"If they accept it as theirs, or reject it, "
                         f"note_postscript('{_lab('Q', q)}', answer_is=..., "
                         f"user_said=<their words>) records that."),
               "position": (f"now {_lab('Q', self._current_question(p['id']))}"
                            if self._current_question(p["id"]) else
                            "no open question left in this project")}
        if cited:
            out["rests on"] = self._citations_of("Q", q["id"], brief=True)
        return out

    def postscript(self, project: str, label: str, text: str,
                   shown_by: Optional[str] = None,
                   headline: Optional[str] = None,
                   answer_is: Optional[str] = None,
                   user_said: Optional[str] = None) -> dict:
        """Add what was learned later. The label decides what it attaches to.

        A Q-label annotates an answered question; an A-label annotates a
        closed attempt; an R- or D-label annotates a decided request or a
        closed defect. None of them touches what is already written.

        `answer_is` and `user_said` are for a question's answer only: where
        it stands now, and the user's words when that is their call.
        """
        kind = label.strip()[:1].upper()
        if kind in ("A", "R", "D") and ((answer_is or "").strip()
                                        or (user_said or "").strip()):
            what = {"A": "an attempt", "R": "a request", "D": "a defect"}[kind]
            raise NoteError(
                f"answer_is and user_said say where a question's ANSWER stands, "
                f"and {label.strip()!r} is {what}. Leave them out here; on "
                f"{what} the note's text says what was learned.")
        if kind == "A":
            return self._attempt_note(project, label, text, shown_by, headline)
        if kind in ("R", "D"):
            return self._crossing_note(project, label, text, shown_by)
        if shown_by:
            raise NoteError(
                "shown_by names the attempt that demonstrated something about "
                "another attempt. A question's postscript does not take one."
            )
        return self._question_postscript(project, label, text, headline,
                                         answer_is, user_said)

    def _attempt_note(self, project: str, label: str, text: str,
                      shown_by: Optional[str],
                      headline: Optional[str] = None) -> dict:
        """Say something about a closed attempt without touching its verdict.

        For the measurement that was INVALID and that nobody noticed -- a
        sweep against a broken rig gives a plausible number, and written down
        it is indistinguishable from a sound one. An outdated finding is a
        different thing and already has a path: a new attempt with
        prompted_by pointing here.

        The verdict stands because it is bound to a falsifier written before
        the data: "the count did not move" either happened or it did not.
        What this adds is that the number should not be believed, and why.
        """
        p = self._project_row(project)
        if not text.strip():
            raise NoteError("a note on an attempt says what was learned about it "
                            "later, in words")
        head = headline_for(headline, text, "note")
        with self._writing():
            a = self._attempt_by_label(p["id"], label)
            if a["closed_at"] is None:
                raise NoteError(
                    f"{_lab('A', a)} is still open -- there is no result to say "
                    f"anything about yet. Close it with note_result, or "
                    f"note_blocked if the apparatus broke before it measured."
                )
            by = self._attempt_by_label(p["id"], shown_by) if shown_by else None
            if by is not None and by["id"] == a["id"]:
                raise NoteError(f"{_lab('A', a)} cannot be its own evidence")
            self.db.execute(
                "INSERT INTO attempt_notes (attempt_id, shown_by, text, headline,"
                " created_at) VALUES (?,?,?,?,?)",
                (a["id"], by["id"] if by else None, text.strip(), head, _now()))
        return {"project": project, "attempt": f"{_lab('A', a)}",
                "verdict": a["verdict"],
                "added": f"{len(text.strip())} characters",
                "shown_by": f"{_lab('A', by)}" if by else
                            "nothing -- this is INTERPRETATION and renders as such",
                "note": "the verdict and the result are unchanged"}

    def _attempt_notes(self, attempt_id: int) -> list[dict]:
        out = []
        for r in self.db.execute(
                "SELECT text, headline, shown_by, created_at FROM attempt_notes"
                " WHERE attempt_id=? ORDER BY id", (attempt_id,)):
            out.append({"when": r["created_at"], "text": r["text"],
                        "headline": r["headline"],
                        "shown_by": self._label_of(r["shown_by"])})
        return out

    def _crossing_note(self, project: str, label: str, text: str,
                       shown_by: Optional[str]) -> dict:
        """Say what a decision or a fix turned out to be worth, afterwards.

        The first case was a decision whose `why` quoted "16 of 89 affected"
        from a check that, fixed the same afternoon, found 5 -- and two of the
        eleven that vanished were refuted outright by copper the router had
        already laid on that board. The correction existed, in a commit
        message. The request still said 16, as decided.

        Only on something closed: an undecided request or an open defect has
        no decision to add to, and its sides already have note_query.
        """
        p = self._project_row(project)
        if not text.strip():
            raise NoteError("a note on a decision says what was learned about "
                            "it later, in words")
        request = label.strip()[:1].upper() == "R"
        with self._writing():
            if request:
                row = self._request_by_label(label)
                sides = (row["asked_by"], row["owner_id"])
                name = self._rd_label("R", row)
                if row["closed_at"] is None:
                    raise NoteError(
                        f"{name} has not been decided -- there is no decision "
                        f"to add to. The owner closes it with note_decide.")
            else:
                row = self._defect_by_label(label)
                sides = (row["reported_by"], row["owner_id"])
                name = self._rd_label("D", row)
                if row["closed_at"] is None:
                    raise NoteError(
                        f"{name} is still open -- there is no resolution to add "
                        f"to. note_query asks the other side something without "
                        f"closing it.")
            if p["id"] not in sides:
                # A project can ask itself: PcbRouter's R3 was its own.
                who = (f"{name} belongs to {self._project_name(sides[0])}"
                       if sides[0] == sides[1] else
                       f"{name} is between {self._project_name(sides[0])} and "
                       f"{self._project_name(sides[1])}")
                raise NoteError(
                    f"{who}. {project!r} is neither side, and a note here would "
                    f"be written in their record for them. Tell them; they can "
                    f"add it.")
            by = self._attempt_by_label(p["id"], shown_by) if shown_by else None
            table, key = (("request_notes", "request_id") if request
                          else ("defect_notes", "defect_id"))
            self.db.execute(
                f"INSERT INTO {table} ({key}, written_by, shown_by, text, created_at)"
                " VALUES (?,?,?,?,?)",
                (row["id"], p["id"], by["id"] if by else None, text.strip(), _now()))
        return {"project": project, "on": name,
                "added": f"{len(text.strip())} characters",
                "shown_by": f"{project} {_lab('A', by)}" if by else
                            "nothing -- this is INTERPRETATION and renders as such",
                "note": ("the decision and its reason are unchanged" if request
                         else "the resolution and its cause are unchanged")}

    def _crossing_notes(self, table: str, key: str, row_id: int) -> list[dict]:
        out = []
        for r in self.db.execute(
                f"SELECT n.text, n.created_at, n.written_by, a.seq shown_seq,"
                f" a.qual shown_qual,"
                f" a.project_id shown_project FROM {table} n"
                f" LEFT JOIN attempts a ON a.id=n.shown_by"
                f" WHERE n.{key}=? ORDER BY n.id", (row_id,)):
            out.append({
                "when": r["created_at"], "by": self._project_name(r["written_by"]),
                "text": r["text"],
                # A and Q labels are per project and these are not, so the
                # evidence carries its project or it names nothing.
                "shown_by": (f"{self._project_name(r['shown_project'])} "
                             f"A{r['shown_seq']}"
                             + (f"@{r['shown_qual']}" if r["shown_qual"] else "")
                             if r["shown_seq"] is not None
                             else "nothing -- INTERPRETATION")})
        return out

    def _question_postscript(self, project: str, question: str, text: str,
                             headline: Optional[str] = None,
                             answer_is: Optional[str] = None,
                             user_said: Optional[str] = None) -> dict:
        """Add what was learned later, without touching what was answered.

        An answered question was a dead end: it could not be superseded and
        could not be answered again. That is right for the answer itself and
        wrong for the question -- six months on, an answer can turn out to
        have been partial, and the only move was to open an unrelated new
        question that pointed at nothing.

        The answer stays exactly as written, with its date, and this sits
        under it with its own. Anyone reading gets both: what was concluded
        then, and what is known now. Rewriting the first to look like the
        second would destroy the only thing that made it worth recording.

        `answer_is` moves where the answer STANDS, which prose under it did
        not: a paper's claim was corrected twice in postscripts and went on
        being cited, because the line every view shows is the answer's own.
        ENDORSED and REJECTED are the user's call and need their words --
        a claim that the user holds something is itself a claim, and it is
        not free. WITHDRAWN is the writer's own, and needs none: saying an
        answer no longer stands costs whoever relied on it nothing they were
        entitled to.
        """
        p = self._project_row(project)
        if not text.strip():
            raise NoteError("a postscript is what turned out to be true later, "
                            "in words")
        mark = (answer_is or "").strip().upper() or None
        said = (user_said or "").strip() or None
        if mark is not None and mark not in ANSWER_IS:
            raise NoteError(
                f"answer_is is one of {ANSWER_IS}, or empty for a note that "
                f"leaves the answer standing where it was -- not {answer_is!r}.")
        if said and mark is None:
            raise NoteError(
                "user_said goes with answer_is: ENDORSED when the user accepted "
                "the answer as theirs, REJECTED when they said it is not. A note "
                "that changes nothing about where the answer stands needs no "
                "user_said -- put what they said in text. Nothing was written.")
        if mark in ("ENDORSED", "REJECTED") and not said:
            raise NoteError(
                f"{mark} is the user's call, and their words are the record of "
                f"it: user_said = what they said, VERBATIM, and where -- e.g. "
                f"「1にしよう。」 (chat, 2026-09-30). The user is the person this "
                f"work is for; a message from an agent -- yours, or the one that "
                f"delegated to you -- is not theirs. If they have not said it, "
                f"the answer stays not endorsed by the user, which is what it "
                f"is. Nothing was written.")
        if mark == "WITHDRAWN" and said:
            raise NoteError(
                "WITHDRAWN is your own finding that the answer no longer stands. "
                "If the user said so, that is answer_is='REJECTED', with their "
                "words. Nothing was written.")
        head = headline_for(headline, text, "postscript")
        with self._writing():
            q = self._question_by_label(p["id"], question)
            if q["status"] == "open":
                raise NoteError(
                    f"{_lab('Q', q)} is still open -- there is no answer to add to. "
                    f"Keep working under it, or note_ask(..., supersedes='{_lab('Q', q)}') "
                    f"if the question itself turned out to be the wrong one."
                )
            if mark is not None and q["answer"] is None:
                raise NoteError(
                    f"{_lab('Q', q)} was {q['status']} without being answered, so "
                    f"there is no answer to call {mark}. A note without "
                    f"answer_is still goes on it.")
            self.db.execute(
                "INSERT INTO postscripts (question_id, text, headline, answer_is,"
                " user_said, created_at) VALUES (?,?,?,?,?,?)",
                (q["id"], text.strip(), head, mark, said, _now()))
            now = self._answer_standing(q["id"])
        out = {"project": project, "question": f"{_lab('Q', q)}",
               "added": f"{len(text.strip())} characters",
               "note": "the answer is unchanged and always will be"}
        if mark is not None:
            out["the answer now"] = standing_words(now)
        return out

    def _postscripts(self, question_id: int) -> list[dict]:
        out = []
        for r in self.db.execute(
                "SELECT text, headline, answer_is, user_said, created_at"
                " FROM postscripts WHERE question_id=? ORDER BY id", (question_id,)):
            n = {"when": r["created_at"], "text": r["text"], "headline": r["headline"]}
            # Only where there is one, so a note that moves nothing reads as
            # it always did.
            if r["answer_is"]:
                n["answer_is"] = r["answer_is"]
            if r["user_said"]:
                n["user_said"] = r["user_said"]
            out.append(n)
        return out

    def _answer_standing(self, question_id: int) -> Optional[dict]:
        """Where a question's answer stands now: whose it is, and whether it
        still stands. None for a question with no answer.

        The latest note that says so, by when it was written -- a note that
        arrived from another machine keeps its own date, and the row order
        here is only the order things were imported. Before any note, the
        words given with the answer; before those, an agent's answer."""
        q = self.db.execute("SELECT answer, answer_user_said, closed_at FROM questions"
                            " WHERE id=?", (question_id,)).fetchone()
        if q is None or q["answer"] is None:
            return None
        n = self.db.execute(
            "SELECT answer_is, user_said, created_at FROM postscripts WHERE"
            f" question_id=? AND answer_is IN ({','.join('?' * len(ANSWER_IS))})"
            " ORDER BY created_at DESC, id DESC LIMIT 1",
            (question_id, *ANSWER_IS)).fetchone()
        if n is not None:
            return {"is": n["answer_is"], "when": n["created_at"],
                    "user_said": n["user_said"]}
        if q["answer_user_said"]:
            return {"is": "ENDORSED", "when": q["closed_at"],
                    "user_said": q["answer_user_said"]}
        return {"is": "NOT_ENDORSED", "when": q["closed_at"], "user_said": None}

    def _fall_back(self, project_id: int, closing_id: int) -> None:
        """Move off a question that is being closed, onto one that is not.

        The pointer only ever moved when a question was ASKED, so answering
        the current one left it resting on an answered question -- and that
        is not a display fault. note_hypothesis attaches to the current
        question and refuses one that is closed, so a project with two open
        questions and a stale pointer could not pre-register anything at all.
        The instruction it got back, "note_ask opens the next one", asked it
        to invent a fourteenth question to reach the eleventh.

        The most recently opened one, because that is the one most recently
        decided to be worth opening. Any of them beats a closed one, and the
        trunk lists the rest.
        """
        cur = self.db.execute("SELECT current_question FROM projects WHERE id=?",
                              (project_id,)).fetchone()["current_question"]
        if cur != closing_id:
            return
        nxt = self.db.execute(
            "SELECT id FROM questions WHERE project_id=? AND status='open' AND id<>?"
            " ORDER BY seq DESC LIMIT 1", (project_id, closing_id)).fetchone()
        if nxt is None:
            # Everything here is answered, and saying so by pointing at the
            # last answer is true. Clearing it made the trunk report "no
            # question yet" about a project full of them, which is the same
            # fault in the other direction.
            return
        self.db.execute("UPDATE projects SET current_question=? WHERE id=?",
                        (nxt["id"], project_id))

    def _current_question(self, project_id: int) -> Optional[sqlite3.Row]:
        """Where the project stands.

        While attempts are open, the question they are under: open work IS
        the position, whatever the pointer says. Replacing that question
        mid-measurement used to move the view to its successor, and the
        falsifier somebody had committed to dropped out of the trunk they
        re-read at every checkpoint -- the README said it did not, and
        nothing tested it, so when _fall_back began moving the pointer on
        supersession nothing failed.

        Otherwise the question the pointer names -- unless that one is closed
        and another is still open, in which case the most recently opened.
        _fall_back moves the pointer at the moment a question closes, and
        only then. A pointer already resting on a closed question when that
        was written was never moved: sainpost-itself sat on answered Q7
        with Q5 open, and note_hypothesis refused it everything, telling it
        to ask a new question to reach an open one. Reading the pointer this
        way heals that, and any pointer an import leaves on a question that
        closed on the other machine, without writing from a read."""
        work = self.db.execute(
            "SELECT q.* FROM attempts a JOIN questions q ON q.id=a.question_id"
            " WHERE a.project_id=? AND a.closed_at IS NULL AND a.origin IS ?"
            " ORDER BY a.seq LIMIT 1", (project_id, self.name)).fetchone()
        if work is not None:
            return work
        p = self.db.execute("SELECT current_question FROM projects WHERE id=?",
                            (project_id,)).fetchone()
        if p is None or p["current_question"] is None:
            return None
        q = self.db.execute("SELECT * FROM questions WHERE id=?",
                            (p["current_question"],)).fetchone()
        if q is not None and q["status"] != "open":
            nxt = self.db.execute(
                "SELECT * FROM questions WHERE project_id=? AND status='open'"
                " ORDER BY seq DESC LIMIT 1", (project_id,)).fetchone()
            if nxt is not None:
                return nxt
        return q

    def _after_close(self, project_id: int) -> None:
        """The last open attempt has just closed, so the position moves onto
        the question that was asked WHILE that work was open and has been
        waiting. note_ask promised exactly that ("close that attempt and it
        becomes current") and nothing did it: the pointer stayed where it
        was, and the question asked in the meantime sat in the footer.

        Which question that is, is recorded when it is ASKED, where the fact
        is known. Reconstructing it afterwards needs "asked in the meantime"
        from something the row carries, and both candidates are wrong: the
        numbering says only which was written first, so laying a tree out
        before starting -- the point of a tree -- makes closing work under Q3
        jump the position to Q7; and these timestamps are whole seconds, so
        by the clock a question asked in the same second as the attempt it
        interrupted is not in the meantime at all.
        """
        if self._open_attempts(project_id):
            return
        row = self.db.execute("SELECT waiting_question FROM projects WHERE id=?",
                              (project_id,)).fetchone()
        if row is None or row["waiting_question"] is None:
            return
        q = self.db.execute("SELECT * FROM questions WHERE id=?",
                            (row["waiting_question"],)).fetchone()
        self.db.execute("UPDATE projects SET waiting_question=NULL WHERE id=?",
                        (project_id,))
        if q is not None and q["status"] == "open":
            self.db.execute("UPDATE projects SET current_question=? WHERE id=?",
                            (q["id"], project_id))

    def _question_by_label(self, project_id: int, label: str) -> sqlite3.Row:
        return self._qa_by_label("Q", project_id, label)

    def _qa_by_label(self, kind: str, project_id: int, label: str) -> sqlite3.Row:
        """The row a label names here. Bare is the row this notebook prints
        bare; a qualified one is the row from that notebook. A miss lists what
        does hold the number, because the likeliest miss is a bare label
        copied from text written where the other row is the bare one."""
        seq, qual = _parse_qa(label, kind)
        table = _QA[kind]
        row = self.db.execute(f"SELECT * FROM {table} WHERE project_id=? AND seq=?"
                              f" AND qual=?", (project_id, seq, qual)).fetchone()
        if row is None:
            held = [_lab(kind, r) for r in self.db.execute(
                f"SELECT seq, qual FROM {table} WHERE project_id=? AND seq=?"
                f" ORDER BY qual", (project_id, seq))]
            what = {"Q": "question", "A": "attempt"}[kind]
            raise NoteError(f"no {what} {label!r} in this project"
                            + (f". {kind}{seq} here is: {', '.join(held)}" if held else ""))
        return row

    # -- attempts ---------------------------------------------------------

    def hypothesis(self, project: str, hypothesis: str, why_now: str, measure: str,
                   falsifier: str, apparatus: str,
                   prompted_by: Optional[str] = None,
                   question: Optional[str] = None,
                   headline: Optional[str] = None) -> dict:
        """Pre-register an attempt. Nothing has been measured yet.

        The front is one question. Attempts may be open side by side under
        it -- two arms of one question, measured in parallel -- but not under
        two questions at once, because then there would be two positions and
        the trunk shows one. Refuses when any of the four pre-commitment
        fields is blank, because the whole point is that they exist before
        the number does.

        `question` opens it under a question other than the current one, and
        the position moves there. Without it the pointer only ever moved to
        the question most recently ASKED, so a tree built before any work
        began left every requirement but the last unreachable: the only
        order that worked was to open one question and measure it before
        writing the next, which is the opposite of laying the argument out
        first. Moving is refused while work is open under another question --
        that is what one front means -- and nothing moves the position
        without opening work there, so the position never points at a
        question nobody is on.

        Returns `already_tried` -- similar hypotheses from EVERY project,
        with their verdicts. That search is not optional and not a separate
        tool: the only route to recording is through it.
        """
        p = self._project_row(project)
        head = headline_for(headline, hypothesis, "hypothesis")
        with self._writing():
            q = (self._question_by_label(p["id"], question) if question
                 else self._current_question(p["id"]))
            if q is None:
                raise NoteError(
                    f"{project} has no current question. note_ask opens one -- an "
                    f"attempt has to hang off the question it is trying to settle."
                )
            opens = self._open_attempts(p["id"])
            # Work open under another question. Reachable only by naming one:
            # without `question` the position IS the open work, so there is
            # nowhere else for it to be.
            elsewhere = [o for o in opens if o["question_id"] != q["id"]]
            if elsewhere:
                where = self._q_label(elsewhere[0]["question_id"])
                raise NoteError(
                    f"{_labels(elsewhere)} {'is' if len(elsewhere) == 1 else 'are'} "
                    f"open under {where}, so that is where this project stands. "
                    f"Arms run side by side under one question, not two: close "
                    f"{'it' if len(elsewhere) == 1 else 'them'} with note_result "
                    f"(ABANDONED counts) before measuring under {_lab('Q', q)}."
                )
            # What can also happen is that q was REPLACED while its arms were
            # still open. The position stays with them, and new work waits for
            # the successor -- two open fronts is how position is lost.
            if q["status"] != "open" and opens:
                nxt = self._q_label(q["superseded_by"])
                raise NoteError(
                    f"{_labels(opens)} {'is' if len(opens) == 1 else 'are'} still "
                    f"open under {_lab('Q', q)}, which was replaced by {nxt} while "
                    f"{'it was' if len(opens) == 1 else 'they were'} running:\n"
                    + "\n".join(f"  {_lab('A', o)}  {o['hypothesis']}\n"
                                f"      falsifier: {o['falsifier']}" for o in opens)
                    + f"\nArms run side by side under one question, not two. Close "
                      f"{'it' if len(opens) == 1 else 'each'} with note_result "
                      f"(ABANDONED counts), and {nxt} becomes current."
                )
            if q["status"] != "open":
                raise NoteError(f"{_lab('Q', q)} is {q['status']}. note_ask opens the next one.")
            beside = opens

            fields = {"hypothesis": hypothesis, "why_now": why_now,
                      "measure": measure, "falsifier": falsifier, "apparatus": apparatus}
            # why_now names the prior RESULT that sent you here. Before any
            # result exists there is none, and requiring it there only buys a
            # paragraph explaining that the field does not apply -- which is
            # what a cold agent wrote into it. Required from the second
            # attempt on, where it is answerable.
            if not self.db.execute(
                    "SELECT 1 FROM attempts WHERE project_id=? AND closed_at IS NOT NULL"
                    " LIMIT 1", (p["id"],)).fetchone():
                fields.pop("why_now")
            blank = [k for k, v in fields.items() if not (v or "").strip()]
            if blank:
                raise NoteError(
                    "these are required before measuring, not after: " + ", ".join(blank)
                    + "\n  measure   = the quantity, and how\n"
                      "  falsifier = what the numbers look like IF THE HYPOTHESIS IS WRONG\n"
                      "  apparatus = the check that the rig is sound (versions, flags, a\n"
                      "              control whose answer you already know)\n"
                      "  why_now   = which prior result prompted this. Interpretation, n=1."
                )

            # The edge points at a RESULT that was read, never at work in
            # flight. While one attempt at a time was the rule, that held by
            # itself and no check was written; with arms open side by side, a
            # sibling can be named, and it has no result to have prompted
            # anything.
            parent = self._attempt_by_label(p["id"], prompted_by) if prompted_by else None
            if parent is not None and parent["closed_at"] is None:
                raise NoteError(
                    f"{_lab('A', parent)} is still open -- prompted_by names the "
                    f"result that sent you here, and it has none yet. An arm "
                    f"beside it is prompted by whatever prompted it, or by "
                    f"nothing: leave prompted_by empty, or name an attempt that "
                    f"note_trunk shows with a verdict."
                )
            # Two fields encode the same link and only one was enforced, so an
            # agent that named A1 in why_now and forgot prompted_by lost the
            # edge with nothing said. The information is right there.
            if parent is None:
                named = sorted({m for m in re.findall(r"\bA(\d+)\b", why_now)
                                if self.db.execute(
                                    "SELECT 1 FROM attempts WHERE project_id=? AND"
                                    " seq=? AND closed_at IS NOT NULL",
                                    (p["id"], int(m))).fetchone()})
                if named:
                    raise NoteError(
                        f"why_now names A{named[0]}, but prompted_by is empty. That "
                        f"edge is what assembles the tree -- prose does not. Pass "
                        f"prompted_by='A{named[0]}' (or drop the label from why_now "
                        f"if it is not what sent you here)."
                    )

            # Both searches run inside the lock, so they describe the record
            # as it was at the instant this attempt entered it. `in_flight`
            # is the reason that matters: an answer computed a moment earlier
            # could miss the collision it exists to report.
            hits = self.already_tried(hypothesis, exclude_project=None, limit=5)
            live = self.in_flight(hypothesis, exclude_project=project, limit=5)

            seq = self._next_seq("attempts", p["id"])
            state = self._code_state(p)
            made = {"hypothesis": hypothesis.strip(), "why_now": why_now.strip(),
                    "measure": measure.strip(), "falsifier": falsifier.strip(),
                    "apparatus": apparatus.strip(), "created_at": _now()}
            self.db.execute(
                "INSERT INTO attempts (project_id, question_id, seq, hypothesis,"
                " headline, why_now,"
                " prompted_by, measure, falsifier, apparatus, open_commit,"
                " open_dirty, open_untracked, created_at, ident, origin)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["id"], q["id"], seq, made["hypothesis"], head, made["why_now"],
                 parent["id"] if parent else None, made["measure"], made["falsifier"],
                 made["apparatus"], state["commit"],
                 None if state["modified"] is None else int(state["modified"]),
                 self._untracked_text(state["untracked"]), made["created_at"],
                 ident("A", made), self.name),
            )
            # The position is where the work is. Persisted as well as read,
            # so that closing the last arm here falls back from the right place.
            self.db.execute("UPDATE projects SET current_question=? WHERE id=?",
                            (q["id"], p["id"]))
        out = {
            "project": project,
            "attempt": f"A{seq}",
            # The question's own body is not this node. Echoed whole, a
            # 900-character question came back on every pre-registration
            # and every request -- the caller reading back what it had just
            # written, against the one-line-per-node rule everywhere else.
            "under": f"{_lab('Q', q)}  {_one_line(q['text'], 96)}",
            "hypothesis": hypothesis.strip(),
            "falsifier": falsifier.strip(),
            "prompted_by": f"{_lab('A', parent)}" if parent else None,
            "already_tried": hits,
            "in_flight": live,
            "measured_against": self._state_out(state),
        }
        if beside:
            # Two arms of one question are compared in the end, and they can
            # only be compared if they were measured the same way. Each gets
            # the others' commitments on the way in, not after the numbers.
            out["open beside it, under the same question"] = [{
                "attempt": f"{_lab('A', a)}", "hypothesis": a["hypothesis"],
                "measure": a["measure"], "falsifier": a["falsifier"],
                "apparatus": a["apparatus"], "open_since": a["created_at"],
            } for a in beside]
            if p["repo"]:
                out["code state of parallel arms"] = (
                    f"every attempt here reads its commit from {p['repo']}. An arm "
                    f"whose code lives in another checkout -- a git worktree -- is "
                    f"recorded against that one's commit, not its own.")
        return out

    def result(self, project: str, result: str, verdict: str,
               attempt: Optional[str] = None,
               cites: Optional[str | list] = None,
               headline: Optional[str] = None) -> dict:
        """Close an attempt, once. Closed attempts are never edited."""
        p = self._project_row(project)
        head = headline_for(headline, result, "result")
        with self._writing():
            a = self._attempt_to_close(p["id"], attempt)
            if a is None:
                raise NoteError(
                    f"{project} has no open attempt. note_hypothesis opens one "
                    f"(and requires its falsifier first)."
                )
            if a["closed_at"] is not None:
                raise NoteError(
                    f"{_lab('A', a)} closed at {a['closed_at']} as {a['verdict']}: "
                    f"{a['result']}\nThe record is append-only. If the finding "
                    f"changed, open a new attempt and point prompted_by at this one."
                )
            verdict = verdict.strip().upper()
            if verdict == "BLOCKED":
                raise NoteError(
                    "BLOCKED is not a result -- nothing was measured. note_blocked "
                    "with stopped=true closes the attempt that way, and it requires "
                    "the invocation, what came back, and which project owns the "
                    "apparatus that broke. A front closed as blocked with nobody "
                    "named is a lost day nobody is working on."
                )
            if verdict not in _VERDICTS_BY_HAND:
                raise NoteError(
                    f"verdict must be one of {_VERDICTS_BY_HAND}, not {verdict!r}")
            if not result.strip():
                raise NoteError("result is the numbers -- what was actually measured")
            state = self._code_state(p)
            self.db.execute(
                "UPDATE attempts SET result=?, result_headline=?, verdict=?,"
                " close_commit=?, close_dirty=?, close_untracked=?, closed_at=?"
                " WHERE id=?",
                (result.strip(), head, verdict, state["commit"],
                 None if state["modified"] is None else int(state["modified"]),
                 self._untracked_text(state["untracked"]),
                 _now(), a["id"]),
            )
            cited = self._cite("A", a["id"], project, cites)
            self._after_close(p["id"])
            still = self._open_attempts(p["id"])
            readings = self._readings_in(a["id"])
        # Not the result back. You wrote it; reading it again costs a copy of
        # everything you just measured, and these run to thousands of
        # characters. The falsifier IS handed back -- that is the check this
        # call exists to make possible, and it is a sentence.
        out = {"project": project, "attempt": f"{_lab('A', a)}", "verdict": verdict,
               "hypothesis": a["hypothesis"],
               "recorded": f"{len(result.strip())} characters",
               "predicted_falsifier": a["falsifier"],
               "measured_against": self._state_out(state)}
        # Beside the falsifier, for the same reason: the call is checked
        # against what is on record, and a reading inside this measurement is
        # on record as false.
        if readings:
            out["a reading in it was false"] = readings
        # The one thing this whole capture exists to make visible. Nothing
        # else in the record can see it: both halves look entirely normal.
        #
        # Both ids are real HEADs read out of the repository, so comparing
        # them is exact. It was not, while this module made a fresh
        # timestamped commit at each end: identical code then produced two
        # different ids and the warning fired on nearly every attempt,
        # destroying with its own noise the one signal it existed to give.
        if (a["open_commit"] and state["commit"]
                and a["open_commit"] != state["commit"]):
            out["THE CODE MOVED UNDER THIS MEASUREMENT"] = (
                f"pre-registered against {a['open_commit'][:12]}, closed against "
                f"{state['commit'][:12]}. The number is not about the code you "
                f"predicted from. Both states are kept; diff them before you "
                f"believe the verdict."
            )
        if still:
            out["still open beside it"] = [f"{_lab('A', o)}  {o['hypothesis']}"
                                           for o in still]
        if cited:
            out["rests on"] = self._citations_of("A", a["id"], brief=True)
        return out

    def _open_attempt(self, project_id: int) -> Optional[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM attempts WHERE project_id=? AND closed_at IS NULL"
            " ORDER BY seq LIMIT 1", (project_id,)).fetchone()

    def _open_attempts(self, project_id: int,
                       everywhere: bool = False) -> list[sqlite3.Row]:
        """This notebook's front: the attempts open here that were opened here.

        One front per project was one agent's position, and two machines
        each have one. An import used to be refused for leaving attempts open
        under two questions; with each machine measuring the same
        investigation, that is the ordinary state of a merged record, and
        "one front" is kept where it means something -- per notebook. An
        attempt opened elsewhere can still be closed here by naming it: the
        handover. `everywhere` is for what open work of anybody's forbids,
        such as answering the question it is under."""
        return self.db.execute(
            "SELECT * FROM attempts WHERE project_id=? AND closed_at IS NULL"
            + ("" if everywhere else " AND origin IS ?") + " ORDER BY seq",
            (project_id,) if everywhere else (project_id, self.name)).fetchall()

    def _open_away(self, project_id: int) -> list[str]:
        """Attempts open in this project that another notebook opened, one line
        each. Not this notebook's front, and not nothing either."""
        return [f"{_lab('A', a)}  {a['headline'] or _one_line(a['hypothesis'], LINE)}"
                f"  (under {self._q_label(a['question_id'])}, open on "
                f"{a['origin'] or 'another notebook'})"
                for a in self._open_attempts(project_id, everywhere=True)
                if a["origin"] != self.name]

    def _attempt_to_close(self, project_id: int, label: Optional[str],
                          none_ok: bool = False) -> Optional[sqlite3.Row]:
        """The named attempt, or the open one when only one is open. With
        several open side by side, guessing would touch somebody else's arm.

        `none_ok` adds the answer "none of them" to that question, for a
        defect in a tool the reporter is only using. Without it the reporter
        of such a bug had to name an arm, and naming one either closed a
        measurement the tool had not stopped or filed the bug as a false
        reading inside a measurement it had nothing to do with. An agent with
        two arms open hit this and filed nothing at all.
        """
        if label:
            return self._attempt_by_label(project_id, label)
        # This notebook's own first. With none open here, what is open is
        # work handed over from another machine, and closing it here is the
        # ordinary handover -- the same guess, over the attempts that exist.
        opens = (self._open_attempts(project_id)
                 or self._open_attempts(project_id, everywhere=True))
        if len(opens) > 1:
            raise NoteError(
                f"{_labels(opens)} are open side by side. Say which one this is "
                f"for: attempt='{_lab('A', opens[0])}' (note_trunk shows each "
                f"with its falsifier)."
                + (f", or attempt='none' if this stopped none of them -- a bug "
                   f"in a tool you are only using" if none_ok else "")
                + "\n" + "\n".join(
                    f"  {_lab('A', a)}  {a['hypothesis']}" for a in opens))
        return opens[0] if opens else None

    def _attempt_by_label(self, project_id: int, label: str) -> sqlite3.Row:
        return self._qa_by_label("A", project_id, label)

    def _next_seq(self, table: str, project_id: int) -> int:
        r = self.db.execute(f"SELECT MAX(seq) m FROM {table} WHERE project_id=?",
                            (project_id,)).fetchone()
        return (r["m"] or 0) + 1

    # -- defects ----------------------------------------------------------
    #
    # The apparatus broke and the fix belongs to somebody else. Everything
    # about the split below exists to keep one line intact: the reporter
    # writes what it SAW, the owner writes what was WRONG. See the comment on
    # the table itself.

    def blocked(self, project: str, invocation: str, observed: str, needed: str,
                owner: str, attempt: Optional[str] = None,
                supersedes: Optional[str] = None,
                stopped: Optional[bool] = None) -> dict:
        """File a defect against the apparatus, and record what it did to your
        measurement: stopped it, or gave one false reading inside it.

        A stop and its defect are one call, not two, because they must not be
        able to diverge: an attempt closed BLOCKED with no defect filed is a
        lost day nobody is working on, and a defect with no blocked
        measurement behind it is the wishlist this record deliberately has no
        room for.

        `stopped` is asked whenever there is an attempt to touch, because only
        the reporter knows whether a number came out. It used to be assumed.
        Every open attempt closed BLOCKED, "not measured", and a seam
        inspection that read a 0.1 mm step as a 138-degree crease -- filed
        after seven predictions and a control had all been measured -- closed
        that attempt as unmeasured, for good. True closes it BLOCKED. False
        links the defect to it as a reading inside it and touches nothing
        else: an open attempt stays open for `result`, a closed one keeps its
        verdict, so the two calls can come in either order.

        The three fields the reporter writes are observation:

          invocation -- what was actually run. Verbatim. Not "I ran the
                        router" but the call.
          observed   -- what came back. Verbatim. Do not summarise a
                        traceback; the summary is where the reading you did
                        not check gets in.
          needed     -- what your measurement needed in order to continue.
                        About your own attempt, not about their code.

        There is deliberately no field for where you think the bug is or how
        you think it should be fixed. You are blocked, which means you did
        not measure the cause -- and a cause asserted without a measurement,
        acted on by somebody else, is exactly the failure this whole record
        exists to stop, crossing an agent boundary.

        Everything else the owner needs is inherited from the attempt: the
        apparatus it committed to, what it was measuring, and the hypothesis
        that made anyone care.

        `supersedes` re-files a defect that came back NOT_ACTIONABLE (or any
        other closed one), keeping the first one's link to the attempt. The
        record has no edit path here either.
        """
        p = self._project_row(project)
        fields = {"invocation": invocation, "observed": observed, "needed": needed}
        blank = [k for k, v in fields.items() if not (v or "").strip()]
        if blank:
            raise NoteError(
                "these are what the owner has to work from: " + ", ".join(blank)
                + "\n  invocation = what you ran, verbatim\n"
                  "  observed   = what came back, verbatim -- do not summarise it\n"
                  "  needed     = what your measurement needed to continue\n"
                  "There is no field for the cause or the fix. You are blocked; you\n"
                  "did not measure either one."
            )

        with self._writing():
            # Inside the lock, behind every refusal: made before them, a call
            # that was refused still left a blank card for an owner nothing
            # had been filed against.
            own = self._referral_stub(owner)
            prior = reading = None
            if supersedes:
                prior = self._defect_by_label(supersedes)
                if prior["closed_at"] is None:
                    raise NoteError(
                        f"{self._rd_label('D', prior)} is still open. Re-file only "
                        f"what came back unresolved."
                    )
                a = self.db.execute("SELECT * FROM attempts WHERE id=?",
                                    (prior["attempt_id"],)).fetchone()
                reading = self.db.execute("SELECT * FROM attempts WHERE id=?",
                                          (prior["reading_in"],)).fetchone()
            else:
                # "none" is the reporter saying no measurement of theirs is
                # involved: the tool is one they are using, not measuring
                # with. It is not the same as omitting the label, which asks
                # for the open attempt and cannot mean this while arms are open.
                nothing_of_mine = (attempt or "").strip().lower() == "none"
                if nothing_of_mine and stopped is not None:
                    raise NoteError(
                        "attempt='none' says no measurement of yours is "
                        "involved, so stopped= has nothing to apply to. Drop "
                        "stopped, or name the attempt this happened in.")
                a = (None if nothing_of_mine else
                     self._attempt_to_close(p["id"], attempt, none_ok=True))
                if a is not None and a["closed_at"] is not None and stopped is not False:
                    raise NoteError(
                        f"{_lab('A', a)} already closed as {a['verdict']}. Open a new "
                        f"attempt and block that, or re-file with supersedes=. If "
                        f"a reading inside {_lab('A', a)} was false, stopped=false "
                        f"files it against that reading and leaves the verdict "
                        f"as it is."
                    )
                if a is not None and stopped is None:
                    raise NoteError(
                        f"{_lab('A', a)} is open. Say what this did to it, with "
                        f"stopped:\n"
                        f"  stopped=true   no number came out. {_lab('A', a)} closes "
                        f"as BLOCKED, 'not measured', and nothing reopens it.\n"
                        f"  stopped=false  it measured, and one reading in it was "
                        f"false. The defect is filed against that reading, and "
                        f"{_lab('A', a)} stays open for note_result.\n"
                        f"Nothing was filed."
                    )
                if a is not None and not stopped:
                    reading, a = a, None
                # No attempt is not a refusal any more. The wishlist this list
                # must not become is kept out by `invocation` and `observed`
                # demanding verbatim text, not by requiring a stopped
                # measurement: "it would be nice if" cannot be written into
                # "what came back, verbatim". Requiring one shut out exactly
                # the reporter who most needs to be heard -- somebody using
                # the apparatus rather than measuring with it, who therefore
                # has no attempt of their own to stop.
            seq = (self.db.execute("SELECT MAX(seq) m FROM defects").fetchone()["m"] or 0) + 1
            state = self._code_state(p)
            # Where the reporter was, read rather than typed. With no attempt
            # there is nothing to inherit the rig from, and the owner still
            # has to be able to find the moment this happened.
            held = a if a is not None else reading
            cq = self._current_question(p["id"])
            context = (None if held is not None else
                       (f"{project} was on {_lab('Q', cq)}: {_one_line(cq['text'], 96)}" if cq else
                        f"{project} had no question open"))
            if a is not None and prior is None:
                # One line. The trunk is one line per attempt and a pasted
                # traceback would swamp it; the verbatim output is in the
                # defect, which is the only place it needs to exist.
                self.db.execute(
                    "UPDATE attempts SET result=?, verdict='BLOCKED', closed_at=?"
                    " WHERE id=?",
                    (f"not measured -- the apparatus failed, see D{seq}",
                     _now(), a["id"]),
                )
                self._after_close(p["id"])
            made = {"invocation": invocation.strip(), "observed": observed.strip(),
                    "needed": needed.strip(), "seen_commit": state["commit"],
                    "seen_dirty": (None if state["modified"] is None
                                   else int(state["modified"])),
                    "seen_untracked": self._untracked_text(state["untracked"]),
                    "created_at": _now()}
            self.db.execute(
                "INSERT INTO defects (seq, ident, reported_by, owner_id, attempt_id,"
                " reading_in, invocation, observed, needed, supersedes, context,"
                " seen_commit, seen_dirty, seen_untracked, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (seq, ident("D", made), p["id"], own["id"],
                 a["id"] if a is not None else None,
                 reading["id"] if reading is not None else None,
                 made["invocation"], made["observed"], made["needed"],
                 prior["id"] if prior else None, context, made["seen_commit"],
                 made["seen_dirty"], made["seen_untracked"], made["created_at"]),
            )
        if a is not None:
            blocked = f"{project} {_lab('A', a)}"
        elif reading is None:
            blocked = ("nothing -- this is a report about the apparatus, not a "
                       "measurement that stopped")
        elif reading["closed_at"] is None:
            blocked = (f"nothing -- {_lab('A', reading)} is still open, and "
                       f"note_result records what it measured")
        else:
            blocked = (f"nothing -- {_lab('A', reading)} closed as "
                       f"{reading['verdict']} and stays that. If this reading "
                       f"changes what that verdict is worth, note_postscript on "
                       f"{_lab('A', reading)} says so beside it")
        return {
            "defect": f"D{seq}",
            "owner": owner,
            "reported_by": project,
            "blocked": blocked,
            **({"a false reading in": f"{project} {_lab('A', reading)}"}
               if reading is not None else {}),
            "supersedes": self._rd_label("D", prior) if prior else None,
            "inherited_from_the_attempt": {
                "hypothesis": held["hypothesis"],
                "measure": held["measure"],
                "apparatus (the rig that broke)": held["apparatus"],
            } if held is not None else {"where the reporter was": context},
            # The owner never has to ask "which version". It is not prose.
            "broke_at": self._state_out(state),
        }

    def fixed(self, defect: str, resolution: str, cause: str, change: str = "",
              verify: str = "", invalidates: str = "") -> dict:
        """Close a defect, once, from the side that owns the apparatus.

        `cause` is required on every resolution and exists only here. It is
        the one field in this record that says what was actually wrong, and
        it is writable only by whoever owns the code -- the reporter never
        had a measurement of it.

        FIXED also requires `change`, `verify` and `invalidates`. `verify` is
        what the blocked party runs before measuring again; without it "fixed"
        is a claim they have to take on trust. `invalidates` is what stops a
        number taken through a broken rig from quietly staying in the record
        as a fact.

        NOT_REPRODUCIBLE requires `verify` too: if it runs here and not there,
        the rigs differ, and that difference is itself an apparatus finding
        the blocked party needs.
        """
        resolution = resolution.strip().upper()
        if resolution not in RESOLUTIONS:
            raise NoteError(f"resolution must be one of {RESOLUTIONS}, not {resolution!r}")
        if not cause.strip():
            raise NoteError(
                "cause is required: what was actually wrong. It is the only field "
                "in this record for that, and only you can write it -- the reporter "
                "saw a symptom.\n  NOT_ACTIONABLE: say what is missing, so the "
                "re-filed one can carry it."
            )
        if resolution == "FIXED":
            missing = [k for k, v in (("change", change), ("verify", verify),
                                      ("invalidates", invalidates)) if not (v or "").strip()]
            if missing:
                raise NoteError(
                    "FIXED requires " + ", ".join(missing) + "\n"
                    "  change      = what you altered\n"
                    "  verify      = what they run to confirm it before measuring again\n"
                    f"  invalidates = one of {INVALIDATES} -- whether numbers already\n"
                    "                taken through the broken rig still stand"
                )
        if resolution == "NOT_REPRODUCIBLE" and not verify.strip():
            raise NoteError(
                "NOT_REPRODUCIBLE requires verify: exactly what you ran, and on "
                "what. It passing for you and failing for them is a difference "
                "between two rigs, and they cannot find it from 'works here'."
            )
        if invalidates and invalidates.strip().upper() not in INVALIDATES:
            raise NoteError(f"invalidates must be one of {INVALIDATES}")

        with self._writing():
            d = self._defect_by_label(defect)
            label = self._rd_label("D", d)
            if d["closed_at"] is not None:
                raise NoteError(
                    f"{label} closed at {d['closed_at']} as {d['resolution']}: "
                    f"{d['cause']}\nThe record is append-only. If it is still "
                    f"broken, the reporter files a new one with supersedes={label}."
                )
            own = self.db.execute("SELECT * FROM projects WHERE id=?",
                                  (d["owner_id"],)).fetchone()
            state = self._code_state(own)
            self.db.execute(
                "UPDATE defects SET resolution=?, cause=?, change=?, verify=?,"
                " invalidates=?, fix_commit=?, fix_dirty=?, fix_untracked=?,"
                " closed_at=? WHERE id=?",
                (resolution, cause.strip(), change.strip(), verify.strip(),
                 invalidates.strip().upper(), state["commit"],
                 None if state["modified"] is None else int(state["modified"]),
                 self._untracked_text(state["untracked"]),
                 _now(), d["id"]),
            )
        who = self.db.execute("SELECT name FROM projects WHERE id=?",
                              (d["reported_by"],)).fetchone()["name"]
        out = {"defect": label, "resolution": resolution,
               "cause": cause.strip(), "tell": who,
               "fixed_at": self._state_out(state)}
        if resolution == "FIXED":
            out["verify (run this before measuring again)"] = verify.strip()
            out["invalidates"] = invalidates.strip().upper()
        elif resolution == "NOT_REPRODUCIBLE":
            out["verify (it passed here)"] = verify.strip()
        return out

    def _referral_stub(self, owner: str) -> sqlite3.Row:
        """The owner's project, created blank if nobody has started it.

        It used to refuse, which forced the reporter to run note_start for
        another team -- writing a `description` of an investigation it knows
        nothing about, and picking a repo for them. An agent did exactly that,
        wrote a disclaimer into the description to cope, and pointed out that
        the tool had required of it the one thing this record exists to
        prevent. The card is left blank instead, and note_start hands it to
        its own team the moment they arrive.
        """
        row = self._project_row(owner, required=False)
        if row is not None:
            return row
        name = owner.strip()
        if not name:
            raise NoteError("a defect needs an owner: the project that owns the "
                            "apparatus that broke")
        self.db.execute(
            "INSERT INTO projects (name, description, repo, stub, created_at)"
            " VALUES (?,'','',1,?)", (name, _now()))
        return self._project_row(name)

    # --- one question back, and one answer. Not a thread ------------------

    def _side_of(self, d: sqlite3.Row, project: str) -> tuple[int, int]:
        """(you, them) as project ids. Either side of a defect may ask."""
        p = self._project_row(project)
        if p["id"] == d["owner_id"]:
            return d["owner_id"], d["reported_by"]
        if p["id"] == d["reported_by"]:
            return d["reported_by"], d["owner_id"]
        raise NoteError(
            f"{self._rd_label('D', d)} is between "
            f"{self._project_name(d['reported_by'])} and "
            f"{self._project_name(d['owner_id'])}. {project!r} is neither, and a "
            f"defect is not a place for a third party to leave notes."
        )

    def query(self, defect: str, project: str, question: str) -> dict:
        """Ask the other side of a defect something, without closing it.

        EITHER side. It was owner-to-reporter only, on the strength of one
        agent needing that direction -- and the very next agent was the
        reporter, read the description, found its own situation named in it
        and the door pointed the wrong way. Both directions were always real:
        the owner needs to know what the thing was supposed to do, and the
        reporter needs to know things only the owner can answer.

        Exactly one question, and one reply. A second exchange means the
        report itself was wrong, and re-filing already exists for that.
        """
        if not question.strip():
            raise NoteError("a query is a question for the other side, in words")
        with self._writing():
            d = self._defect_by_label(defect)
            label = self._rd_label("D", d)
            mine, theirs = self._side_of(d, project)
            if d["closed_at"] is not None:
                raise NoteError(
                    f"{label} is closed as {d['resolution']}. Asking after "
                    f"the fact changes nothing; the reporter re-files with "
                    f"supersedes={label} if it is still broken."
                )
            if d["query"]:
                raise NoteError(
                    f"{label} already asks: {d['query']}\n"
                    f"One question is the round trip a report needs. If it needs "
                    f"another, close it NOT_ACTIONABLE and let them re-file."
                )
            self.db.execute(
                "UPDATE defects SET query=?, asked_by=?, queried_at=? WHERE id=?",
                (question.strip(), mine, _now(), d["id"]))
        return {"defect": label, "asked": question.strip(),
                "of": self._project_name(theirs),
                "still": "open -- this did not close it"}

    def reply(self, defect: str, project: str, answer: str) -> dict:
        """Answer the one question. Comes from the side that was not asked."""
        if not answer.strip():
            raise NoteError("a reply is an answer to the question, in words")
        with self._writing():
            d = self._defect_by_label(defect)
            label = self._rd_label("D", d)
            mine, theirs = self._side_of(d, project)
            if not d["query"]:
                raise NoteError(
                    f"{label} has not asked anything. Nothing here needs a "
                    f"reply; the owner closes it with note_fixed."
                )
            if d["asked_by"] == mine:
                raise NoteError(
                    f"{label}'s question came from {project!r} -- you cannot "
                    f"answer yourself. It is waiting on "
                    f"{self._project_name(theirs)}."
                )
            if d["reply"]:
                raise NoteError(f"{label} was already answered: {d['reply']}")
            self.db.execute("UPDATE defects SET reply=?, replied_at=? WHERE id=?",
                            (answer.strip(), _now(), d["id"]))
        return {"defect": label, "asked": d["query"],
                "answered": answer.strip(), "of": self._project_name(theirs)}

    # -- what somebody wants it to do -------------------------------------

    def request(self, project: str, wanted: str, because: str, owner: str) -> dict:
        """Ask the owner of a tool to make it do something it does not.

        Separate from a defect because nothing is broken. A defect proves it
        happened by pasting what came back; a request has no output to paste,
        so `because` carries the weight: what you were doing when you wanted
        this, and what not having it cost. A preference is not enough --
        "writing one at a time is tedious" is one, "Q1 through Q13 went in as
        thirteen separate calls" is an observation.

        Naming the shape you want is fine here. You know your own need. What
        is still forbidden is telling an owner how to fix something that
        BROKE: that is a claim about code you do not own, and it has no field
        anywhere in this record.
        """
        p = self._project_row(project)
        own = self._referral_stub(owner)
        blank = [k for k, v in (("wanted", wanted), ("because", because))
                 if not (v or "").strip()]
        if blank:
            raise NoteError(
                "a request needs both: " + ", ".join(blank)
                + "\n  wanted  = what you want to be able to do. Name the shape\n"
                  "            if you have one -- you know your own need.\n"
                  "  because = what you were DOING when you wanted it, and what\n"
                  "            not having it cost. Not that it would be nice."
            )
        with self._writing():
            seq = (self.db.execute("SELECT MAX(seq) m FROM requests").fetchone()["m"]
                   or 0) + 1
            cq = self._current_question(p["id"])
            context = (f"{project} was on {_lab('Q', cq)}: {_one_line(cq['text'], 96)}" if cq
                       else f"{project} had no question open")
            made = {"wanted": wanted.strip(), "because": because.strip(),
                    "context": context, "created_at": _now()}
            self.db.execute(
                "INSERT INTO requests (seq, ident, asked_by, owner_id, wanted,"
                " because, context, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (seq, ident("R", made), p["id"], own["id"], made["wanted"],
                 made["because"], context, made["created_at"]))
        return {"request": f"R{seq}", "owner": owner, "asked_by": project,
                "wanted": wanted.strip(), "where the asker was": context,
                "note": "nothing is blocked -- this is a request, and it is the "
                        "owner's call whether to take it"}

    def decide(self, request: str, decision: str, why: str) -> dict:
        """Take a request or turn it down. Once, with the reason either way."""
        decision = decision.strip().upper()
        if decision not in DECISIONS:
            raise NoteError(f"decision must be one of {DECISIONS}, not {decision!r}")
        if not why.strip():
            raise NoteError(
                "why is required on both. DECLINED without a reason reads as "
                "nobody looked; ACCEPTED without one loses what was actually "
                "agreed to, which is rarely the whole of what was asked."
            )
        with self._writing():
            r = self._request_by_label(request)
            label = self._rd_label("R", r)
            if r["closed_at"] is not None:
                raise NoteError(
                    f"{label} was already {r['decision']}: {r['why']}\n"
                    f"The record is append-only. If it should be revisited, "
                    f"the asker files a new one; if something it rests on "
                    f"turned out wrong, note_postscript('{label}') puts that "
                    f"beside it."
                )
            self.db.execute(
                "UPDATE requests SET decision=?, why=?, closed_at=? WHERE id=?",
                (decision, why.strip(), _now(), r["id"]))
        return {"request": label, "decision": decision, "why": why.strip(),
                "wanted": r["wanted"],
                "tell": self._project_name(r["asked_by"])}

    def _request_by_label(self, label: str) -> sqlite3.Row:
        return self._rd_by_label("R", label)

    # -- one number, possibly two records ----------------------------------
    #
    # A request or defect carried from another notebook keeps its number, and
    # the number may be taken here. The first row to hold a number here prints
    # it bare -- so nothing already here is ever relabelled -- and any later
    # one prints the hash of what it was made with beside it. A qualified
    # label is the same on every machine that holds the row; a bare one means
    # whatever the notebook it was written in gave that number.

    def _ident_of(self, kind: str, row: sqlite3.Row) -> str:
        return row["ident"] or ident(kind, row)

    def _rd_rows(self, kind: str, seq: int) -> list[sqlite3.Row]:
        return self.db.execute(f"SELECT * FROM {_RD[kind]} WHERE seq=? ORDER BY id",
                               (seq,)).fetchall()

    def _rd_label(self, kind: str, row: sqlite3.Row) -> str:
        """R6, or R6@3fa2c1 when an earlier row here already holds R6."""
        first = self.db.execute(f"SELECT MIN(id) m FROM {_RD[kind]} WHERE seq=?",
                                (row["seq"],)).fetchone()["m"]
        if first == row["id"]:
            return f"{kind}{row['seq']}"
        return f"{kind}{row['seq']}@{self._ident_of(kind, row)[:_SHORT]}"

    def _rd_by_label(self, kind: str, label: str) -> sqlite3.Row:
        what = {"R": "request", "D": "defect"}[kind]
        seq, prefix = _parse_rd(label, kind)
        rows = self._rd_rows(kind, seq)
        if not rows:
            raise NoteError(f"no {what} {label.strip()!r}")
        if prefix is None:
            return rows[0]
        hits = [r for r in rows if self._ident_of(kind, r).startswith(prefix)]
        if len(hits) == 1:
            return hits[0]
        held = ", ".join(self._rd_label(kind, r) for r in rows)
        if not hits:
            raise NoteError(f"no {what} {label.strip()!r}. {kind}{seq} here is: {held}")
        raise NoteError(f"{label.strip()!r} fits more than one {what}: "
                        + ", ".join(f"{kind}{seq}@{self._ident_of(kind, r)[:16]}"
                                    for r in hits) + ". Give more of the hash.")

    def _rd_line(self, kind: str, row: sqlite3.Row) -> str:
        """A record in one line: its label here, what it says, and its sides."""
        head = _one_line(row["wanted"] if kind == "R" else row["observed"], 60)
        a, b = ((row["asked_by"], row["owner_id"]) if kind == "R"
                else (row["reported_by"], row["owner_id"]))
        return (f"{self._rd_label(kind, row)}  {head}  "
                f"[{self._project_name(a)} -> {self._project_name(b)}]")

    def _carried(self, tbl: str, row_id: int) -> set[str]:
        """Which of this row's writings arrived by import."""
        return {r["event"] for r in self.db.execute(
            "SELECT event FROM carried WHERE tbl=? AND row_id=?", (tbl, row_id))}

    def _meant_elsewhere(self, kind: str, seq: int) -> list[sqlite3.Row]:
        """What a bare label in text written in ANOTHER notebook names here,
        when that is not what it names bare. Empty when there is nothing to
        correct.

        The writer's notebook gave the number to its own record, and every
        record that arrived from elsewhere is marked as such -- so when a
        number is held both by a record made here and by one carried in, the
        carried one is what the carried text meant. With records from more
        than one other notebook under one number, this cannot tell which
        notebook wrote the text, and says so by returning them all."""
        rows = self._rd_rows(kind, seq)
        if len(rows) < 2:
            return []
        away = [r for r in rows if "made" in self._carried(_RD[kind], r["id"])]
        if not away or away == [rows[0]]:
            return []
        return away

    def _misread(self, tbl: str, row: sqlite3.Row,
                 events: Optional[set[str]] = None) -> list[tuple[str, str, int, str, list]]:
        """(field, kind, seq, the text, what it names) for every bare R/D label
        in this row's carried text that names something else here bare.
        `events` narrows it to writings that arrived in one import."""
        carried = self._carried(tbl, row["id"])
        out = []
        for event, fields in _TEXTS[tbl].items():
            if event not in carried or (events is not None and event not in events):
                continue
            for f in fields:
                text = row[f] or ""
                for m in _CITE.finditer(text):
                    if m.group(3):
                        continue                      # qualified: says itself
                    kind, seq = m.group(1), int(m.group(2))
                    meant = self._meant_elsewhere(kind, seq)
                    if meant:
                        out.append((f, kind, seq, text, meant))
        return out

    #: The question or attempt a note hangs off: its text cites that
    #: project's numbers, in the numbering of whoever wrote it.
    _QA_PARENT = {"postscripts": ("questions", "question_id"),
                  "attempt_notes": ("attempts", "attempt_id")}

    def _writer(self, tbl: str, row: sqlite3.Row, event: str) -> tuple[Optional[str], int]:
        """(the notebook a question's or attempt's text was written in -- None
        when all that is known is "not this one" -- and its project).

        What a row was made with was written where the row was. A later
        writing -- an answer, a result, a note -- was written here unless an
        import brought it, and then in the notebook the row came from."""
        if tbl in _QA.values():
            node = row
        else:
            table, key = self._QA_PARENT[tbl]
            node = self.db.execute(f"SELECT origin, project_id FROM {table} WHERE id=?",
                                   (row[key],)).fetchone()
        if tbl in _QA.values() and event == "made":
            return node["origin"], node["project_id"]
        if event not in self._carried(tbl, row["id"]):
            return self.name, node["project_id"]
        return (node["origin"] if node["origin"] != self.name else None), node["project_id"]

    def _qa_misread(self, tbl: str, row: sqlite3.Row) -> list[tuple[str, str, int, list]]:
        """(field, kind, seq, what it names) for every bare Q or A label in
        this row's text that, bare, names something else here than it did
        where it was written. Two notebooks' rows in one project share
        numbers -- a merge, or both adding before importing -- and each
        writer's bare label meant its own notebook's row."""
        if tbl not in ("questions", "attempts", "postscripts", "attempt_notes"):
            return []
        out = []
        for event, fields in _TEXTS[tbl].items():
            if not any(row[f] for f in fields):
                continue
            who, pid = self._writer(tbl, row, event)
            if who == self.name:
                continue                  # written here: bare means bare here
            for f in fields:
                for m in _QA_CITE.finditer(row[f] or ""):
                    if m.group(3):
                        continue                      # qualified: says itself
                    kind, seq = m.group(1), int(m.group(2))
                    held = self.db.execute(
                        f"SELECT * FROM {_QA[kind]} WHERE project_id=? AND seq=?"
                        f" ORDER BY qual", (pid, seq)).fetchall()
                    if len(held) < 2:
                        continue
                    meant = ([h for h in held if h["origin"] == who] if who
                             else [h for h in held if h["qual"]])
                    if meant and not (len(meant) == 1 and meant[0]["qual"] == ""):
                        out.append((f, kind, seq, meant))
        return out

    def _qa_line(self, kind: str, r: sqlite3.Row) -> str:
        return (f"{_lab(kind, r)}  "
                + (r["headline"] or _one_line(r["text" if kind == "Q" else "hypothesis"],
                                              60)))

    def _legend(self, parts: list[tuple[str, sqlite3.Row, str]]) -> dict:
        """For a node and its notes: each bare label in text that was written
        in another notebook, and the record it names here. Empty if none.
        `parts` is (table, row, where): where is "" for the node itself, whose
        texts are named by field, and says which note a note is."""
        found: dict[str, tuple[list, list[str]]] = {}
        for tbl, row, where in parts:
            hits = [(f, kind, seq, meant) for f, kind, seq, _, meant
                    in self._misread(tbl, row)] + self._qa_misread(tbl, row)
            for f, kind, seq, meant in hits:
                label = f"{kind}{seq}"
                spot = where or f
                _, spots = found.setdefault(label, (meant, []))
                if spot not in spots:
                    spots.append(spot)
        if not found:
            return {}
        out = {"read this": (
            "written in another notebook, where a bare label named that "
            "notebook's own record. Here each of these bare labels is a "
            "different record, and the one the text meant is named beside it. "
            "The text is as written. These are string matches -- in a circuit "
            "record R1 or D4 is as often a part as a citation.")}
        for label, (meant, spots) in sorted(
                found.items(), key=lambda kv: (kv[0][0], int(kv[0][1:]))):
            kind = label[0]
            names = " | ".join(self._rd_line(kind, r) if kind in _RD
                               else self._qa_line(kind, r) for r in meant)
            out[label] = ((names if len(meant) == 1 else
                           f"one of: {names} -- records from more than one other "
                           f"notebook hold this number, and nothing says which "
                           f"one wrote this text")
                          + f"   (in: {', '.join(spots)})")
        return out

    def _same_number(self, kind: str, row: sqlite3.Row) -> list[str]:
        """Every other record here that holds this row's number."""
        return [self._rd_line(kind, r)
                + ("  -- carried from another notebook, where it is "
                   f"{kind}{r['seq']}" if "made" in self._carried(_RD[kind], r["id"])
                   else "  -- this notebook's own")
                for r in self._rd_rows(kind, row["seq"]) if r["id"] != row["id"]]

    def _request_row(self, r: sqlite3.Row) -> dict:
        out = {"request": self._rd_label("R", r),
               "owner": self._project_name(r["owner_id"]),
               "asked_by": self._project_name(r["asked_by"]),
               "wanted": r["wanted"],
               "because (the cost of not having it)": r["because"],
               "where the asker was": r["context"],
               "since": r["created_at"]}
        if r["closed_at"]:
            out["decision"] = r["decision"]
            out["why"] = r["why"]
            out["closed_at"] = r["closed_at"]
            later = self._crossing_notes("request_notes", "request_id", r["id"])
            if later:
                out["learned later"] = later
        return out

    def _defect_by_label(self, label: str) -> sqlite3.Row:
        return self._rd_by_label("D", label)

    def _defect_row(self, d: sqlite3.Row) -> dict:
        rep = self.db.execute("SELECT name FROM projects WHERE id=?",
                              (d["reported_by"],)).fetchone()["name"]
        own = self.db.execute("SELECT name FROM projects WHERE id=?",
                              (d["owner_id"],)).fetchone()["name"]
        a = (self.db.execute("SELECT * FROM attempts WHERE id=?",
                             (d["attempt_id"],)).fetchone()
             if d["attempt_id"] else None)
        r = (self.db.execute("SELECT * FROM attempts WHERE id=?",
                             (d["reading_in"],)).fetchone()
             if d["reading_in"] else None)
        held = a if a is not None else r
        sup = (self.db.execute("SELECT * FROM defects WHERE id=?",
                               (d["supersedes"],)).fetchone()
               if d["supersedes"] else None)
        out = {
            "defect": self._rd_label("D", d),
            "owner": own,
            "reported_by": rep,
            "blocked": (f"{rep} {_lab('A', a)}  {a['hypothesis']}" if a is not None
                        else d["context"] or f"{rep} (no measurement stopped)"),
            **({"a false reading in": f"{rep} {_lab('A', r)}  {r['hypothesis']}"}
               if r is not None else {}),
            "since": d["created_at"],
            # observation, written by the party that could not measure
            "invocation": d["invocation"],
            "observed": d["observed"],
            "needed": d["needed"],
            "apparatus (inherited from the attempt)":
                held["apparatus"] if held is not None else None,
            # The row it re-files, by its label. This printed the row's id,
            # which is this database's own number and equals the label only
            # while no record from another notebook has been carried in.
            "supersedes": self._rd_label("D", sup) if sup is not None else None,
        }
        if d["query"]:
            asker = self._project_name(d["asked_by"]) if d["asked_by"] else "?"
            out[f"{asker} asks"] = d["query"]
            out["answered"] = d["reply"] or "(not yet)"
        if d["seen_commit"]:
            out["broke at"] = d["seen_commit"][:12] + (
                " (tracked files differed -- the owner cannot reproduce from this "
                "commit alone)" if d["seen_dirty"] else "") + (
                f" (untracked: {d['seen_untracked']})" if d["seen_untracked"] else "")
        if d["closed_at"]:
            out["resolution"] = d["resolution"]
            out["cause (found by the owner)"] = d["cause"]
            out["change"] = d["change"] or None
            out["verify"] = d["verify"] or None
            out["invalidates"] = d["invalidates"] or None
            if d["fix_commit"]:
                out["fixed at"] = d["fix_commit"][:12]
            out["closed_at"] = d["closed_at"]
            later = self._crossing_notes("defect_notes", "defect_id", d["id"])
            if later:
                out["learned later"] = later
        return out

    def defects(self, project: Optional[str] = None, closed: bool = False) -> dict:
        """Every measurement currently stopped on somebody else, machine-wide.

        This is the list an agent reads to find work waiting on it. It cannot
        rot into a wishlist, because a row only exists while a specific
        pre-registered measurement is stopped by it.
        """
        where, args = ("" if closed else " WHERE closed_at IS NULL"), []
        if project:
            p = self._project_row(project)
            where += (" AND" if where else " WHERE") + " (owner_id=? OR reported_by=?)"
            args = [p["id"], p["id"]]
        rows = self.db.execute(
            f"SELECT * FROM defects{where} ORDER BY closed_at IS NOT NULL, seq", args)
        where_r, args_r = ("" if closed else " WHERE closed_at IS NULL"), []
        if project:
            pr = self._project_row(project)
            where_r += (" AND" if where_r else " WHERE") + " (owner_id=? OR asked_by=?)"
            args_r = [pr["id"], pr["id"]]
        reqs = self.db.execute(
            f"SELECT * FROM requests{where_r} ORDER BY closed_at IS NOT NULL, seq",
            args_r)
        out = {"scope": project or "every project",
               "defects": [self._defect_row(r) for r in rows],
               "requests": [self._request_row(r) for r in reqs]}
        if not out["defects"] and not out["requests"] and not closed:
            # An empty list read as "there were never any". A closed defect is
            # real history -- what broke, and what it turned out to be -- and
            # it was reachable only by knowing this argument exists.
            n = self.db.execute("SELECT COUNT(*) c FROM defects WHERE closed_at"
                                " IS NOT NULL").fetchone()["c"]
            out["note"] = (f"nothing is blocked. {n} defect(s) have been closed; "
                           f"note_defects(closed=True) has what they turned out "
                           f"to be." if n else "nothing is blocked, and nothing "
                           "ever has been.")
        return out

    def _defect_lines(self, project_id: int) -> tuple[list[str], list[str]]:
        """(what is stopping you, what is waiting on you) -- one line each.

        Both belong in the trunk. A defect you filed is why your front is
        empty; a defect you own is somebody else's front standing still.
        Neither is visible anywhere the position is read, otherwise.
        """
        def lines(mine: str, theirs: str) -> list[str]:
            out = []
            for r in self.db.execute(
                    f"SELECT * FROM defects WHERE {mine}=? AND closed_at IS NULL"
                    " ORDER BY seq, id", (project_id,)).fetchall():
                head = _one_line(r["observed"])
                out.append(f"{self._rd_label('D', r)}  {head}   "
                           f"[{self._project_name(r[theirs])}]")
            return out

        return lines("reported_by", "owner_id"), lines("owner_id", "reported_by")

    def _request_lines(self, project_id: int) -> tuple[list[str], list[str]]:
        """(what you are waiting for, what is waiting on you) -- requests.

        Same two directions as defects, and shown in the same places: what an
        agent needs is one answer to "what is on my plate", not two lists it
        has to remember to check separately."""
        def lines(mine: str, theirs: str) -> list[str]:
            return [f"{self._rd_label('R', r)}  {r['wanted'][:70]}   "
                    f"[{self._project_name(r[theirs])}]"
                    for r in self.db.execute(
                        f"SELECT * FROM requests WHERE {mine}=? AND closed_at IS NULL"
                        " ORDER BY seq, id", (project_id,)).fetchall()]
        return lines("asked_by", "owner_id"), lines("owner_id", "asked_by")

    def _project_name(self, pid: int) -> str:
        return self.db.execute("SELECT name FROM projects WHERE id=?",
                               (pid,)).fetchone()["name"]

    def _readings_in(self, attempt_id: int) -> list[str]:
        """Defects filed against a false reading inside this attempt, one line
        each. Printed wherever its verdict is, because a verdict can rest on
        the reading -- the first one to arrive had fired a falsifier."""
        return [f"{self._rd_label('D', d)} -> {self._project_name(d['owner_id'])} "
                + ("[open]" if d["closed_at"] is None else f"[{d['resolution']}]")
                for d in self.db.execute(
                    "SELECT * FROM defects WHERE reading_in=? ORDER BY seq, id",
                    (attempt_id,)).fetchall()]

    # -- reading ----------------------------------------------------------

    def already_tried(self, text: str, exclude_project: Optional[str] = None,
                      limit: int = 5, threshold: float = 0.30) -> list[dict]:
        """Closed attempts whose hypothesis reads like this one, any project.

        Closed only, and that stays true: prior art is a hypothesis somebody
        already carried to a verdict. An attempt still open has nothing to
        report about whether the idea works. What it does report -- that
        someone is measuring this right now -- is a different fact with a
        different consequence, so it comes back from `in_flight` instead of
        being mixed in here with a verdict of None.
        """
        rows = self.db.execute(
            "SELECT a.*, p.name project FROM attempts a JOIN projects p ON p.id=a.project_id"
            " WHERE a.closed_at IS NOT NULL"
        ).fetchall()
        scored = []
        for r in rows:
            if exclude_project and r["project"] == exclude_project:
                continue
            s = similarity(text, r["hypothesis"])
            if s >= threshold:
                scored.append((s, r))
        scored.sort(key=lambda t: -t[0])
        return [{
            "project": r["project"],
            "attempt": f"{_lab('A', r)}",
            "similarity": round(s, 2),
            "hypothesis": r["headline"] or r["hypothesis"],
            "verdict": r["verdict"],
            # What a reader wants from prior art is "somebody carried this to
            # FALSIFIED, and here is what fell over". That is the result's
            # first line. Whole, four of these came back on one
            # pre-registration -- 7,000 characters of numbers nobody had
            # asked for -- and there were six more questions to register.
            "result": r["result_headline"] or _one_line(r["result"] or "", LINE) or None,
        } for s, r in scored[:limit]]

    def in_flight(self, text: str, exclude_project: Optional[str] = None,
                  limit: int = 5, threshold: float = 0.30) -> list[dict]:
        """OPEN attempts elsewhere that read like this one. The collision channel.

        Arms open side by side in one project are returned by note_hypothesis
        whole, as its own list; this is for the other projects. The moment a
        second agent works the same investigation from its own, nothing in the
        record stops the two of them pre-registering the same hypothesis
        within a minute of each other. Neither would ever learn it: the
        other attempt has no verdict, so `already_tried` cannot mention it,
        and `search` is the one tool nobody is obliged to call.

        This is reported, never refused. Two agents measuring the same thing
        on different apparatus is a replication and worth having; two doing
        it by accident is waste. Only the caller can tell which, and it can
        only tell with the other attempt's falsifier and apparatus in hand,
        so both are returned.
        """
        rows = self.db.execute(
            "SELECT a.*, p.name project FROM attempts a JOIN projects p ON p.id=a.project_id"
            " WHERE a.closed_at IS NULL"
        ).fetchall()
        scored = []
        for r in rows:
            if exclude_project and r["project"] == exclude_project:
                continue
            s = similarity(text, r["hypothesis"])
            if s >= threshold:
                scored.append((s, r))
        scored.sort(key=lambda t: -t[0])
        return [{
            "project": r["project"],
            "attempt": f"{_lab('A', r)}",
            "similarity": round(s, 2),
            "hypothesis": r["headline"] or r["hypothesis"],
            "falsifier": r["falsifier"],
            "apparatus": r["apparatus"],
            "open_since": r["created_at"],
        } for s, r in scored[:limit]]

    def search(self, query: str, project: Optional[str] = None,
               limit: int = 20, threshold: float = 0.18) -> dict:
        """Hypotheses and questions that read like the query, across projects."""
        where, args = "", []
        if project:
            self._project_row(project)
            where, args = " WHERE p.name=?", [project]
        a_rows = self.db.execute(
            "SELECT a.*, p.name project FROM attempts a JOIN projects p ON p.id=a.project_id"
            + where, args).fetchall()
        q_rows = self.db.execute(
            "SELECT q.*, p.name project FROM questions q JOIN projects p ON p.id=q.project_id"
            + where, args).fetchall()

        att = sorted(
            ((similarity(query, r["hypothesis"]), r) for r in a_rows),
            key=lambda t: -t[0])
        que = sorted(
            ((max(similarity(query, r["text"]), similarity(query, r["answer"] or "")), r)
             for r in q_rows), key=lambda t: -t[0])
        return {
            "query": query,
            "attempts": [{
                "project": r["project"], "attempt": f"{_lab('A', r)}",
                "similarity": round(s, 2), "hypothesis": r["hypothesis"],
                "verdict": r["verdict"] or "OPEN", "result": r["result"],
            } for s, r in att if s >= threshold][:limit],
            "questions": [self._found_question(s, r) for s, r in
                          [(s, r) for s, r in que if s >= threshold][:limit]],
        }

    def _found_question(self, s: float, r: sqlite3.Row) -> dict:
        """A question search turned up. Where its answer stands comes before
        the answer: search hands answers back whole, and one that the user
        rejected read exactly like one they wrote."""
        st = self._answer_standing(r["id"])
        return {"project": r["project"], "question": f"{_lab('Q', r)}",
                "similarity": round(s, 2), "text": r["text"], "status": r["status"],
                **({"the answer is": standing_words(st)} if st else {}),
                "answer": r["answer"]}

    def question_chain(self, project_id: int, q: sqlite3.Row) -> list[sqlite3.Row]:
        """The reformulations that led to `q`, oldest first."""
        chain, seen = [], set()
        cur = q
        while cur is not None and cur["supersedes"] is not None:
            if cur["supersedes"] in seen:
                break
            seen.add(cur["supersedes"])
            cur = self.db.execute("SELECT * FROM questions WHERE id=?",
                                  (cur["supersedes"],)).fetchone()
            if cur is not None:
                chain.append(cur)
        return list(reversed(chain))

    def trunk(self, project: str, question: Optional[str] = None) -> dict:
        """Where you are: the current question, how it got reformulated, and
        one line per attempt under it. This is the thing meant to be re-read
        at every checkpoint, so it stays small on purpose -- bodies come from
        `open`."""
        p = self._project_row(project)
        q = (self._question_by_label(p["id"], question) if question
             else self._current_question(p["id"]))
        if q is None:
            blocked_on, waiting = self._defect_lines(p["id"])
            aw, ow = self._request_lines(p["id"])
            blocked_on, waiting = blocked_on + aw, waiting + ow
            return {"project": project, "question": None,
                    "blocked_on": blocked_on, "waiting_on_you": waiting,
                    "note": f"{project} has no question yet. note_ask opens one."}
        rows = self.db.execute(
            "SELECT * FROM attempts WHERE question_id=? ORDER BY seq", (q["id"],)).fetchall()
        # Its successor is not "another open question" -- printing it in that
        # footer while reading a superseded question reads as unrelated work.
        others = self.db.execute(
            "SELECT id, seq, qual, text, headline, parent FROM questions"
            " WHERE project_id=? AND status='open'"
            " AND id<>? AND (? IS NULL OR id<>?) ORDER BY seq",
            (p["id"], q["id"], q["superseded_by"], q["superseded_by"])).fetchall()
        above = {a["id"] for a in self._ancestors(q)}
        blocked_on, waiting = self._defect_lines(p["id"])
        aw, ow = self._request_lines(p["id"])
        blocked_on, waiting = blocked_on + aw, waiting + ow
        # Open work under another question -- the one being read is not the
        # current one, or the current one was replaced mid-measurement -- still
        # has to be visible: it is what somebody here is in the middle of.
        # One format, not two: the hypothesis was put into an f-string and the
        # result handed to "%", so a hypothesis containing "%" -- "50% の…" --
        # was read as a format directive, and reading any other question of a
        # project with such an attempt open raised ValueError.
        stray = [f"{_lab('A', o)}  {o['hypothesis']}  "
                 f"(under {self._q_label(o['question_id'])})"
                 for o in self._open_attempts(p["id"]) if o["question_id"] != q["id"]
                 ] or None
        return {
            "project": project,
            "repo": p["repo"] or None,
            "question": f"{_lab('Q', q)}",
            "text": q["text"],
            "status": q["status"],
            "answer": q["answer"],
            "answer_headline": q["answer_headline"],
            "answer_is": self._answer_standing(q["id"]),
            "learned_later": self._postscripts(q["id"]),
            "rests_on": self._warned_citations("Q", q["id"]),
            "superseded_by": self._q_label(q["superseded_by"]),
            "reformulated_from": [
                {"question": f"{_lab('Q', r)}", "text": r["text"]}
                for r in self.question_chain(p["id"], q)],
            # What this question is in service of, and what it is waiting on.
            # Both are position: an answer here cannot be written while
            # anything below is open, and the reader of a requirement needs
            # to know which claim it was opened to support.
            "in_service_of": [self._q_line(a) for a in self._ancestors(q)] or None,
            "opened_under_it": [self._q_line(c) for c in self._children(q["id"])] or None,
            "attempts": [{
                "attempt": f"{_lab('A', r)}",
                "verdict": r["verdict"] or "OPEN",
                "hypothesis": r["hypothesis"],
                "result": r["result"],
                "falsifier": r["falsifier"] if r["closed_at"] is None else None,
                "apparatus": r["apparatus"] if r["closed_at"] is None else None,
                "prompted_by": self._label_of(r["prompted_by"]),
                "learned_later": self._attempt_notes(r["id"]),
                "false_readings": self._readings_in(r["id"]),
                "rests_on": self._warned_citations("A", r["id"]),
                "since": r["created_at"] if r["closed_at"] is None else None,
            } for r in rows],
            # Neither the children nor the line of questions this one serves:
            # both are printed above, and a question that is your own parent
            # read as unrelated work is the flat list this tree replaced.
            "other_open_questions": [
                f"{_lab('Q', r)}  {r['headline'] or _one_line(r['text'], LINE)}" for r in others
                if r["parent"] != q["id"] and r["id"] not in above],
            "blocked_on": blocked_on,
            "waiting_on_you": waiting,
            "open_elsewhere": stray,
            **({"open_on_other_notebooks": away}
               if (away := self._open_away(p["id"])) else {}),
        }

    def trail(self, project: str, question: Optional[str] = None) -> dict:
        """The whole path of trial and error, one line per node.

        `question` reads one BRANCH: that question, everything opened under
        it, and the line of questions it serves. A project's whole trail
        outgrows what one reply can carry -- 275 attempts came to 170 KB,
        past what the client will hand the model -- and a tree gives the
        unit to read it in.

        Not named `path`: this class already carries `self.path`, the file the
        notebook lives in, and a method of that name is simply unreachable
        behind it.

        `trunk` answers "where am I", and stays small by showing one question.
        That is the wrong shape for the other question an agent arrives with:
        what has already been ruled out, and what is standing. Three cold
        agents in a row reconstructed this by hand, calling trunk once per
        question after guessing the labels.

        A FALSIFIED row is the most valuable kind in the record, and it is
        worth nothing if nobody reads it. So the dead ends are pulled out
        separately as well as sitting in the trail: in a long project the
        trail is long, and "what must I not re-derive" is what gets scanned.

        Still one line per node. Bodies come from `open`, as everywhere.
        """
        p = self._project_row(project)
        qs = self.db.execute(
            "SELECT * FROM questions WHERE project_id=? ORDER BY seq", (p["id"],)
        ).fetchall()
        above = []
        if question:
            root = self._question_by_label(p["id"], question)
            keep = {root["id"]} | {b["id"] for b in self._below(root["id"])}
            above = [self._q_line(a) for a in self._ancestors(root)]
            qs = [q for q in qs if q["id"] in keep]
        blocked_by = {r["attempt_id"]: r for r in self.db.execute(
            "SELECT d.*, o.name owner FROM defects d JOIN projects o ON o.id=d.owner_id"
            " WHERE d.reported_by=?", (p["id"],))}

        # Questions carry work too. Counting only attempt verdicts made a
        # project with thirteen answered questions and the measurements
        # behind them open with "nothing yet" -- the headline saying the
        # opposite of what it holds, to the reader who has not scrolled yet.
        answered = sum(1 for q in qs if q["status"] == "answered")
        still_open = sum(1 for q in qs if q["status"] == "open")
        trail, dead, standing, unsettled, counts = [], [], [], [], {}
        # Confirmed under an answer that was then rejected by the user or
        # withdrawn. The measurement stands; what it was standing FOR does
        # not, and STANDING is read as what to rest on.
        gone: list = []
        whose: dict = {}
        # "The branch being worked": the current question with what it serves
        # and what is under it -- or, when one branch was asked for, that one.
        # It decides what is kept when the reply cannot hold everything.
        cur = self._current_question(p["id"])
        live = set()
        if question:
            live = keep
        elif cur is not None:
            live = ({cur["id"]} | {a["id"] for a in self._ancestors(cur)}
                    | {b["id"] for b in self._below(cur["id"])})
        for q, depth in self._question_tree(qs):
            st = self._answer_standing(q["id"])
            if st is not None and q["status"] == "answered":
                whose[st["is"]] = whose.get(st["is"], 0) + 1
            node = {"question": f"{_lab('Q', q)}", "text": q["text"], "depth": depth,
                    "live": q["id"] in live,
                    "headline": q["headline"], "answer_headline": q["answer_headline"],
                    "under": self._q_label(q["parent"]),
                    "status": q["status"], "answer": q["answer"],
                    "answer_is": st, "state": self._q_state(q),
                    "learned_later": self._postscripts(q["id"]),
                    "supersedes": self._q_label(q["supersedes"]),
                    "superseded_by": self._q_label(q["superseded_by"]),
                    "attempts": []}
            for a in self.db.execute(
                    "SELECT * FROM attempts WHERE question_id=? ORDER BY seq",
                    (q["id"],)):
                v = a["verdict"] or "OPEN"
                counts[v] = counts.get(v, 0) + 1
                row = {"attempt": f"{_lab('A', a)}", "verdict": v,
                       "under": f"{_lab('Q', q)}", "live": q["id"] in live,
                       "hypothesis": a["hypothesis"], "headline": a["headline"],
                       "result": (a["result_headline"]
                                  or _one_line(a["result"] or "", LINE) or None),
                       "prompted_by": self._label_of(a["prompted_by"]),
                       "learned_later": self._attempt_notes(a["id"]),
                       "false_readings": self._readings_in(a["id"])}
                d = blocked_by.get(a["id"])
                if d is not None:
                    row["defect"] = (f"{self._rd_label('D', d)} -> {d['owner']}"
                                     + ("" if d["closed_at"] is None
                                        else f" [{d['resolution']}]"))
                node["attempts"].append(row)
                node.setdefault("verdicts", {})
                node["verdicts"][v] = node["verdicts"].get(v, 0) + 1
                node["last_touch"] = max(node.get("last_touch") or "",
                                         a["closed_at"] or a["created_at"])
                if v in ("FALSIFIED", "ABANDONED"):
                    dead.append(row)
                elif v == "CONFIRMED" and st is not None and st["is"] in GONE:
                    gone.append(row)
                elif v == "CONFIRMED":
                    standing.append(row)
                else:
                    # OPEN, INCONCLUSIVE, BLOCKED: nothing was settled, and
                    # each for a different reason. Lumping them with the dead
                    # ends would retire work that is still live.
                    unsettled.append(row)
            node["last_touch"] = max(node.get("last_touch") or "",
                                     q["closed_at"] or q["created_at"])
            trail.append(node)

        return {
            "project": project,
            "repo": p["repo"] or None,
            "branch": f"{_lab('Q', root)}" if question else None,
            "in_service_of": above or None,
            "tally": "; ".join(
                x for x in (
                    ", ".join(f"{n} {v}" for v, n in sorted(counts.items()))
                    or ("no attempt has reached a verdict" if qs else None),
                    # Whose the answers are, counted where a reader looks
                    # first. "21 answered" read as 21 settled claims; none of
                    # them was the user's.
                    (f"{answered} question(s) answered ("
                     + ", ".join(f"{whose[k]} {w}" for k, w in (
                         ("NOT_ENDORSED", "not endorsed by the user"),
                         ("ENDORSED", "endorsed by the user"),
                         ("REJECTED", "rejected by the user"),
                         ("WITHDRAWN", "withdrawn")) if whose.get(k)) + ")"
                     if answered else None),
                    (f"{still_open} still open" if still_open else None),
                ) if x) or "nothing yet",
            "reformulations": sum(1 for q in qs if q["superseded_by"]),
            # Only questions that actually replaced one another. The digest
            # used to print every question in the project as one chain --
            # "the question moved: Q1 -> Q2 -> ... -> Q8" -- about eight
            # questions where none had superseded any other. A reader who
            # trusted that headline read a project as one long reformulation
            # and the earlier questions as dead ends, which is the opposite
            # of what those rows say.
            "reformulated": self._reformulation_chains(qs),
            "trail": trail,
            "closed_off": dead,
            "standing": standing,
            "no_longer_standing": gone,
            "open_now": unsettled,
        }

    @staticmethod
    def _question_tree(qs: list) -> list:
        """(question, depth), depth-first: each question followed by the ones
        opened under it. A question whose parent is not here stands at the
        root rather than disappearing."""
        kids: dict = {}
        for q in qs:
            kids.setdefault(q["parent"], []).append(q)
        known = {q["id"] for q in qs}
        out: list = []

        def walk(q, depth: int) -> None:
            out.append((q, depth))
            for c in kids.get(q["id"], []):
                walk(c, depth + 1)

        for q in qs:
            if q["parent"] is None or q["parent"] not in known:
                walk(q, 0)
        return out

    @staticmethod
    def _reformulation_chains(qs: list) -> list:
        """Each run of questions that actually replaced one another."""
        by_id = {q["id"]: q for q in qs}
        chains = []
        for q in qs:
            if q["superseded_by"] is None or q["supersedes"] is not None:
                continue                      # not the head of a chain
            chain, cur = [f"{_lab('Q', q)}"], q
            while cur["superseded_by"] in by_id:
                cur = by_id[cur["superseded_by"]]
                chain.append(f"{_lab('Q', cur)}")
            chains.append(chain)
        return chains

    # -- what a result or an answer rests on, in another project ----------

    def _cite(self, kind: str, node_id: int, project: str,
              cites: Optional[str | list]) -> list[str]:
        """Record what this node stands on. Refuses a name that is nothing.

        A citation that names no row is worse than none: it reads as a
        reference and cannot be followed, which is how "the record says 119"
        survived when the registered number was 113.
        """
        specs = ([s.strip() for s in cites.split(",")] if isinstance(cites, str)
                 else [str(s).strip() for s in (cites or [])])
        made, missing = [], []
        for spec in [s for s in specs if s]:
            role = "supports"
            for word in ROLES:
                if spec.lower().startswith(word + ":"):
                    role, spec = word, spec[len(word) + 1:].strip()
            where, _, label = spec.rpartition("/")
            where = where.strip() or project
            row = self._cited_row(where, label)
            if row is None:
                missing.append(spec)
                continue
            to = label[:1].upper()
            self.db.execute(
                "INSERT INTO citations (kind, node_id, to_project, to_kind, to_seq,"
                " to_created, to_id, role, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (kind, node_id, where, to, row["seq"],
                 row["created_at"], row["id"], role, _now()))
            made.append(f"{where}/{_lab(to, row)}")
        if missing:
            raise NoteError(
                "nothing here is " + ", ".join(repr(m) for m in missing)
                + ". A citation is followed, so it names a row or it is not "
                  "written: 'project/A4' or 'project/Q2', or a bare label for "
                  "this project. note_projects lists the projects; note_path "
                  "lists their labels.")
        return made

    def _cited_row(self, project: str, label: str) -> Optional[sqlite3.Row]:
        p = self._project_row(project, required=False)
        if p is None or label[:1].upper() not in ("A", "Q"):
            return None
        try:
            return self._qa_by_label(label[:1].upper(), p["id"], label)
        except NoteError:
            return None

    def _citations_of(self, kind: str, node_id: int, brief: bool = False) -> list[dict]:
        """Each cited row as it stands NOW, and what has been learned about
        it since it was cited.

        `brief` drops the cited row's own numbers. On a WRITE they are the
        one thing the caller does not need: it has just decided to stand on
        them. Six citations came back with a line of result each on every
        answer, and the writes in one afternoon were returning more than ten
        thousand characters a call -- enough that the work stopped.
        """
        out = []
        for c in self.db.execute(
                "SELECT * FROM citations WHERE kind=? AND node_id=? ORDER BY id",
                (kind, node_id)):
            name = f"{c['to_project']}/{c['to_kind']}{c['to_seq']}"
            if c["to_id"] is None:
                out.append({"cites": name,
                            "READ IT YOURSELF": "not in this notebook -- it was "
                                                "cited on another machine"})
                continue
            item = (self._cited_attempt(name, c) if c["to_kind"] == "A"
                    else self._cited_question(name, c))
            if brief:
                item.pop("result", None)
                item.pop("answer", None)
            out.append(item)
        return out

    def _cited_attempt(self, name: str, c: sqlite3.Row) -> dict:
        a = self.db.execute("SELECT * FROM attempts WHERE id=?", (c["to_id"],)).fetchone()
        item = {"cites": name, "as": c["role"],
                "hypothesis": a["headline"] or _one_line(a["hypothesis"], LINE),
                "verdict": a["verdict"] or "OPEN",
                "result": (a["result_headline"]
                           or _one_line(a["result"] or "", LINE) or None)}
        why = []
        # Only where the citation LEANS on it, and which way it leans decides
        # which verdict is the sound one. Cited as a record of what happened,
        # a falsified attempt is exactly what was meant, and saying so on
        # every one of them buries the notes that matter.
        if c["role"] == "records":
            pass
        elif a["verdict"] in (None, "OPEN"):
            why.append("it is still open: there is no result yet to rest on")
        elif c["role"] == "refutes":
            if a["verdict"] != "FALSIFIED":
                why.append(f"it is {a['verdict']}, so there is no refutation "
                           f"here to rest on")
        elif a["verdict"] != "CONFIRMED":
            why.append(f"it is {a['verdict']}, which is not a standing result")
        # What it was standing FOR. A confirmed attempt whose question's
        # answer the user then rejected is still cited as support, and the
        # citing row read as sound: a paper's requirements rested on the
        # attempt that WAS its rejected claim. Learned later, so every role.
        st = self._answer_standing(a["question_id"])
        if st is not None and st["is"] in GONE:
            where = f"{c['to_project']}/{self._q_label(a['question_id'])}"
            why.append(f"it stood under {where}, whose answer was "
                       + standing_words(st))
        # Every note on it, not only the ones dated after the citation. The
        # comparison looked exact and was not: these timestamps are whole
        # seconds, so a note written in the same second as the citation --
        # or by the same session a moment before it -- came out as nothing
        # to read. What matters is that the record you are standing on has
        # been annotated at all; the date says whether it is news.
        why += [f"learned later about it ({n['created_at'][:10]}): "
                f"{_one_line(n['text'], 96)}"
                for n in self.db.execute(
                    "SELECT text, created_at FROM attempt_notes WHERE attempt_id=?"
                    " ORDER BY id", (a["id"],))]
        why += [f"a reading in it was reported false: {d}"
                for d in self._readings_in(a["id"])]
        if why:
            item["READ IT AGAIN"] = why
        return item

    def _cited_question(self, name: str, c: sqlite3.Row) -> dict:
        q = self.db.execute("SELECT * FROM questions WHERE id=?", (c["to_id"],)).fetchone()
        item = {"cites": name, "as": c["role"],
                "question": q["headline"] or _one_line(q["text"], LINE),
                "status": q["status"],
                "answer": (q["answer_headline"]
                           or _one_line(q["answer"] or "", LINE) or None)}
        why = []
        st = self._answer_standing(q["id"])
        if c["role"] == "records":
            pass
        elif q["status"] == "open":
            why.append("it is still open: there is no answer yet to rest on")
        elif q["status"] == "superseded":
            why.append(f"it was replaced by {self._q_label(q['superseded_by'])}")
        if st is not None:
            # Whose the answer is, in the item; whether it still stands, as
            # a warning on every role -- that was learned later, and is true
            # however the citation leans on it.
            item["whose answer"] = standing_words(st)
            if st["is"] in GONE:
                why.append(f"its answer was {standing_words(st)}")
        why += [f"learned later about it ({n['created_at'][:10]}): "
                f"{_one_line(n['text'], 96)}"
                for n in self.db.execute(
                    "SELECT text, created_at FROM postscripts WHERE question_id=?"
                    " ORDER BY id", (q["id"],))]
        if why:
            item["READ IT AGAIN"] = why
        return item

    def _warned_citations(self, kind: str, node_id: int) -> list[str]:
        """One line each, for the views that are one line per node."""
        return [f"{c['cites']}: {c['READ IT AGAIN'][0]}"
                for c in self._citations_of(kind, node_id) if "READ IT AGAIN" in c
                ] + [f"{c['cites']}: not in this notebook"
                     for c in self._citations_of(kind, node_id)
                     if "READ IT YOURSELF" in c]

    def _label_of(self, attempt_id: Optional[int]) -> Optional[str]:
        if attempt_id is None:
            return None
        r = self.db.execute("SELECT seq, qual FROM attempts WHERE id=?",
                            (attempt_id,)).fetchone()
        return _lab("A", r) if r else None

    def open(self, project: str, labels: Iterable[str]) -> dict:
        """Full bodies for named nodes. Nothing is truncated here."""
        p = self._project_row(project)
        out: list[dict] = []
        for label in labels:
            label = label.strip()
            if not label:
                continue
            if label[:1].upper() == "D":
                d = self._defect_by_label(label)
                out.append({**self._defect_row(d), **self._numbered_alike("D", d),
                            **self._legend_of("defects", d)})
            elif label[:1].upper() == "R":
                # Decided ones leave every list but note_defects(closed=True),
                # and a decision that later got a note is exactly the one
                # somebody comes back to by name.
                r = self._request_by_label(label)
                out.append({**self._request_row(r), **self._numbered_alike("R", r),
                            **self._legend_of("requests", r)})
            elif label[:1].upper() == "Q":
                q = self._question_by_label(p["id"], label)
                kids = self.db.execute(
                    "SELECT seq, qual, hypothesis, verdict FROM attempts WHERE question_id=?"
                    " ORDER BY seq", (q["id"],)).fetchall()
                st = self._answer_standing(q["id"])
                out.append({
                    "question": f"{_lab('Q', q)}", "text": q["text"], "status": q["status"],
                    # Before the answer, so it is read first. A correction
                    # printed after the body was printed after the claim.
                    **({"the answer is": standing_sentence(st)} if st else {}),
                    "answer": q["answer"], "created_at": q["created_at"],
                    "learned later": self._postscripts(q["id"]) or None,
                    "supersedes": self._q_label(q["supersedes"]),
                    "superseded_by": self._q_label(q["superseded_by"]),
                    "in service of": [self._q_line(a) for a in self._ancestors(q)] or None,
                    "opened under it": [self._q_line(c)
                                        for c in self._children(q["id"])] or None,
                    "the answer rests on": self._citations_of("Q", q["id"]) or None,
                    "attempts": [f"{_lab('A', k)}  {k['verdict'] or 'OPEN'}  {k['hypothesis']}"
                                 for k in kids],
                    **self._legend_of("questions", q),
                })
            else:
                a = self._attempt_by_label(p["id"], label)
                q = self.db.execute("SELECT seq, qual, text FROM questions WHERE id=?",
                                    (a["question_id"],)).fetchone()
                readings = self._readings_in(a["id"])
                out.append({
                    "attempt": f"{_lab('A', a)}",
                    "under": f"{_lab('Q', q)}  {_one_line(q['text'], 96)}",
                    "hypothesis": a["hypothesis"],
                    "prompted_by": self._label_of(a["prompted_by"]),
                    "why_now (INTERPRETATION, n=1)": a["why_now"],
                    "measure": a["measure"],
                    "falsifier (written before)": a["falsifier"],
                    "apparatus (written before)": a["apparatus"],
                    "result (MEASURED)": a["result"],
                    "verdict": a["verdict"] or "OPEN",
                    "learned later": self._attempt_notes(a["id"]) or None,
                    "the result rests on": self._citations_of("A", a["id"]) or None,
                    **({"a reading in it was false": readings} if readings else {}),
                    **self._code_state_of_attempt(a),
                    "created_at": a["created_at"], "closed_at": a["closed_at"],
                    "prompted_these": [
                        f"{_lab('A', r)}  {r['hypothesis']}" for r in self.db.execute(
                            "SELECT seq, qual, hypothesis FROM attempts WHERE prompted_by=?"
                            " ORDER BY seq", (a["id"],))],
                    **self._legend_of("attempts", a),
                })
        return {"project": project, "nodes": out}

    #: Where each kind of node keeps what was learned about it later.
    _NOTES = {"questions": ("postscripts", "question_id"),
              "attempts": ("attempt_notes", "attempt_id"),
              "requests": ("request_notes", "request_id"),
              "defects": ("defect_notes", "defect_id")}

    def _legend_of(self, tbl: str, row: sqlite3.Row) -> dict:
        """The legend for one node and every note under it, keyed for a body."""
        notes, key = self._NOTES[tbl]
        parts = [(tbl, row, "")] + [
            (notes, n, f"note of {n['created_at'][:10]}")
            for n in self.db.execute(f"SELECT * FROM {notes} WHERE {key}=? ORDER BY id",
                                     (row["id"],)).fetchall()]
        legend = self._legend(parts)
        return {"labels in text from another notebook": legend} if legend else {}

    def _numbered_alike(self, kind: str, row: sqlite3.Row) -> dict:
        """For a request or defect body: the other records here with its
        number, and which one a bare label names. A reader who followed a
        bare label out of carried text lands on this notebook's record, and
        this is what tells them it may not be the one the text meant."""
        others = self._same_number(kind, row)
        if not others:
            return {}
        bare = f"{kind}{row['seq']}"
        if self._rd_label(kind, row) == bare:
            note = (f"this is the {bare} a bare label names here. In text carried "
                    f"from another notebook a bare {bare} named that notebook's own "
                    f"record -- one of these -- and note_open on that text says "
                    f"which")
        else:
            note = (f"this one arrived from another notebook, where it is {bare}. "
                    f"Here a bare {bare} names an earlier record, below; in text "
                    f"written in that notebook, a bare {bare} means this one")
        return {f"also numbered {bare} here": {"read this": note, "records": others}}

    def _code_state_of_attempt(self, a: sqlite3.Row) -> dict:
        """What code this was predicted from, and what code the number came
        out of. Two different commits is the finding, not a footnote."""
        out: dict = {}
        for phase, commit, dirty, untracked in (
                ("pre-registered against", a["open_commit"], a["open_dirty"],
                 a["open_untracked"]),
                ("measured against", a["close_commit"], a["close_dirty"],
                 a["close_untracked"])):
            if not commit:
                continue
            note = " (tracked files differed -- not reproducible)" if dirty else ""
            if untracked:
                note += f" (untracked: {untracked})"
            out[phase] = f"{commit[:12]}{note}"
        if (a["open_commit"] and a["close_commit"]
                and a["open_commit"] != a["close_commit"]):
            out["THE CODE MOVED UNDER THIS MEASUREMENT"] = (
                "the number is not about the code the prediction was made from")
        return out

    def _q_label(self, qid: Optional[int]) -> Optional[str]:
        if qid is None:
            return None
        r = self.db.execute("SELECT seq, qual FROM questions WHERE id=?",
                            (qid,)).fetchone()
        return _lab("Q", r) if r else None

    def _q_text(self, qid: int) -> str:
        return self.db.execute("SELECT text FROM questions WHERE id=?",
                               (qid,)).fetchone()["text"]

    def _q_line(self, q: sqlite3.Row) -> str:
        """One question, one line, the way every view here shows a node --
        with where its answer stands, since this is the line a reader of the
        questions above and below it gets instead of the answer."""
        state = self._q_state(q)
        return (f"{_lab('Q', q)}  {q['headline'] or _one_line(q['text'], LINE)}"
                + (f"  [{state}]" if state else ""))

    def _q_state(self, q: sqlite3.Row) -> Optional[str]:
        return question_state(q["status"], self._q_label(q["superseded_by"]),
                              self._answer_standing(q["id"]))

    def _children(self, question_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM questions WHERE parent=? ORDER BY seq",
            (question_id,)).fetchall()

    def _ancestors(self, q: sqlite3.Row) -> list[sqlite3.Row]:
        """Root first. What this question is in service of."""
        chain, seen = [], {q["id"]}
        cur = q
        while cur["parent"] is not None and cur["parent"] not in seen:
            seen.add(cur["parent"])
            cur = self.db.execute("SELECT * FROM questions WHERE id=?",
                                  (cur["parent"],)).fetchone()
            if cur is None:
                break
            chain.append(cur)
        return list(reversed(chain))

    def _below(self, question_id: int) -> list[sqlite3.Row]:
        """Every question under this one, at any depth."""
        return self.db.execute(
            "WITH RECURSIVE below(id) AS ("
            "  SELECT id FROM questions WHERE parent=?"
            "  UNION ALL"
            "  SELECT q.id FROM questions q JOIN below b ON q.parent=b.id)"
            " SELECT q.* FROM questions q JOIN below ON below.id=q.id"
            " ORDER BY q.seq", (question_id,)).fetchall()

    def _open_below(self, question_id: int) -> list[sqlite3.Row]:
        """Every open question under this one, at any depth.

        Depth matters: an open grandchild means the subtree is not settled,
        and an answer written over it is a summary of half the argument --
        the same thing an open attempt means, one level up.
        """
        return self.db.execute(
            "WITH RECURSIVE below(id) AS ("
            "  SELECT id FROM questions WHERE parent=?"
            "  UNION ALL"
            "  SELECT q.id FROM questions q JOIN below b ON q.parent=b.id)"
            " SELECT q.* FROM questions q JOIN below ON below.id=q.id"
            " WHERE q.status='open' ORDER BY q.seq", (question_id,)).fetchall()


#: `TypeError: ...`, `error: ...`, `AssertionError` -- what a reader scans for.
_RAISED = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Warning)\b|^\w*error\b",
                     re.IGNORECASE)


#: How wide one line is, everywhere a node is shown as one.
LINE = 96


# --------------------------------------------------------------------------
# where an answer stands, said the same way in every view
# --------------------------------------------------------------------------

def standing_head(st: dict) -> str:
    """Who said what about an answer: 'REJECTED by the user, recorded
    2026-10-01'. The date is when it was written down here -- the note's,
    or for an answer endorsed as it was written, the answer's own. When the
    user said it is in their words, not in this date."""
    when = (st.get("when") or "")[:10]
    rec = f", recorded {when}" if when else ""
    return {"NOT_ENDORSED": "not endorsed by the user",
            "ENDORSED": f"endorsed by the user{rec}",
            "REJECTED": f"REJECTED by the user{rec}",
            "WITHDRAWN": f"WITHDRAWN{' on ' + when if when else ''}"}[st["is"]]


def standing_words(st: Optional[dict]) -> str:
    """Whose an answer is and whether it still stands, as one phrase."""
    if not st:
        return "no answer"
    return standing_head(st) + ("; it no longer stands" if st["is"] in GONE else "")


def standing_sentence(st: dict) -> str:
    """The same, for a body: with the user's words, and what to do about it."""
    said = f", in their words: {st['user_said']}" if st.get("user_said") else ""
    return {
        "NOT_ENDORSED": (
            "not endorsed by the user -- an agent's answer. Nothing here records "
            "the user accepting it as theirs; note_postscript(answer_is='ENDORSED', "
            "user_said=<their words>) does, once they have."),
        "ENDORSED": f"{standing_head(st)}{said}",
        "REJECTED": (f"{standing_head(st)}{said}. It no longer stands: what "
                     f"follows is what was written then; do not cite it as theirs."),
        "WITHDRAWN": (f"{standing_head(st)}: it no longer stands -- 'learned "
                      f"later' says why. What follows is what was written then."),
    }[st["is"]]


def question_state(status: str, superseded_by: Optional[str],
                   st: Optional[dict]) -> Optional[str]:
    """What a one-line view puts in brackets after a question. Nothing for
    an open one. An answered one says whose its answer is: "[answered]"
    alone read as a settled claim, and the one that did was an agent's."""
    if status == "open":
        return None
    if status == "answered" and st is not None:
        out = "answered, " + {"NOT_ENDORSED": "not endorsed by the user",
                              "ENDORSED": "endorsed by the user",
                              "REJECTED": "then REJECTED by the user",
                              "WITHDRAWN": "then WITHDRAWN"}[st["is"]]
        # Answered and then replaced: the measurements stay valid and stop
        # meaning what they were taken to mean. "[answered]" alone hid it.
        return out + (f", then replaced by {superseded_by}" if superseded_by else "")
    if superseded_by:
        return f"became {superseded_by}"
    return status


def shown_line(text: str, first_line_only: bool = False) -> str:
    """The text a one-line view would have to work with."""
    body = (text or "").strip()
    if first_line_only:
        body = (body.splitlines() or [""])[0]
    return " ".join(body.split())


def headline_for(headline: Optional[str], text: str, what: str,
                 first_line_only: bool = False) -> Optional[str]:
    """Check a written headline, and require one where the body is too long
    to show without cutting it.

    Only there. A one-sentence question is already its own line, and asking
    for a second copy of it would be a field that gets filled with the same
    words -- which is how `why_now` came to hold paragraphs explaining that
    it did not apply.
    """
    line = (headline or "").strip()
    if line:
        if "\n" in line:
            raise NoteError(f"the {what} headline is one line, not several.")
        if len(line) > LINE:
            raise NoteError(
                f"the {what} headline is {len(line)} characters; {LINE} is the "
                f"width every view shows a node at. Say the one thing it is.")
        return line
    if len(shown_line(text, first_line_only)) <= LINE:
        return None
    raise NoteError(
        f"this {what} is {len(shown_line(text, first_line_only))} characters, and "
        f"every view but note_open shows a node as ONE line. Without a headline "
        f"that line is this text with a machine's cut in it -- a summary nobody "
        f"wrote, which came out as '[R1]' the day a question had no spaces in it.\n"
        f"  headline = what this {what} says, in one line of at most {LINE} "
        f"characters.\nThe body is kept exactly as written and note_open gives it "
        f"whole.")


def clip(text: str, width: int) -> str:
    """`width` characters, cut at a word boundary when there is one near it.

    Backing up to the last space assumed the text has spaces near the cut. A
    Japanese line has none: the only space in "[R1] 設計に要る構造（…" is after
    the tag, so a 97-character question came back as "[R1]..." -- a tree of
    them, each one showing only its label, in the view whose whole job is
    letting somebody read the tree. A boundary that far back is not a
    boundary; the cut is taken at `width` instead.
    """
    if len(text) <= width:
        return text
    cut = text[:width].rsplit(" ", 1)[0]
    return (cut if len(cut) >= width * 0.6 else text[:width]) + "..."


def _one_line(observed: str, width: int = 70) -> str:
    """The most informative single line of what came back.

    Taking the last line assumed a traceback. An agent pasted a prose account
    instead and the trunk showed a slice from the middle of a sentence, cut
    mid-word, that never said what had broken. So: the line that looks like a
    raise if there is one, otherwise the first line -- and never a broken word.
    """
    lines = [ln.strip() for ln in observed.splitlines() if ln.strip()]
    if not lines:
        return ""
    pick = next((ln for ln in reversed(lines) if _RAISED.match(ln)), lines[0])
    return clip(pick, width)


def _labels(attempts) -> str:
    return ", ".join(_lab("A", a) for a in attempts)


def _lab(kind: str, row) -> str:
    """A question's or attempt's label here: Q12, or Q12@k7m for one written
    in notebook k7m whose number a row here already held (see `qual`)."""
    return f"{kind}{row['seq']}" + (f"@{row['qual']}" if row["qual"] else "")


def _parse_qa(label: str, kind: str) -> tuple[int, str]:
    """'Q12' -> (12, ''); 'Q12@k7m' -> (12, 'k7m')."""
    m = re.fullmatch(rf"(?:{kind})?(\d+)(?:@([a-z0-9]+))?", str(label).strip(),
                     re.IGNORECASE)
    if not m:
        raise NoteError(f"expected a label like {kind}3, or {kind}3@k7m for one "
                        f"written in another notebook, got {label!r}")
    return int(m.group(1)), (m.group(2) or "").lower()


def _parse_rd(label: str, kind: str) -> tuple[int, Optional[str]]:
    """'R6' -> (6, None); 'R6@3fa2c1' -> (6, '3fa2c1')."""
    m = re.fullmatch(rf"(?:{kind})?(\d+)(?:@([0-9a-f]+))?", str(label).strip(),
                     re.IGNORECASE)
    if not m:
        raise NoteError(f"expected a label like {kind}3, or {kind}3@1a2b3c for a "
                        f"record carried from another notebook, got {label!r}")
    return int(m.group(1)), (m.group(2).lower() if m.group(2) else None)
