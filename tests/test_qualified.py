"""Two notebooks writing one project, each numbering its own work.

Questions and attempts were numbered per project and the numbers were
unique, which made two records of one investigation impossible to join: both
had a Q1..Q19, and their text cites those numbers. A row is now its number
and what it was made with (`ident`), it carries the notebook that wrote it
(`origin`), and a number held twice prints the second holder after that
notebook's name: Q3@n02. Nothing is renumbered, on either side.
"""

import json
import sqlite3

import pytest

from sainpost import share
from sainpost.store import NoteError, Store


@pytest.fixture()
def two(tmp_path):
    win, lin = Store(tmp_path / "win.db"), Store(tmp_path / "lin.db")
    yield win, lin, tmp_path
    win.close()
    lin.close()


def carry(src, dst, path, project="ddr"):
    share.export_project(src, project, str(path))
    return share.import_file(dst, path)


def started(win, lin, tmp):
    """One project, made on win and carried to lin: the same card on both."""
    win.start_project("ddr", "escape routing under a 0.5mm BGA")
    win.ask("ddr", "why do the four byte lanes jam")
    win.hypothesis("ddr", hypothesis="via price is too high", why_now="",
                   measure="sweep", falsifier="count does not move", apparatus="a")
    win.result("ddr", "6/8 unchanged", "FALSIFIED")
    carry(win, lin, tmp / "ddr.json")


def test_a_notebook_is_named_once_and_keeps_its_name(tmp_path):
    st = Store(tmp_path / "t.db")
    name = st.name
    st.close()
    again = Store(tmp_path / "t.db")
    assert again.name == name, "the name is in labels agents copy into text"
    again.close()


def test_both_sides_adding_is_the_ordinary_case_now(two):
    """Both machines ask Q2 and open A2 without importing each other first.
    It used to be refused whole. Each keeps its own numbers bare, and the
    other's arrive after the name of the notebook that wrote them."""
    win, lin, tmp = two
    started(win, lin, tmp)
    win.ask("ddr", "is it the frontage")
    lin.ask("ddr", "is it the via stack")
    win.hypothesis("ddr", hypothesis="one via short", why_now="A1", prompted_by="A1",
                   measure="count", falsifier="2+", apparatus="a")
    lin.hypothesis("ddr", hypothesis="the stack is too tall", why_now="A1",
                   prompted_by="A1", measure="height", falsifier="fits", apparatus="a")

    share.export_project(lin, "ddr", str(tmp / "lin.json"))
    got = share.import_file(win, tmp / "lin.json")
    assert f"Q2@{lin.name}" in got["numbers already held here"]["labels"]
    assert f"A2@{lin.name}" in got["numbers already held here"]["labels"]

    share.export_project(win, "ddr", str(tmp / "win.json"))
    share.import_file(lin, tmp / "win.json")
    assert share.snapshot(win, "ddr") == share.snapshot(lin, "ddr"), \
        "one record on both machines, whatever each prints"

    mine = win.open("ddr", ["Q2", f"Q2@{lin.name}"])["nodes"]
    assert [n["text"] for n in mine] == ["is it the frontage", "is it the via stack"]
    theirs = lin.open("ddr", ["Q2", f"Q2@{win.name}"])["nodes"]
    assert [n["text"] for n in theirs] == ["is it the via stack", "is it the frontage"], \
        "symmetric: each notebook prints its own work bare"


def test_the_next_number_is_past_every_holder(two):
    win, lin, tmp = two
    started(win, lin, tmp)
    lin.ask("ddr", "asked on linux")
    carry(lin, win, tmp / "lin.json")
    assert win.ask("ddr", "asked on windows after that")["question"] == "Q3"


def test_a_bare_label_that_misses_says_what_holds_the_number(two):
    win, lin, tmp = two
    started(win, lin, tmp)
    win.ask("ddr", "here")
    lin.ask("ddr", "there")
    carry(lin, win, tmp / "lin.json")
    with pytest.raises(NoteError) as e:
        win.open("ddr", ["Q2@zzz"])
    assert f"Q2@{lin.name}" in str(e.value) and "Q2," in str(e.value)


