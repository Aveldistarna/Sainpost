"""The tool surface, exercised by calling the tools.

A pure-function suite and an import check both pass while the door is
broken; only calling the door proves the door. Everything here goes through
the functions the MCP client actually invokes, and one test walks the
registered tool list so a tool added later cannot skip the suite.
"""

import asyncio
import json

import pytest

from sainpost import server
from sainpost.store import Store


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("SAINPOST_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(server, "_STORE", None)
    yield server
    server._STORE = None


def seed(t):
    t.note_start("ddr", "escape routing under a 0.5mm BGA")
    t.note_ask("ddr", "why do U2's four byte lanes jam")


def prereg(t, **kw):
    args = dict(project="ddr",
                hypothesis="via price is too high to escape to another layer",
                why_now="A0 showed the order does not matter",
                measure="sweep via_cost_mm 0.1..8.0, count joined spans",
                falsifier="the joined-span count does not move across the sweep",
                apparatus="server/info stale=false; running with repair=False")
    args.update(kw)
    return t.note_hypothesis(**args)


# -- refusals arrive as answers, not stack traces -------------------------

def test_a_refusal_comes_back_as_text_the_caller_can_act_on(tools):
    out = tools.note_trunk("nope")
    assert out.startswith("REFUSED:")
    assert "note_start" in out


def test_the_gate_refuses_over_the_tool_boundary_too(tools):
    seed(tools)
    out = prereg(tools, falsifier="")
    assert out.startswith("REFUSED:") and "falsifier" in out
    assert "IF THE HYPOTHESIS IS WRONG" in out


def test_a_number_cannot_be_recorded_against_nothing(tools):
    seed(tools)
    assert tools.note_result("ddr", "6/8", "FALSIFIED").startswith("REFUSED:")


# -- the search on the way in --------------------------------------------

def test_pre_registering_returns_prior_verdicts_from_other_projects(tools):
    seed(tools)
    prereg(tools)
    tools.note_result("ddr", "6/8 unchanged across 0.1..8.0; vias 12<->6", "FALSIFIED")
    tools.note_start("hat", "a different board")
    tools.note_ask("hat", "why will these spans not route")
    hits = json.loads(prereg(tools, project="hat"))["already_tried"]
    assert hits[0]["project"] == "ddr" and hits[0]["verdict"] == "FALSIFIED"


def test_search_spans_projects_by_default(tools):
    seed(tools)
    prereg(tools)
    tools.note_result("ddr", "6/8 unchanged", "FALSIFIED")
    found = json.loads(tools.note_search("via cost too high"))["attempts"]
    assert found and found[0]["attempt"] == "A1"


# -- the trunk is what gets re-read --------------------------------------

def test_the_trunk_is_text_and_shows_the_commitment_while_open(tools):
    seed(tools)
    prereg(tools)
    out = tools.note_trunk("ddr")
    assert "QUESTION Q1" in out
    assert "A1   OPEN" in out
    assert "falsifier:" in out and "apparatus:" in out


def test_the_trunk_shows_the_path_and_the_reformulation(tools):
    seed(tools)
    prereg(tools)
    tools.note_result("ddr", "6/8 unchanged", "FALSIFIED")
    prereg(tools, hypothesis="the part is facing the wrong way", prompted_by="A1")
    tools.note_result("ddr", "270deg: 21->28/32 joined", "CONFIRMED")
    tools.note_ask("ddr", "the pad frontage is blocked, not the order", supersedes="Q1")
    out = tools.note_trunk("ddr", question="Q1")
    assert "A1   FALSIFIED" in out and "A2   CONFIRMED" in out
    assert "<-A1" in out                       # the edge is visible
    assert "-> 6/8 unchanged" in out           # the measurement is visible
    assert "[superseded]" in out
    assert "was    Q1" in tools.note_trunk("ddr")   # chain on the successor


def test_the_trunk_stays_one_line_per_closed_attempt(tools):
    """It is re-read at every checkpoint, so its size must not track the
    length of the investigation."""
    seed(tools)
    for i in range(12):
        prereg(tools, hypothesis=f"candidate cause number {i}")
        tools.note_result("ddr", f"measured {i}: no movement", "FALSIFIED")
    body = tools.note_trunk("ddr")
    assert len(body.splitlines()) < 32          # 12 attempts x 2 + header
    assert len(body) < 2000


def test_open_returns_the_full_body_for_named_nodes_only(tools):
    seed(tools)
    prereg(tools)
    tools.note_result("ddr", "6/8 unchanged", "FALSIFIED")
    node = json.loads(tools.note_open("ddr", "A1"))["nodes"][0]
    assert node["falsifier (written before)"].startswith("the joined-span")
    assert node["result (MEASURED)"] == "6/8 unchanged"
    assert "why_now (INTERPRETATION, n=1)" in node
    assert node["why_now (INTERPRETATION, n=1)"].startswith("A0 showed")


def test_open_wants_at_least_one_label(tools):
    seed(tools)
    assert tools.note_open("ddr", "  ,  ").startswith("REFUSED:")


def test_projects_names_the_position_of_each(tools):
    seed(tools)
    prereg(tools)
    rows = json.loads(tools.note_projects())
    assert rows[0]["current_question"].startswith("Q1")
    assert rows[0]["open_attempts"][0].startswith("A1")


# -- the guard on the surface itself --------------------------------------

def test_every_registered_tool_is_reachable_and_documented(tools):
    """A tool added later is covered by this without anyone remembering to
    extend a hand-written list -- hand-written lists go stale."""
    listed = asyncio.run(server.mcp.list_tools())
    assert len(listed) >= 9
    for t in listed:
        fn = getattr(server, t.name, None)
        assert callable(fn), f"{t.name} is registered but not importable"
        assert (t.description or "").strip(), f"{t.name} ships without a docstring"


def test_the_instructions_say_what_the_server_is_for_not_just_what_it_has():
    """A feature list gets correctly summarised as 'a notes database' and the
    reader stops there. The mechanism has to arrive in the same block."""
    text = server.mcp.instructions
    for phrase in ["falsifier", "append-only", "where you are", "prompted_by"]:
        assert phrase.lower() in text.lower()


def test_the_store_module_carries_no_mcp_import():
    """The record must stay readable and testable without the server."""
    import inspect

    from sainpost import store
    imports = [l.strip() for l in inspect.getsource(store).splitlines()
               if l.strip().startswith(("import ", "from "))]
    assert not [l for l in imports if "mcp" in l], imports


def test_nothing_shipped_lets_the_locale_choose_its_encoding():
    """The rule a Linux machine cannot feel, checked where Linux can see it.

    Text read or written without encoding= uses the console codepage, which
    is cp932 on a Japanese Windows. That ended the backup on the first
    accented word in the record, and turned gh's JSON into mojibake -- which
    the backup correctly reads as "cannot confirm the remote is private" and
    stops on. Both were found by hand. A third, rclone's stderr, was missed
    by the same hand and found by this, which is the argument for having it:
    the platform that suffers from a new one of these is never the platform
    it gets written on.

    subprocess is included because text=True is the same default wearing
    different clothes. Binary opens and an explicit ** of options are not
    guesses about the locale, so they pass.
    """
    import ast

    from pathlib import Path

    MODES = {"r", "w", "a", "x", "rb", "wb", "ab", "r+", "w+", "rt", "wt", "at"}
    root = Path(__file__).resolve().parents[1]
    shipped = [root / "backup.py", root / "launch.py",
               *sorted((root / "sainpost").glob("*.py"))]

    bad = []
    for f in shipped:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg for k in node.keywords}
            if "encoding" in kw or None in kw:      # given, or **-ed in
                continue
            attribute = isinstance(node.func, ast.Attribute)
            name = node.func.attr if attribute else getattr(node.func, "id", "")
            strings = [a.value for a in node.args
                       if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if name in ("read_text", "write_text"):
                pass
            elif name == "open" and (not attribute or set(strings) & MODES):
                if any("b" in m for m in strings if m in MODES):
                    continue
            elif name in ("run", "Popen", "check_output"):
                if not {"text", "universal_newlines"} & kw:
                    continue
            else:
                continue
            bad.append(f"{f.name}:{node.lineno} {name}()")

    assert not bad, ("these decide their encoding from the machine's locale:\n  "
                     + "\n  ".join(bad))


def test_the_db_path_is_overridable_and_shared_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SAINPOST_DB", raising=False)
    from sainpost.store import default_db_path
    assert default_db_path().name == "research.db"
    monkeypatch.setenv("SAINPOST_DB", str(tmp_path / "x.db"))
    assert default_db_path() == tmp_path / "x.db"


def test_no_child_is_handed_the_server_s_stdin_without_saying_so():
    """The bug this pins did not look like a bug in anything it touched.

    subprocess leaves stdin alone unless told otherwise, so a child gets the
    parent's. In the server the parent's stdin is the MCP pipe, opened by
    anyio in overlapped mode, and `git rev-parse --show-toplevel` -- which
    reads no input and returns in 0.02s from a plain process with a plain
    pipe -- inherited it and never returned. Caught with three of them
    minutes old and still running, each parented to a server that was never
    going to answer its client.

    What it cost to find: note_start(repo=...) hung from ONE client, and
    every test that called the store directly passed, because the store was
    not where it broke. The projects were even created first -- the write
    commits before the response is built -- so the record filled up with
    projects that had nothing under them, which is what the machine looked
    like when it was reported.

    So the rule is not "pass DEVNULL". It is that every child says what its
    stdin is, including the one in launch.py that genuinely inherits: that
    one IS the server, and it says stdin=None where a reader can see it.
    """
    import ast

    from pathlib import Path

    KINDS = ("run", "Popen", "call", "check_call", "check_output")
    root = Path(__file__).resolve().parents[1]
    shipped = [root / "backup.py", root / "launch.py",
               *sorted((root / "sainpost").glob("*.py"))]

    bad = []
    for f in shipped:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == "subprocess" and fn.attr in KINDS):
                continue
            kw = {k.arg for k in node.keywords}
            if None in kw or "stdin" in kw:
                continue
            bad.append(f"{f.name}:{node.lineno} subprocess.{fn.attr}()")

    assert not bad, ("these hand the child whatever stdin this process has, "
                     "without saying so:\n  " + "\n  ".join(bad))


