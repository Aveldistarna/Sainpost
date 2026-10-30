"""One number, possibly two records.

Requests and defects are numbered notebook-wide, and each machine's notebook
numbers its own. A record carried in from another machine keeps its number,
so here a row is its number and what it was made with (`ident`). These are
the guards on the notebooks that existed before that: every one of them had
`seq` UNIQUE, and the rebuild that lets go of it runs on every machine's
record the first time a session opens it.
"""

import json
import sqlite3
import threading

import pytest

from sainpost import share
from sainpost.store import SCHEMA, NoteError, Store, _statements, ident


def filled(db):
    """A notebook with every kind of request and defect row in it: open and
    decided, stopped and fixed, with notes on both."""
    st = Store(db)
    st.start_project("a", "")
    st.start_project("b", "")
    st.ask("a", "q")
    st.hypothesis("a", hypothesis="h", why_now="", measure="m", falsifier="f",
                  apparatus="ap")
    st.request(project="a", owner="b", wanted="open one", because="c")
    st.request(project="a", owner="b", wanted="decided one", because="c")
    st.decide("R2", "ACCEPTED", "yes")
    st.postscript("b", "R2", "later: half of it")
    st.blocked("a", invocation="i", observed="stopped one", needed="n", owner="b",
               stopped=True)
    st.fixed("D1", "NOT_A_DEFECT", cause="used wrongly")
    st.postscript("b", "D1", "later: it was the docs")
    st.close()


def as_it_was(db, also_without=()):
    """Requests and defects the way every notebook had them until now: `seq`
    UNIQUE, and no `ident` -- and without any other columns named."""
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = OFF")
    for t in ("requests", "defects"):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")
                if r[1] not in ("id", "seq", "ident", *also_without)]
        c.execute(f"CREATE TABLE {t}_then (id INTEGER PRIMARY KEY,"
                  f" seq INTEGER NOT NULL UNIQUE, {', '.join(cols)})")
        c.execute(f"INSERT INTO {t}_then (id, seq, {', '.join(cols)})"
                  f" SELECT id, seq, {', '.join(cols)} FROM {t}")
        c.execute(f"DROP TABLE {t}")
        c.execute(f"ALTER TABLE {t}_then RENAME TO {t}")
    c.commit()
    c.close()


def rows(db):
    c = sqlite3.connect(db)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY id").fetchall()
           for t in ("requests", "defects", "request_notes", "defect_notes")}
    c.close()
    return out