def test_each_notebook_has_its_own_front(two):
    """Open under different questions on each machine: two fronts, one per
    notebook. The import used to refuse it as two fronts in one project."""
    win, lin, tmp = two
    started(win, lin, tmp)
    win.ask("ddr", "is it the frontage")
    win.hypothesis("ddr", hypothesis="one via short", why_now="A1", prompted_by="A1",
                   measure="count", falsifier="2+", apparatus="a")
    lin.ask("ddr", "is it the via stack")
    lin.hypothesis("ddr", hypothesis="the stack is too tall", why_now="A1",
                   prompted_by="A1", measure="height", falsifier="fits", apparatus="a")
    got = carry(lin, win, tmp / "lin.json")
    assert "REFUSED" not in json.dumps(got)
    t = win.trunk("ddr")
    assert t["question"] == "Q2" and [a["attempt"] for a in t["attempts"]] == ["A2"]
    assert any(f"A2@{lin.name}" in line and f"open on {lin.name}" in line
               for line in t["open_on_other_notebooks"])
    # And this notebook's front is still one question.
    win.ask("ddr", "a third")
    with pytest.raises(NoteError) as e:
        win.hypothesis("ddr", hypothesis="x", why_now="A1", prompted_by="A1",
                       measure="m", falsifier="f", apparatus="a", question="Q3")
    assert "open under Q2" in str(e.value)


def test_work_handed_over_is_closed_where_it_arrived(two):
    """Opened on one machine, closed on the other: nothing open here, so the
    one open there is the one this closes."""
    win, lin, tmp = two
    started(win, lin, tmp)
    win.hypothesis("ddr", hypothesis="one via short", why_now="A1", prompted_by="A1",
                   measure="count", falsifier="2+", apparatus="a")
    carry(win, lin, tmp / "ddr.json")
    assert lin.result("ddr", "2 vias", "CONFIRMED")["attempt"] == "A2"


def test_a_file_from_before_origins_still_imports(two, tmp_path):
    """/1 numbered every reference. It is read by upgrading it in memory,
    and what it cannot say -- which notebook wrote each row -- stays unknown
    until a /2 file of the same rows says it."""
    win, lin, tmp = two
    started(win, lin, tmp)
    fresh = Store(tmp_path / "fresh.db")
    v2 = share.snapshot(win, "ddr")
    q_seq = {q["ident"]: q["seq"] for q in v2["questions"]}
    a_seq = {a["ident"]: a["seq"] for a in v2["attempts"]}
    v1 = json.loads(json.dumps(v2))
    v1["format"] = "sainpost-project/1"
    v1["project"]["current_question"] = q_seq.get(v1["project"]["current_question"])
    for q in v1["questions"]:
        for k in ("supersedes", "superseded_by", "parent"):
            q[k] = q_seq.get(q[k])
        del q["ident"], q["origin"]
    for a in v1["attempts"]:
        a["question"] = q_seq[a["question"]]
        a["prompted_by"] = a_seq.get(a["prompted_by"])
        del a["ident"], a["origin"]
    (tmp / "v1.json").write_text(json.dumps(v1), encoding="utf-8")
    got = share.import_file(fresh, tmp / "v1.json")
    assert "1 questions" in got["added"]
    assert fresh.db.execute("SELECT origin FROM questions").fetchone()["origin"] is None

    share.export_project(win, "ddr", str(tmp / "v2.json"))
    got = share.import_file(fresh, tmp / "v2.json")
    assert "where written" in got
    assert fresh.db.execute("SELECT origin FROM questions").fetchone()["origin"] == win.name
    fresh.close()


def test_two_notebooks_that_drew_one_name_are_not_mixed(two, monkeypatch):
    win, lin, tmp = two
    started(win, lin, tmp)
    lin.ask("ddr", "asked on linux")
    win.ask("ddr", "asked on windows")
    lin.name = win.name                       # as if both had drawn it
    lin.db.execute("UPDATE questions SET origin=? WHERE seq=2", (win.name,))
    with pytest.raises(NoteError) as e:
        carry(lin, win, tmp / "lin.json")
    assert "Two notebooks drew the same name" in str(e.value)


