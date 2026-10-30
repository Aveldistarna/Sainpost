"""What happens when more than one agent has the notebook open.

The record is shared by every project on the machine, so "two writers" is
the normal case, not an exotic one. These tests cover the two ways that
breaks: a guard that reads before it locks, and a collision no tool is
obliged to look for.
"""

import threading
from pathlib import Path

import pytest

from sainpost.store import NoteError, Store


def pre(st, project, **kw):
    args = dict(hypothesis="via price is too high to escape to another layer",
                why_now="A0 showed order does not matter",
                measure="sweep via_cost_mm 0.1..8.0, count joined spans",
                falsifier="joined-span count does not move across the sweep",
                apparatus="stale=false checked; repair=False noted")
    args.update(kw)
    return st.hypothesis(project, **args)


def seeded(path, project, question="why do U2's four byte lanes jam"):
    st = Store(path)
    st.start_project(project, "")
    st.ask(project, question)
    return st


# -- the guard and the write it authorises must share one lock ------------

def run_together(db, n, work):
    """Run `work(store, i)` in n threads that start at the same instant.

    Each thread opens its OWN Store, because that is what a second agent is:
    another process with another connection to one file. sqlite3 refuses a
    connection across threads anyway, and that refusal is worth keeping --
    it is what stops this test from passing for the wrong reason.
    """
    gate = threading.Barrier(n)
    out, errs = [], []
    lock = threading.Lock()

    def go(i):
        st = Store(db)
        gate.wait()
        try:
            r = work(st, i)
        except Exception as e:                                 # noqa: BLE001
            with lock:
                errs.append(e)
        else:
            with lock:
                out.append(r)
        finally:
            st.close()

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return out, errs


def test_arms_opened_at_once_share_one_question_and_get_their_own_labels(tmp_path):
    """Two agents pre-registering arms of one question at the same instant
    both succeed -- that is the point of arms -- and each gets its own label."""
    db = tmp_path / "shared.db"
    seeded(db, "ddr").close()
    ok, errs = run_together(
        db, 2, lambda s, i: pre(s, "ddr", hypothesis=f"arm {i}: via price too high"))
    assert not errs, errs
    assert sorted(r["attempt"] for r in ok) == ["A1", "A2"]
    assert {r["under"][:2] for r in ok} == {"Q1"}


def test_two_agents_do_not_collide_on_the_next_label(tmp_path):
    """MAX(seq)+1 read outside the write lock hands both agents the same
    label, and UNIQUE(project_id, seq) then turns it into a stack trace."""
    db = tmp_path / "shared.db"
    seeded(db, "ddr").close()
    ok, errs = run_together(
        db, 4, lambda s, i: s.ask("ddr", f"is it the pad frontage, take {i}"))
    assert not errs, errs
    assert len({r["question"] for r in ok}) == 4


def test_a_refused_write_leaves_nothing_behind(tmp_path):
    """A refusal happens inside the transaction it would have written in."""
    db = tmp_path / "shared.db"
    s = seeded(db, "ddr")
    pre(s, "ddr")
    with pytest.raises(NoteError):
        pre(s, "ddr", hypothesis="something else entirely", prompted_by="A1")
    assert s.db.execute("SELECT COUNT(*) c FROM attempts").fetchone()["c"] == 1
    assert not s.db.in_transaction
    s.close()


# -- the collision channel -------------------------------------------------

def test_pre_registering_reports_what_another_agent_has_open_now(tmp_path):
    """Agents in different projects have nothing else that would tell them
    they overlap: the other attempt has no verdict, so already_tried cannot
    mention it."""
    s = seeded(tmp_path / "t.db", "ddr")
    pre(s, "ddr")
    s.start_project("hat", "another board, another agent")
    s.ask("hat", "why will these spans not route")
    got = pre(s, "hat")

    assert got["already_tried"] == [], "an unfinished attempt is not prior art"
    live = got["in_flight"]
    assert live and live[0]["project"] == "ddr" and live[0]["attempt"] == "A1"
    s.close()


def test_the_collision_arrives_with_the_other_falsifier_and_apparatus(tmp_path):
    """Whether a duplicate is a replication or waste is the caller's call,
    and it cannot make it without knowing what would kill the other attempt
    and what rig it is running on."""
    s = seeded(tmp_path / "t.db", "ddr")
    pre(s, "ddr", falsifier="joined-span count flat across the sweep",
        apparatus="kicad 10.0.1, repair=False")
    s.start_project("hat", "")
    s.ask("hat", "why will these spans not route")
    live = pre(s, "hat")["in_flight"][0]
    assert live["falsifier"] == "joined-span count flat across the sweep"
    assert live["apparatus"] == "kicad 10.0.1, repair=False"
    assert live["open_since"]
    s.close()