def test_the_schema_is_cut_where_sqlite_cuts_it():
    """The comments carry semicolons ("pasting what came back; a request
    has no output"). Cut on every ";", the reshape built requests from a
    piece that began mid-comment and failed on the first real notebook it
    met, with near "a": syntax error -- while every test passed, because
    none of them rebuilt requests."""
    stmts = _statements(SCHEMA)
    assert len(stmts) == SCHEMA.count("CREATE ")
    for st in stmts:
        code = [ln for ln in st.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        assert code[0].lstrip().startswith("CREATE "), code[0]
        assert sqlite3.complete_statement(st)


def test_an_older_notebook_lets_go_of_the_unique_number_and_keeps_every_row(tmp_path):
    db = tmp_path / "old.db"
    filled(db)
    as_it_was(db)
    before = rows(db)

    st = Store(db)
    after = rows(db)
    for t in ("request_notes", "defect_notes"):
        assert after[t] == before[t]
    for t in ("requests", "defects"):
        assert [r[0] for r in after[t]] == [r[0] for r in before[t]], "ids are kept"
    assert not st.db.execute("PRAGMA foreign_key_check").fetchall()
    for kind, table in (("R", "requests"), ("D", "defects")):
        for r in st.db.execute(f"SELECT * FROM {table}"):
            assert r["ident"] == ident(kind, r)
        uniq = [st.db.execute(f"PRAGMA index_info({i['name']})").fetchall()
                for i in st.db.execute(f"PRAGMA index_list({table})") if i["unique"]]
        assert not uniq, f"{table}.seq is still unique"
    assert {"requests_by_seq", "defects_by_seq"} <= {r[0] for r in st.db.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert st.open("a", ["R2"])["nodes"][0]["decision"] == "ACCEPTED"
    assert st.open("a", ["D1"])["nodes"][0]["learned later"][0]["text"] == \
        "later: it was the docs"
    st.postscript("a", "D1", "and the notes still take a row")     # defect_notes -> defects
    st.close()
    again = Store(db)
    assert again._needs_reshape() == [], "done once"
    again.close()


def test_a_note_table_stranded_by_the_old_rebuild_is_repaired(tmp_path):
    """The rebuild this replaced renamed defects out of the way BEFORE
    building the new one, and SQLite rewrites every REFERENCES to a renamed
    table: defect_notes came out pointing at "defects_was", dropped a moment
    later. Every note on a defect after that failed with "no such table"."""
    db = tmp_path / "old.db"
    filled(db)
    create = next(s for s in _statements(SCHEMA)
                  if "CREATE TABLE IF NOT EXISTS defects (" in s)
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = OFF")
    c.execute("ALTER TABLE defects RENAME TO defects_was")        # what it did
    c.execute(create)
    c.execute("INSERT INTO defects SELECT * FROM defects_was")
    c.execute("DROP TABLE defects_was")
    c.commit()
    stranded = c.execute("SELECT sql FROM sqlite_master WHERE name='defect_notes'"
                         ).fetchone()[0]
    c.close()
    assert "defects_was" in stranded, "the fault as it was"
    c = sqlite3.connect(db, isolation_level=None)
    try:
        c.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.OperationalError) as e:
            c.execute("INSERT INTO defect_notes (defect_id, written_by, text,"
                      " created_at) VALUES (1, 1, 't', 'now')")
        assert "defects_was" in str(e.value)
    finally:
        c.close()

    st = Store(db)
    assert "defects_was" not in st.db.execute(
        "SELECT sql FROM sqlite_master WHERE name='defect_notes'").fetchone()[0]
    st.postscript("a", "D1", "a note after the repair")
    assert len(st.open("a", ["D1"])["nodes"][0]["learned later"]) == 2
    st.close()


def test_a_reference_that_already_pointed_nowhere_does_not_stop_the_reshape(tmp_path):
    """Only what the rebuild itself breaks stops it. One orphan row already
    in a notebook would otherwise refuse every session that opened it, for a
    fault the reshape did not make and cannot repair."""
    db = tmp_path / "old.db"
    filled(db)
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = OFF")
    c.execute("INSERT INTO request_notes (request_id, written_by, text, created_at)"
              " VALUES (999, 1, 'a note on nothing', 'then')")
    c.commit()
    c.close()
    as_it_was(db)
    st = Store(db)
    assert "ident" in {r["name"] for r in st.db.execute("PRAGMA table_info(requests)")}
    orphan = st.db.execute("SELECT id FROM request_notes WHERE text='a note on nothing'"
                           ).fetchone()["id"]
    assert [tuple(r)[:2] for r in st.db.execute("PRAGMA foreign_key_check")] == \
        [("request_notes", orphan)], "the orphan is still there, and nothing else is"
    st.close()


def test_a_record_written_by_an_older_server_is_hashed_on_the_next_open(tmp_path):
    """A session started before this keeps running until it is restarted,
    and it inserts rows with no ident. They must read the same meanwhile and
    be filled in, once, on the next open."""
    db = tmp_path / "n.db"
    st = Store(db)
    st.start_project("a", "")
    st.db.execute("INSERT INTO requests (seq, asked_by, owner_id, wanted, because,"
                  " context, created_at) VALUES (1, 1, 1, 'old', 'b', 'c', 'now')")
    assert st.open("a", ["R1"])["nodes"][0]["request"] == "R1"
    assert st.request(project="a", owner="a", wanted="w", because="b")["request"] == "R2"
    st.close()
    again = Store(db)
    r = again._rd_by_label("R", "R1")
    assert r["ident"] == ident("R", r)
    again.close()


def test_an_older_server_asking_for_a_bare_label_gets_the_record_here_first(tmp_path):
    """Its lookup was "WHERE seq=?", first row. Through the (seq, id) index
    that is the record that held the number here first -- what a bare label
    names. Through an index on (seq, ident) it would be whichever hash sorts
    first, so the carried record here is given one that sorts below."""
    lin = Store(tmp_path / "lin.db")
    lin.start_project("other", "")
    lin.request(project="other", owner="other", wanted="from here", because="b")
    lin.blocked(project="other", invocation="i", observed="from here", needed="n",
                owner="other")
    there = Store(tmp_path / "there.db")
    there.start_project("p", "")
    there.request(project="p", owner="p", wanted="from there", because="b")
    there.blocked(project="p", invocation="i", observed="from there", needed="n",
                  owner="p")
    f = tmp_path / "p.json"
    share.export_project(there, "p", str(f))
    there.close()
    data = json.loads(f.read_text(encoding="utf-8"))
    for kind, rows, field in (("R", "requests", "wanted"), ("D", "defects", "observed")):
        mine = lin._rd_by_label(kind, f"{kind}1")["ident"]
        row = data[rows][0]
        n = 0
        while ident(kind, row) >= mine:
            n += 1
            row[field] = f"from there {n}"
    f.write_text(share.render(data), encoding="utf-8")
    share.import_file(lin, f)
    for table, field in (("requests", "wanted"), ("defects", "observed")):
        assert lin.db.execute(f"SELECT count(*) FROM {table} WHERE seq=1"
                              ).fetchone()[0] == 2
        first = lin.db.execute(f"SELECT * FROM {table} WHERE seq=?", (1,)).fetchone()
        assert first[field] == "from here"
    lin.close()


def test_what_identifies_a_record_leaves_its_sides_out():
    """An import may read the other notebook's name for a project as this
    notebook's own (rename=), and the row has to hash the same on both."""
    r = {"wanted": "w", "because": "b", "context": "c", "created_at": "t",
         "asked_by": "cadbridge", "owner": "cadbridge"}
    assert ident("R", r) == ident("R", {**r, "asked_by": "CadBridge", "owner": "x"})
    assert ident("R", r) != ident("R", {**r, "wanted": "w2"})
    d = {"invocation": "i", "observed": "o", "needed": "n", "seen_commit": None,
         "seen_dirty": None, "seen_untracked": None, "created_at": "t",
         "context": "rewritten by an import"}
    assert ident("D", d) == ident("D", {**d, "context": "somewhere else"})


def test_every_session_opening_an_older_notebook_at_once_comes_up(tmp_path):
    """After a reload every session on the machine opens the notebook in the
    same instant, and each one sees the old shape before any of them has
    rebuilt it. One rebuilds; the rest wait and find it done. (Whether two of
    them also read a column as missing before either adds it is up to the
    scheduler; the next test places that exactly.)"""
    db = tmp_path / "old.db"
    filled(db)
    as_it_was(db, also_without=("reading_in",))
    before = rows(db)
    go = threading.Barrier(4, timeout=30)
    errors, done = [], []

    def open_it():
        try:
            go.wait()
            st = Store(db)
            done.append(st.open("a", ["R1"])["nodes"][0]["wanted"])
            st.close()
        except Exception as e:            # noqa: BLE001 -- reported below
            errors.append(repr(e))

    ts = [threading.Thread(target=open_it) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=90)
    assert not any(t.is_alive() for t in ts), "a session never came up"
    assert not errors, errors
    assert done == ["open one"] * 4
    after = rows(db)
    assert [r[0] for r in after["requests"]] == [r[0] for r in before["requests"]]


def test_a_column_another_session_added_first_is_not_an_error(tmp_path, monkeypatch):
    """More than one session can read a column as missing before any of them
    adds it, and whichever writes second finds it there. With threads that
    race came out either way from one run to the next -- removing the guard
    passed once in two -- so here the other session's ALTER lands exactly
    between this one's read and its write."""
    db = tmp_path / "old.db"
    filled(db)
    as_it_was(db, also_without=("reading_in",))
    real = Store._add_column

    def the_other_session_first(self, table, column, decl):
        c = sqlite3.connect(db)
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        c.commit()
        c.close()
        return real(self, table, column, decl)

    monkeypatch.setattr(Store, "_add_column", the_other_session_first)
    st = Store(db)
    assert "reading_in" in {r["name"] for r in st.db.execute("PRAGMA table_info(defects)")}
    st.close()


def test_a_label_that_fits_two_records_is_refused_rather_than_guessed(tmp_path):
    st = Store(tmp_path / "n.db")
    st.start_project("a", "")
    st.request(project="a", owner="a", wanted="one", because="b")
    r = st._rd_by_label("R", "R1")
    seventh = "1" if r["ident"][6] == "0" else "0"          # the same six, then apart
    st.db.execute("INSERT INTO requests (seq, ident, asked_by, owner_id, wanted,"
                  " because, context, created_at) VALUES (1, ?, 1, 1, 'two', 'b',"
                  " 'c', 'then')", (r["ident"][:6] + seventh + "0" * 57,))
    with pytest.raises(NoteError) as e:
        st._rd_by_label("R", f"R1@{r['ident'][:6]}")
    assert "fits more than one" in str(e.value)
    assert st._rd_by_label("R", f"R1@{r['ident'][:7]}")["wanted"] == "one"
    st.close()