def test_a_notebook_from_before_qualifiers_is_reshaped_once(tmp_path):
    """UNIQUE (project_id, seq) goes, every row keeps its number, and every
    row nothing carried in is marked as written here."""
    db = tmp_path / "old.db"
    st = Store(db)
    st.start_project("ddr", "")
    st.ask("ddr", "q")
    st.hypothesis("ddr", hypothesis="h", why_now="", measure="m", falsifier="f",
                  apparatus="a")
    st.close()
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = OFF")
    for t in ("questions", "attempts"):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")
                if r[1] not in ("id", "project_id", "seq", "ident", "origin", "qual")]
        c.execute(f"CREATE TABLE {t}_then (id INTEGER PRIMARY KEY,"
                  f" project_id INTEGER NOT NULL, seq INTEGER NOT NULL,"
                  f" {', '.join(cols)}, UNIQUE (project_id, seq))")
        c.execute(f"INSERT INTO {t}_then (id, project_id, seq, {', '.join(cols)})"
                  f" SELECT id, project_id, seq, {', '.join(cols)} FROM {t}")
        c.execute(f"DROP TABLE {t}")
        c.execute(f"ALTER TABLE {t}_then RENAME TO {t}")
    c.commit()
    c.close()

    st = Store(db)
    for t in ("questions", "attempts"):
        r = st.db.execute(f"SELECT * FROM {t}").fetchone()
        assert (r["seq"], r["qual"], r["origin"]) == (1, "", st.name)
        assert r["ident"]
    assert st.trunk("ddr")["question"] == "Q1"
    st.close()


# -- two projects that were one investigation --------------------------------

def split(win, lin, tmp):
    """The shape that was actually there: PcbRouter written on win, pcbrouter
    on lin, both numbered from Q1, and lin's carried to win."""
    win.start_project("PcbRouter", "the router, as measured on windows")
    win.ask("PcbRouter", "does the router finish the board")
    win.hypothesis("PcbRouter", hypothesis="it finishes", why_now="",
                   measure="unrouted", falsifier="any left", apparatus="a")
    win.result("PcbRouter", "3 left", "FALSIFIED")
    lin.start_project("pcbrouter", "the router, written up on linux")
    lin.ask("pcbrouter", "why do the lanes jam")
    lin.hypothesis("pcbrouter", hypothesis="via price", why_now="",
                   measure="sweep", falsifier="count does not move", apparatus="a")
    lin.result("pcbrouter", "6/8 unchanged", "FALSIFIED")
    lin.hypothesis("pcbrouter", hypothesis="the frontage is blocked",
                   why_now="A1 showed price does nothing", prompted_by="A1",
                   measure="count", falsifier="2+", apparatus="a")
    carry(lin, win, tmp / "pcbrouter.json", "pcbrouter")


def test_a_merge_moves_every_row_and_keeps_every_number(two):
    win, lin, tmp = two
    split(win, lin, tmp)
    got = win.merge("PcbRouter", "pcbrouter")
    assert "3 question(s) and attempt(s)" in got["moved"]
    assert [p["project"] for p in win.projects()] == ["PcbRouter"]
    assert win.projects()[0]["merged_from"] == ["pcbrouter"]
    nodes = win.open("PcbRouter", ["Q1", f"Q1@{lin.name}", "A2"])["nodes"]
    assert nodes[0]["text"] == "does the router finish the board", "written here: bare"
    assert nodes[1]["text"] == "why do the lanes jam"
    assert nodes[2]["hypothesis"] == "the frontage is blocked", "no A2 here: still bare"
    # The old name is read as the new one, by every tool.
    assert win.trunk("pcbrouter")["project"] == "pcbrouter"
    assert win.trunk("pcbrouter")["repo"] == win.trunk("PcbRouter")["repo"]


def test_moved_text_still_means_the_row_its_writer_meant(two):
    """lin wrote "A1 showed price does nothing" about its own A1. Here A1 is
    win's; the text is not rewritten, and note_open says what it meant."""
    win, lin, tmp = two
    split(win, lin, tmp)
    win.merge("PcbRouter", "pcbrouter")
    node = win.open("PcbRouter", ["A2"])["nodes"][0]
    legend = node["labels in text from another notebook"]
    assert legend["A1"].startswith(f"A1@{lin.name}  via price")
    assert "why_now" in legend["A1"]
    assert node["prompted_by"] == f"A1@{lin.name}", "the edge was never a number"