def test_a_collision_is_reported_and_never_refused(tmp_path):
    """Two rigs measuring one claim is a replication. Refusing it would make
    the record thinner, not safer."""
    s = seeded(tmp_path / "t.db", "ddr")
    pre(s, "ddr")
    s.start_project("hat", "")
    s.ask("hat", "why will these spans not route")
    got = pre(s, "hat")
    assert got["attempt"] == "A1" and got["in_flight"]
    s.close()


def test_your_own_open_attempt_is_not_reported_as_a_collision(tmp_path):
    """Listing it there would read as somebody else's work."""
    s = seeded(tmp_path / "t.db", "ddr")
    pre(s, "ddr")
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    got = pre(s, "ddr", hypothesis="via price is too high to escape upward")
    assert got["in_flight"] == []
    assert got["already_tried"], "the closed one is still prior art"
    s.close()


def test_an_arm_open_beside_yours_is_listed_as_an_arm_not_a_collision(tmp_path):
    """Same project, same question: it is the other half of your comparison,
    and it comes back whole whether or not it reads like yours."""
    s = seeded(tmp_path / "t.db", "ddr")
    pre(s, "ddr")
    got = pre(s, "ddr", hypothesis="the pad frontage is blocked, not the price")
    assert got["in_flight"] == []
    assert [a["attempt"] for a in got["open beside it, under the same question"]] == ["A1"]
    s.close()


def test_a_closed_attempt_stops_being_a_collision_and_becomes_prior_art(tmp_path):
    s = seeded(tmp_path / "t.db", "ddr")
    pre(s, "ddr")
    s.result("ddr", "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    s.start_project("hat", "")
    s.ask("hat", "why will these spans not route")
    got = pre(s, "hat")
    assert got["in_flight"] == []
    assert got["already_tried"][0]["verdict"] == "FALSIFIED"
    s.close()


# -- arriving at a notebook nobody has created yet -------------------------

WORKER = """
import sys, time
sys.path.insert(0, sys.argv[1])
db, go, i = sys.argv[2], float(sys.argv[3]), sys.argv[4]
while time.time() < go:                 # everybody opens on the same instant
    time.sleep(0.001)
from sainpost.store import Store
try:
    s = Store(db)
    s.start_project("p" + i, "arrived at the same moment as the others")
    s.close()
    print("ok")
except Exception as e:
    print(type(e).__name__ + ": " + str(e))
"""


def test_a_notebook_nobody_has_created_yet_survives_four_arrivals(tmp_path):
    """PRAGMA journal_mode = WAL is the one statement busy_timeout does not
    cover, and the first use of a shared notebook is when everyone hits it.

    SQLite will not run a busy handler for a journal-mode change -- waiting
    while holding what other writers are queued on is how a deadlock gets
    built -- so it answers SQLITE_BUSY immediately. The 30-second timeout set
    on the line above it therefore bought nothing here. Measured before the
    fix: three sessions calling note_start on a notebook that did not exist
    yet, one refused in ONE MILLISECOND with "database is locked", and
    through the server two of the three never answered at all -- still
    silent at 120 seconds, which is what "it froze" looks like from a
    session that has done nothing wrong.

    Separate PROCESSES, not threads: a second agent is another process with
    another connection, and the lock this test is about is held by the file,
    not by the interpreter.
    """
    import subprocess
    import sys
    import time

    root = str(Path(__file__).resolve().parents[1])
    worker = tmp_path / "arrive.py"
    worker.write_text(WORKER, encoding="utf-8")
    db = tmp_path / "fresh.db"

    go = time.time() + 2.0
    ps = [subprocess.Popen(
        [sys.executable, str(worker), root, str(db), str(go), str(i)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace") for i in range(4)]
    said = []
    for p in ps:
        try:
            said.append((p.communicate(timeout=60)[0] or "").strip())
        except subprocess.TimeoutExpired:
            p.kill()
            said.append("HUNG past 60s")

    assert said == ["ok"] * 4, "\n".join(said)
    st = Store(db)
    assert sorted(p["project"] for p in st.projects()) == ["p0", "p1", "p2", "p3"]
    st.close()