def test_the_notebook_does_not_move_with_the_shell_that_started_it(monkeypatch):
    """The record is machine-wide -- that is the whole reason it lives outside
    any repository -- so its path cannot depend on which shell launched the
    server. XDG_DATA_HOME is exported by git-bash, msys and WSL interop, and
    honouring it on Windows would open a SECOND notebook, indistinguishable
    from inside: a complete record that is simply missing the other's work.
    """
    import os
    from pathlib import Path

    from sainpost.store import data_home

    monkeypatch.delenv("SAINPOST_DB", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/somewhere/a/shell/chose")
    if os.name == "nt":
        assert data_home() == Path(os.environ["LOCALAPPDATA"])
    else:
        assert data_home() == Path("/somewhere/a/shell/chose")


def test_the_record_is_plain_sqlite_anyone_can_read(tmp_path):
    """If this server is ever abandoned, the notebook must still open."""
    import sqlite3
    s = Store(tmp_path / "t.db")
    s.start_project("p"); s.ask("p", "q")
    s.hypothesis("p", "h", "w", "m", "f", "a")
    s.result("p", "r", "CONFIRMED")
    s.close()
    con = sqlite3.connect(tmp_path / "t.db")
    got = con.execute("SELECT hypothesis, falsifier, verdict FROM attempts").fetchone()
    assert got == ("h", "f", "CONFIRMED")


def test_a_refusal_always_names_what_to_do_instead(tools):
    """A refusal is the strongest teaching channel this server has: it lands
    at the moment of the mistake, about that mistake, and cannot be skimmed.
    That only holds while every one of them is actionable."""
    seed(tools)
    prereg(tools)
    refusals = [
        tools.note_hypothesis(project="ddr", hypothesis="an arm prompted by its "
                              "sibling", why_now="w", measure="m", falsifier="f",
                              apparatus="a", prompted_by="A1"),
        tools.note_hypothesis(project="ddr", hypothesis="h", why_now="w",
                              measure="", falsifier="", apparatus="a"),
        tools.note_result("ddr", "it crashed", "BLOCKED"),
        tools.note_result("ddr", "6/8", "MAYBE"),
        tools.note_answer("ddr", "it was the frontage"),
        tools.note_blocked(project="ddr", invocation="", observed="", needed="",
                           owner="ddr"),
        tools.note_blocked(project="ddr", invocation="i", observed="o", needed="n",
                           owner="ddr"),
        tools.note_start("ddr"),
        tools.note_trunk("nosuchproject"),
    ]
    tools.note_hypothesis(project="ddr", hypothesis="a second arm", why_now="w",
                          measure="m", falsifier="f", apparatus="a")
    refusals.append(tools.note_result("ddr", "6/8", "FALSIFIED"))
    for r in refusals:
        assert r.startswith("REFUSED: "), r
        body = r[len("REFUSED: "):]
        assert "note_" in body or any(
            w in body for w in ("falsifier", "apparatus", "measure", "verbatim",
                                "ABANDONED", "Known:", "must be one of")), body