def test_the_merge_travels_and_each_side_prints_its_own_bare(two):
    win, lin, tmp = two
    split(win, lin, tmp)
    win.merge("PcbRouter", "pcbrouter")
    wrote = share.export_project(win, "PcbRouter", str(tmp / "PcbRouter.json"))
    assert wrote["file"].endswith("pcbrouter.json") and "written over" in wrote,         "over the merged half's file, not beside it under a case twin"
    got = share.import_file(lin, wrote["file"])
    assert got["merged"] == ["'pcbrouter' into 'PcbRouter', as the other notebook did"]
    assert [p["project"] for p in lin.projects()] == ["PcbRouter"]
    here, there = share.snapshot(lin, "PcbRouter"), share.snapshot(win, "PcbRouter")
    assert here["questions"] == there["questions"]
    assert here["attempts"] == there["attempts"]
    assert lin.open("PcbRouter", ["Q1"])["nodes"][0]["text"] == "why do the lanes jam"
    assert lin.open("PcbRouter", [f"Q1@{win.name}"])["nodes"][0]["text"] == \
        "does the router finish the board"


def test_a_file_under_the_old_name_lands_in_the_merged_project(two):
    """The other machine has not merged yet and goes on writing pcbrouter."""
    win, lin, tmp = two
    split(win, lin, tmp)
    win.merge("PcbRouter", "pcbrouter")
    lin.ask("pcbrouter", "asked on linux after the merge over there")
    got = carry(lin, win, tmp / "pcbrouter.json", "pcbrouter")
    assert got["project"] == "PcbRouter" and "1 questions" in got["added"]
    assert [p["project"] for p in win.projects()] == ["PcbRouter"]


def test_a_merged_name_is_not_exported_as_its_own_record(two):
    win, lin, tmp = two
    split(win, lin, tmp)
    win.merge("PcbRouter", "pcbrouter")
    with pytest.raises(NoteError) as e:
        share.export_project(win, "pcbrouter", str(tmp / "x.json"))
    assert "note_export('PcbRouter')" in str(e.value)


def test_rows_of_unknown_origin_are_not_merged(two, tmp_path):
    """Told apart by where they were written, which a row carried by a /1
    file does not say."""
    win, lin, tmp = two
    split(win, lin, tmp)
    win.db.execute("UPDATE questions SET origin=NULL WHERE qual='' AND"
                   " project_id=(SELECT id FROM projects WHERE name='pcbrouter')")
    with pytest.raises(NoteError) as e:
        win.merge("PcbRouter", "pcbrouter")
    assert "before files said which notebook wrote them" in str(e.value)


def test_two_projects_numbered_in_one_notebook_are_not_merged(tmp_path):
    st = Store(tmp_path / "one.db")
    for name in ("a", "b"):
        st.start_project(name, "")
        st.ask(name, f"the first question of {name}")
    with pytest.raises(NoteError) as e:
        st.merge("a", "b")
    assert "the same notebook" in str(e.value)
    st.close()


def test_the_merge_travels_to_a_notebook_that_carried_the_other_half_blind(two):
    """lin had imported win's PcbRouter from a /1 file: its rows there do not
    say where they were written. The file that carries the merge does, and
    the import learns it before merging."""
    win, lin, tmp = two
    split(win, lin, tmp)
    early = tmp / "early" / "PcbRouter.json"
    share.export_project(win, "PcbRouter", str(early))
    share.import_file(lin, early)
    lin.db.execute("UPDATE questions SET origin=NULL WHERE origin=?", (win.name,))
    lin.db.execute("UPDATE attempts SET origin=NULL WHERE origin=?", (win.name,))
    win.merge("PcbRouter", "pcbrouter")
    wrote = share.export_project(win, "PcbRouter", str(tmp / "PcbRouter.json"))
    got = share.import_file(lin, wrote["file"])
    assert got["merged"] and "where written" in got
    assert [p["project"] for p in lin.projects()] == ["PcbRouter"]
    assert share.snapshot(lin, "PcbRouter")["attempts"] == \
        share.snapshot(win, "PcbRouter")["attempts"]
