"""The notebook as a picture, for the people the agents work for.

What is under test is that the picture is the record: the same trail() and
open() the tools run, read through a connection that cannot write, and
carried into a page where no body can become markup.
"""

import http.client
import json
import re
import shutil
import sqlite3
import subprocess
import threading
from http.server import ThreadingHTTPServer

import pytest

from sainpost import view
from sainpost.store import NoteError, Store


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "t.db"
    st = Store(path)
    st.start_project("ddr", "escape routing")
    st.ask("ddr", "why do the four byte lanes jam")
    st.hypothesis("ddr", hypothesis="via price is too high", why_now="",
                  measure="sweep", falsifier="count does not move", apparatus="a")
    st.result("ddr", "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    st.ask("ddr", "does the pad frontage block the lanes", supersedes="Q1")
    st.ask("ddr", "which pads face the lanes", parent="Q2")
    st.hypothesis("ddr", hypothesis="the frontage is one via short",
                  why_now="A1 ruled out price", prompted_by="A1",
                  measure="count vias", falsifier="count is 2+", apparatus="b",
                  question="Q2")
    st.close()
    return path


def page_data(page: str) -> dict:
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                  page, re.S)
    return json.loads(m.group(1))


def test_the_reader_cannot_write(db):
    """A viewer left open beside two agents must not be a third writer."""
    before = db.read_bytes()
    ro = Store.read_only(db)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ro.ask("ddr", "a question nobody asked")
        assert ro.trail("ddr")["trail"][0]["question"] == "Q1"
    finally:
        ro.close()
    assert db.read_bytes() == before


def test_a_notebook_behind_the_schema_is_named_not_crashed_on(tmp_path):
    """The first real notebook read this way was behind, and the reader died
    with `IndexError: No item with that key` from deep inside trail()."""
    path = tmp_path / "old.db"
    Store(path).close()
    raw = sqlite3.connect(path)
    raw.execute("ALTER TABLE attempt_notes DROP COLUMN headline")
    raw.commit()
    raw.close()
    with pytest.raises(NoteError, match=r"attempt_notes\.headline.*Restart"):
        Store.read_only(path)


def test_no_notebook_is_a_refusal(tmp_path):
    with pytest.raises(NoteError, match="no notebook"):
        Store.read_only(tmp_path / "absent.db")


def test_the_snapshot_is_the_tree_with_every_body(db):
    snap = view.read(db)
    [p] = snap["projects"]
    assert p["now"] == "Q2"
    assert set(p["bodies"]) == {"Q1", "Q2", "Q3", "A1", "A2"}
    assert p["bodies"]["A2"]["prompted_by"] == "A1"
    assert p["bodies"]["A1"]["falsifier (written before)"] == "count does not move"
    by_label = {q["question"]: q for q in p["trail"]["trail"]}
    assert by_label["Q1"]["superseded_by"] == "Q2"
    assert by_label["Q3"]["under"] == "Q2"


def test_no_body_can_become_markup(tmp_path):
    """Bodies are pasted output. One that closes the data element would run
    as script in the page of everyone who opens the notebook."""
    path = tmp_path / "x.db"
    st = Store(path)
    st.start_project("p", "")
    evil = "</script><script>alert(1)</script><!--"
    st.ask("p", evil)
    st.close()
    page = view.render(view.read(path))
    assert "alert(1)</script>" not in page
    assert "<!--" not in page.split('type="application/json">', 1)[1].split("</script>")[0]
    assert page_data(page)["projects"][0]["bodies"]["Q1"]["text"] == evil


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to parse the page's script")
def test_the_page_script_parses(db, tmp_path):
    """Everything the page does is one inline script; a syntax error in it
    leaves a blank page and no message anywhere."""
    page = view.render(view.read(db))
    script = tmp_path / "page.js"
    script.write_text(re.findall(r"<script>(.*?)</script>", page, re.S)[0], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, r.stderr


def test_the_server_answers_only_when_asked_by_its_own_name(db):
    """The page is every project on the machine. A browser pointed at another
    site that resolves here sends that site's name, and gets nothing."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), view._Handler)
    view._Handler.notebook = db
    view._Handler.port = port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        def get(host):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            c.request("GET", "/", headers={"Host": host})
            r = c.getresponse()
            body = r.read().decode("utf-8")
            c.close()
            return r.status, body

        status, body = get(f"127.0.0.1:{port}")
        assert status == 200
        assert page_data(body)["live"] is True
        assert get(f"evil.example:{port}")[0] == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=10)
