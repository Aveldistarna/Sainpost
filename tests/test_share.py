"""One project, two machines, two notebooks, one file carried between them.

Every test here runs two Stores on two database files -- the Windows machine
and the Linux one -- because the thing under test is exactly what neither
notebook can see on its own: the other one's work.
"""

import json
import shutil
import subprocess

import pytest

from sainpost import share
from sainpost.store import NoteError, Store


@pytest.fixture()
def two(tmp_path):
    win, lin = Store(tmp_path / "win.db"), Store(tmp_path / "lin.db")
    yield win, lin, tmp_path
    win.close()
    lin.close()


def seed(st, project="ddr"):
    """A record with every kind of row in it, and one attempt still open."""
    st.start_project(project, "escape routing under a 0.5mm BGA")
    st.ask(project, "why do the four byte lanes jam")
    st.hypothesis(project, hypothesis="via price is too high", why_now="",
                  measure="sweep", falsifier="count does not move", apparatus="a")
    st.result(project, "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    st.answer(project, "not a cost problem: the count never moves with price")
    st.postscript(project, "Q1", "later: the corridor model was missing entirely")
    st.postscript(project, "A1", "the sweep ran on the stale board",
                  shown_by=None)
    st.ask(project, "does the pad frontage block the lanes", supersedes="Q1")
    st.hypothesis(project, hypothesis="the frontage is one via short",
                  why_now="A1 ruled out price", prompted_by="A1",
                  measure="count vias at the frontage", falsifier="count is 2+",
                  apparatus="kicad 10.0.1")
    return project


def carry(src, dst, path, project="ddr"):
    share.export_project(src, project, str(path))
    return share.import_file(dst, path)


def test_a_project_arrives_whole(two):
    win, lin, tmp = two
    seed(win)
    got = carry(win, lin, tmp / "ddr.json")
    assert "2 questions" in got["added"] and "2 attempts" in got["added"]
    assert share.snapshot(lin, "ddr") == share.snapshot(win, "ddr"), \
        "the record on the other machine is the same record, label for label"
    assert got["position"].startswith("Q2")
    assert "closed or settled since" not in got, \
        "rows that arrived closed are news once, as added -- not twice"
    assert lin._open_attempt(lin._project_row("ddr")["id"])["seq"] == 2, \
        "an open attempt is the handover, and it comes across open"


def test_labels_survive_because_other_records_cite_them(two):
    win, lin, tmp = two
    seed(win)
    carry(win, lin, tmp / "ddr.json")
    a2 = lin.open("ddr", ["A2"])["nodes"][0]
    assert a2["prompted_by"] == "A1" and "A1 ruled out price" in a2["why_now (INTERPRETATION, n=1)"]
    assert lin.open("ddr", ["Q2"])["nodes"][0]["supersedes"] == "Q1"


def test_a_question_tree_crosses_whole(two):
    win, lin, tmp = two
    seed(win)
    win.ask("ddr", "what does the claim require", parent="Q2")
    win.ask("ddr", "which material shows it", parent="Q3")
    carry(win, lin, tmp / "ddr.json")
    assert share.snapshot(lin, "ddr") == share.snapshot(win, "ddr")
    assert lin.open("ddr", ["Q4"])["nodes"][0]["in service of"][0].startswith("Q2")


def test_the_written_line_crosses_with_the_body(two):
    win, lin, tmp = two
    seed(win)
    win.result("ddr", "3 vias", "FALSIFIED")          # free the front first
    win.ask("ddr", "[R1] " + "設計に要る構造は観測に含まれるか。" * 6,
            headline="[R1] 設計の構造は観測に含まれるか")
    win.hypothesis("ddr", hypothesis="読める形で書かれているかで決まる。" * 8,
                   headline="決めるのは構造であって知覚ではない", why_now="A1 ruled out price",
                   prompted_by="A1", measure="m", falsifier="f", apparatus="a")
    win.result("ddr", "23件中20件。" + "内訳。" * 100, "CONFIRMED",
               headline="23件中20件を説明")
    carry(win, lin, tmp / "ddr.json")
    assert share.snapshot(lin, "ddr") == share.snapshot(win, "ddr")
    [row] = [r for r in lin.trail("ddr")["standing"] if r["attempt"] == "A3"]
    assert row["headline"] == "決めるのは構造であって知覚ではない"
    assert row["result"] == "23件中20件を説明"


def test_a_file_written_before_headlines_existed_still_imports(two):
    """Absent is not "no headline", and a row that arrives without one is
    cut to fit the way it always was."""
    win, lin, tmp = two
    seed(win)
    f = tmp / "ddr.json"
    share.export_project(win, "ddr", str(f))
    old = json.loads(f.read_text(encoding="utf-8"))
    for q in old["questions"]:
        q.pop("headline", None), q.pop("answer_headline", None)
    for a in old["attempts"]:
        a.pop("headline", None), a.pop("result_headline", None)
        for n in a["notes"]:
            n.pop("headline", None)
    f.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    got = share.import_file(lin, f)
    assert "REFUSED" not in str(got) and "2 questions" in got["added"]


def test_a_file_written_before_trees_existed_still_imports(two):
    """Absent is not "no parent". Read that way, every question in an older
    file disagrees with one that has since been placed in a tree here, and
    the whole import is refused over a field the file cannot speak to."""
    win, lin, tmp = two
    seed(win)
    f = tmp / "ddr.json"
    carry(win, lin, f)
    lin.ask("ddr", "a requirement, placed here", parent="Q2")
    win.ask("ddr", "a requirement, placed here")            # older machine: flat
    old = json.loads(f.read_text(encoding="utf-8"))
    # Nor where its rows were written: that came later still.
    old["questions"] = [{k: v for k, v in q.items() if k not in ("parent", "origin")}
                        for q in share.snapshot(win, "ddr")["questions"]]
    f.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    got = share.import_file(lin, f)
    assert "REFUSED" not in str(got)
    assert lin.open("ddr", ["Q3"])["nodes"][0]["in service of"][0].startswith("Q2"), \
        "what is placed here stays placed"


def test_what_a_result_rests_on_crosses_with_it(two):
    win, lin, tmp = two
    seed(win)
    win.start_project("adc", "the board")
    win.ask("adc", "how many nets are left unrouted")
    win.hypothesis("adc", hypothesis="the second pass leaves 113", why_now="",
                   measure="count", falsifier="not 113", apparatus="kicad")
    win.result("adc", "113 unrouted", "CONFIRMED")
    win.result("ddr", "3 vias at the frontage", "FALSIFIED", cites="adc/A1")

    share.export_project(win, "adc", str(tmp / "adc.json"))
    share.import_file(lin, tmp / "adc.json")
    carry(win, lin, tmp / "ddr.json")
    [rests] = lin.open("ddr", ["A2"])["nodes"][0]["the result rests on"]
    assert rests["cites"] == "adc/A1" and rests["verdict"] == "CONFIRMED"
    assert share.snapshot(lin, "ddr") == share.snapshot(win, "ddr")


def test_how_something_was_cited_crosses_with_it(two):
    """Dropped, every record-of-what-happened citation turns back into a
    warning on the other machine, and the notes that matter are buried
    there instead."""
    win, lin, tmp = two
    seed(win)
    win.start_project("adc", "the board")
    win.ask("adc", "how many nets are left unrouted")
    win.hypothesis("adc", hypothesis="the second pass leaves 113", why_now="",
                   measure="count", falsifier="not 113", apparatus="kicad")
    win.result("adc", "still 119", "FALSIFIED")
    win.result("ddr", "3 vias at the frontage", "FALSIFIED", cites="records:adc/A1")
    share.export_project(win, "adc", str(tmp / "adc.json"))
    share.import_file(lin, tmp / "adc.json")
    carry(win, lin, tmp / "ddr.json")
    [rests] = lin.open("ddr", ["A2"])["nodes"][0]["the result rests on"]
    assert rests["as"] == "records" and "READ IT AGAIN" not in rests


def test_a_citation_whose_record_is_not_here_is_carried_and_named(two):
    """The cited record travels in another file, which may not have arrived
    -- or the project may not be one this machine holds at all. Dropping the
    link would leave the text resting on something invisible; keeping it
    silent would let a reader think it had been checked."""
    win, lin, tmp = two
    seed(win)
    win.start_project("adc", "the board")
    win.ask("adc", "how many nets are left unrouted")
    win.hypothesis("adc", hypothesis="the second pass leaves 113", why_now="",
                   measure="count", falsifier="not 113", apparatus="kicad")
    win.result("adc", "113 unrouted", "CONFIRMED")
    win.result("ddr", "3 vias at the frontage", "FALSIFIED", cites="adc/A1")
    got = carry(win, lin, tmp / "ddr.json")            # adc never carried
    assert any("adc/A1" in n and "not in this notebook" in n
               for n in got["not carried"])
    [rests] = lin.open("ddr", ["A2"])["nodes"][0]["the result rests on"]
    assert rests["cites"] == "adc/A1" and "READ IT YOURSELF" in rests


def test_work_goes_back_and_forth(two):
    """The ordinary case: work here, export, import there, work, back."""
    win, lin, tmp = two
    f = tmp / "ddr.json"
    seed(win)
    carry(win, lin, f)
    lin.result("ddr", "3 vias at the frontage", "FALSIFIED")      # closes A2 there
    lin.hypothesis("ddr", hypothesis="the lanes cross under U2", why_now="A2",
                   prompted_by="A2", measure="m", falsifier="f", apparatus="a")
    got = carry(lin, win, f)
    assert "1 attempts" in got["added"]
    assert any(c.startswith("A2 FALSIFIED") for c in got["closed or settled since"])
    assert share.snapshot(win, "ddr") == share.snapshot(lin, "ddr")
    assert win._open_attempt(win._project_row("ddr")["id"])["seq"] == 3


def test_importing_twice_changes_nothing(two):
    win, lin, tmp = two
    seed(win)
    carry(win, lin, tmp / "ddr.json")
    again = share.import_file(lin, tmp / "ddr.json")
    assert "nothing new" in again["result"]


def test_both_sides_writing_without_importing_is_refused_whole(two):
    """Renumbering to fit would change what every sentence citing the
    label means. So nothing is written, and it says which labels."""
    win, lin, tmp = two
    f = tmp / "ddr.json"
    seed(win)
    carry(win, lin, f)
    win.result("ddr", "2 vias", "CONFIRMED")
    lin.result("ddr", "3 vias", "FALSIFIED")
    lin.ask("ddr", "a third question, asked only on linux")
    before = share.snapshot(lin, "ddr")
    share.export_project(win, "ddr", str(f))
    with pytest.raises(NoteError) as e:
        share.import_file(lin, f)
    assert "A2" in str(e.value) and "nothing was imported" in str(e.value)
    assert share.snapshot(lin, "ddr") == before


def test_a_different_project_with_the_same_name_is_not_merged(two):
    """The Linux machine already has a record of its own."""
    win, lin, tmp = two
    seed(win)
    lin.start_project("ddr", "something else entirely")
    lin.ask("ddr", "a question from a different investigation")
    with pytest.raises(NoteError) as e:
        carry(win, lin, tmp / "ddr.json")
    assert "Q1 is a different question on each side" in str(e.value)


def test_export_will_not_take_the_other_sides_work_out_of_transit(two):
    win, lin, tmp = two
    f = tmp / "ddr.json"
    seed(win)
    carry(win, lin, f)
    lin.result("ddr", "3 vias", "FALSIFIED")
    share.export_project(lin, "ddr", str(f))
    with pytest.raises(NoteError) as e:
        share.export_project(win, "ddr", str(f))
    assert "note_import it first" in str(e.value)
    share.import_file(win, f)
    share.export_project(win, "ddr", str(f))                        # now it may


def test_an_export_that_learned_nothing_is_no_diff(two):
    win, _, tmp = two
    seed(win)
    f = tmp / "ddr.json"
    share.export_project(win, "ddr", str(f))
    first = f.read_bytes()
    got = share.export_project(win, "ddr", str(f))
    assert "nothing" in got["wrote"] and f.read_bytes() == first
    assert b"\r\n" not in first, "LF on every platform, or git sees a change"


def test_the_file_is_utf8_whatever_the_console_is(two):
    win, lin, tmp = two
    win.start_project("日本語", "ベタの前に区画を描け")
    win.ask("日本語", "否定形の方が効くか — café")
    f = tmp / "x.json"
    share.export_project(win, "日本語", str(f))
    assert "否定形" in f.read_text(encoding="utf-8")
    share.import_file(lin, f)
    assert lin.trunk("日本語")["question"].startswith("Q1")


def test_an_open_attempt_is_warned_about_at_export(two):
    win, _, tmp = two
    seed(win)
    got = share.export_project(win, "ddr", str(tmp / "ddr.json"))
    assert "A2 is open" in got and "code moved" in got["A2 is open"]


def test_the_default_place_is_the_projects_own_repository(two):
    win, _, tmp = two
    repo = tmp / "router"
    repo.mkdir()
    win.start_project("ddr", "d", repo=str(repo))
    win.ask("ddr", "q")
    got = share.export_project(win, "ddr")
    assert got["file"] == str(repo / ".sainpost" / "ddr.json")


def test_no_repository_means_saying_where(two):
    win, _, _ = two
    win.start_project("ddr", "d")
    with pytest.raises(NoteError) as e:
        share.export_project(win, "ddr")
    assert "path=" in str(e.value)


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_a_new_project_takes_its_repository_from_where_the_file_is(two):
    """The other machine's path is not carried: it names nothing here."""
    win, lin, tmp = two
    there = tmp / "checkout"
    there.mkdir()
    subprocess.run(["git", "init", "-q", str(there)], check=True)
    seed(win)
    share.export_project(win, "ddr", str(there))
    share.import_path(lin, str(there))
    got = lin._project_row("ddr")["repo"]
    assert got and (there.resolve() == __import__("pathlib").Path(got).resolve())


def test_a_repository_root_imports_every_file_it_carries(two):
    win, lin, tmp = two
    seed(win, "ddr")
    seed(win, "pdn")
    share.export_project(win, "ddr", str(tmp))
    share.export_project(win, "pdn", str(tmp))
    got = share.import_path(lin, str(tmp))
    assert [r["project"] for r in got["imported"]] == ["ddr", "pdn"]


def test_a_request_travels_and_so_does_its_decision(two):
    win, lin, tmp = two
    f = tmp / "ddr.json"
    seed(win)
    win.request(project="ddr", owner="sainpost-itself", wanted="w",
                because="b")
    carry(win, lin, f)
    assert lin.open("ddr", ["R1"])["nodes"][0]["owner"] == "sainpost-itself"
    assert lin._project_row("sainpost-itself")["stub"] == 1
    win.decide("R1", "ACCEPTED", "worth doing")
    win.postscript("ddr", "R1", "later: it was half of it")
    got = carry(win, lin, f)
    body = lin.open("ddr", ["R1"])["nodes"][0]
    assert body["decision"] == "ACCEPTED"
    assert body["learned later"][0]["text"] == "later: it was half of it"
    assert any(c.startswith("R1 ACCEPTED") for c in got["closed or settled since"])


def test_a_number_held_here_does_not_keep_the_record_out(two):
    """R30. Each machine numbers its requests on its own, so the numbers
    collide as a matter of course: leaving the other machine's record behind
    was going to drop 42 of the 45 two files carried. It comes across under
    its own number, qualified by its hash, and the record that held the
    number here first keeps printing it bare."""
    win, lin, tmp = two
    seed(win)
    win.request(project="ddr", owner="tool", wanted="from windows", because="b")
    lin.start_project("other", "")
    lin.request(project="other", owner="tool", wanted="from linux", because="b")
    got = carry(win, lin, tmp / "ddr.json")
    assert "not carried" not in got
    assert "2 questions" in got["added"] and "1 requests" in got["added"]
    [label] = got["numbers already held here"]["labels"].split(", ")
    assert label.startswith("R1@") and len(label) == len("R1@") + 6
    assert lin.open("other", ["R1"])["nodes"][0]["wanted"] == "from linux", \
        "a bare label still names the record that was here first"
    assert lin.open("ddr", [label])["nodes"][0]["wanted"] == "from windows"
    assert lin.request(project="other", owner="tool", wanted="w", because="b"
                       )["request"] == "R2", "a new number is never one already taken"


def test_a_record_that_went_there_and_came_back_is_the_same_record(two):
    """Matched by its number and what it was made with, so the round trip
    adds nothing, and the notebook that filed it still prints it bare."""
    win, lin, tmp = two
    seed(win)
    win.request(project="ddr", owner="tool", wanted="from windows", because="b")
    lin.start_project("other", "")
    lin.request(project="other", owner="tool", wanted="from linux", because="b")
    f = tmp / "ddr.json"
    carry(win, lin, f)
    share.export_project(lin, "ddr", str(f))
    assert "nothing new" in share.import_file(win, f)["result"]
    assert win.open("ddr", ["R1"])["nodes"][0]["wanted"] == "from windows"
    assert share.snapshot(lin, "ddr")["requests"] == share.snapshot(win, "ddr")["requests"]


def test_a_qualified_label_is_taken_wherever_a_label_is(two):
    """Deciding, noting, asking and fixing a record carried in under a number
    held here. A hash that fits nothing is refused with what the number
    does name here."""
    win, lin, tmp = two
    seed(win)                                     # A2 open in ddr
    win.start_project("tool", "the tool")
    win.request(project="ddr", owner="tool", wanted="from windows", because="b")
    win.blocked(project="ddr", invocation="route()", observed="TypeError: x",
                needed="a route", owner="tool", stopped=True)
    lin.start_project("tool", "the tool")
    lin.start_project("other", "")
    lin.request(project="other", owner="tool", wanted="from linux", because="b")
    lin.blocked(project="other", invocation="x", observed="linux's own", needed="n",
                owner="tool")
    carry(win, lin, tmp / "ddr.json")
    r = lin._rd_label("R", next(x for x in lin._rd_rows("R", 1)
                                if x["wanted"] == "from windows"))
    d = lin._rd_label("D", next(x for x in lin._rd_rows("D", 1)
                                if x["observed"] == "TypeError: x"))
    assert r.startswith("R1@") and d.startswith("D1@")
    assert lin.decide(r, "ACCEPTED", "worth doing")["wanted"] == "from windows"
    assert lin.decide("R1", "DECLINED", "not here")["wanted"] == "from linux"
    assert lin.postscript("tool", r, "later: half of it")["on"] == r
    assert lin.query(d, "tool", "which board?")["defect"] == d
    assert lin.reply(d, "ddr", "the one in the file")["defect"] == d
    assert lin.fixed(d, "FIXED", cause="c", change="ch", verify="v",
                     invalidates="NOTHING")["defect"] == d
    assert lin.open("other", ["D1"])["nodes"][0]["observed"] == "linux's own"
    with pytest.raises(NoteError) as e:
        lin.open("ddr", ["R1@ffffff"])
    assert "R1 here is: R1, R1@" in str(e.value)


def test_a_defect_whose_measurement_is_not_here_says_where_it_is(two):
    win, lin, tmp = two
    seed(win)                                     # A2 open in ddr
    win.start_project("router", "the router")
    win.blocked(project="ddr", invocation="route()", observed="TypeError: x",
                needed="a route", owner="router", stopped=True)
    carry(win, lin, tmp / "router.json", project="router")
    body = lin.open("router", ["D1"])["nodes"][0]
    assert "ddr A2" in body["blocked"] and "not this one" in body["blocked"]
    win.fixed("D1", "FIXED", cause="c", change="ch", verify="v",
              invalidates="NOTHING")
    got = carry(win, lin, tmp / "router.json", project="router")
    assert lin.open("router", ["D1"])["nodes"][0]["resolution"] == "FIXED"
    assert "not carried" not in got


def test_a_false_reading_crosses_with_its_link(two):
    win, lin, tmp = two
    seed(win)                                     # A2 open in ddr
    win.start_project("router", "the router")
    win.blocked(project="ddr", invocation="route()",
                observed="a 0.1 mm step read as 138 deg", needed="a step",
                owner="router", stopped=False)
    f = tmp / "ddr.json"
    carry(win, lin, f)
    assert json.loads(f.read_text(encoding="utf-8"))["defects"][0]["reading_in"]
    assert lin.open("ddr", ["D1"])["nodes"][0]["a false reading in"].startswith("ddr A2")
    assert lin.open("ddr", ["A2"])["nodes"][0]["verdict"] == "OPEN"
    assert share.snapshot(lin, "ddr") == share.snapshot(win, "ddr")


def test_a_false_reading_whose_attempt_is_not_here_says_nothing_was_stopped(two):
    win, lin, tmp = two
    seed(win)
    win.start_project("router", "the router")
    win.blocked(project="ddr", invocation="route()", observed="138 deg",
                needed="a step", owner="router", stopped=False)
    carry(win, lin, tmp / "router.json", project="router")
    body = lin.open("router", ["D1"])["nodes"][0]
    assert "ddr A2" in body["blocked"] and "nothing was stopped" in body["blocked"]


def test_a_record_with_no_false_reading_exports_as_it_always_did(two):
    """The field is written only where there is one, so a file already
    committed in some repository does not change on its next export."""
    win, _, tmp = two
    seed(win)
    win.start_project("router", "the router")
    win.blocked(project="ddr", invocation="route()", observed="TypeError: x",
                needed="a route", owner="router", stopped=True)
    share.export_project(win, "ddr", str(tmp / "ddr.json"))
    d = json.loads((tmp / "ddr.json").read_text(encoding="utf-8"))["defects"][0]
    assert "reading_in" not in d


def test_something_that_is_not_a_notebook_file_is_refused(two):
    _, lin, tmp = two
    f = tmp / "x.json"
    f.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    with pytest.raises(NoteError) as e:
        share.import_file(lin, f)
    assert "not a notebook file" in str(e.value)


def test_a_dry_run_says_what_the_import_would_do_and_writes_nothing(two):
    """R13: the only way to learn what an import does used to be doing it."""
    win, lin, tmp = two
    f = tmp / "ddr.json"
    seed(win)
    share.export_project(win, "ddr", str(f))
    before = lin.db.execute("SELECT count(*) FROM projects").fetchone()[0]
    got = share.import_file(lin, f, dry_run=True)
    assert "nothing was written" in got["DRY RUN"]
    assert "2 questions" in got["would add"] and got["position"].startswith("Q2")
    assert lin._project_row("ddr", required=False) is None
    assert lin.db.execute("SELECT count(*) FROM projects").fetchone()[0] == before
    real = share.import_file(lin, f)
    assert real["added"] == got["would add"], "the dry run was the import, rolled back"


def test_a_dry_run_of_a_refused_import_is_refused_the_same_way(two):
    win, lin, tmp = two
    seed(win)
    lin.start_project("ddr", "something else entirely")
    lin.ask("ddr", "a question from a different investigation")
    share.export_project(win, "ddr", str(tmp / "ddr.json"))
    with pytest.raises(NoteError) as e:
        share.import_file(lin, tmp / "ddr.json", dry_run=True)
    assert "would be refused" in str(e.value) and "Q1" in str(e.value)


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_a_new_project_beside_one_with_the_same_repository_is_said(two):
    """PcbRouter arrived where pcbrouter already recorded the same checkout,
    and became a second project without a word."""
    win, lin, tmp = two
    repo = tmp / "PcbRouter"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    seed(win, "PcbRouter")
    lin.start_project("pcbrouter", "from git history", repo=str(repo))
    share.export_project(win, "PcbRouter", str(repo))
    got = share.import_path(lin, str(repo), dry_run=True)["would import"][0]
    beside = " ".join(got["would arrive beside"])
    assert "'pcbrouter'" in beside and "same repository" in beside \
        and "only in case" in beside
    got = share.import_path(lin, str(repo))["imported"][0]
    assert got["arrived beside"]
    again = share.import_path(lin, str(repo))["imported"][0]
    assert "arrived beside" not in again, "said when it arrives, not every time"


def test_a_bare_label_in_carried_text_names_the_record_its_writer_meant(two):
    """The file's Q3 says "R1: ..." about its own R1; here R1 is another
    request. The text is never rewritten -- in a circuit record R1 is also a
    resistor -- and a pad reference is not a label. What is shown beside the
    text is which record the bare label meant; the import says the same."""
    win, lin, tmp = two
    seed(win)
    win.request(project="ddr", owner="ddr", wanted="from windows", because="b")
    win.ask("ddr", "R1: the request above. Also R1.2 is a resistor pad.")
    lin.start_project("other", "")
    lin.request(project="other", owner="tool", wanted="from linux", because="b")
    share.export_project(win, "ddr", str(tmp / "ddr.json"))
    got = share.import_file(lin, tmp / "ddr.json", dry_run=True)
    cites = got["carried text whose bare labels are other records here"]
    assert cites["R1"]["means here"].startswith("R1@")
    assert "from windows" in cites["R1"]["means here"]
    assert "from linux" in cites["R1"]["bare here"]
    [place] = cites["R1"]["named in"]
    assert place.startswith("Q3 text: ...R1: the request above.")
    assert "more here" not in place, "R1.2 is a pad, not a second citation"

    share.import_file(lin, tmp / "ddr.json")
    q3 = lin.open("ddr", ["Q3"])["nodes"][0]
    assert q3["text"] == "R1: the request above. Also R1.2 is a resistor pad.", \
        "the passage arrives as written"
    meant = q3["labels in text from another notebook"]["R1"]
    assert meant.startswith("R1@") and "from windows" in meant and "(in: text)" in meant
    mine = lin.open("other", ["R1"])["nodes"][0]
    assert mine["wanted"] == "from linux"
    [twin] = mine["also numbered R1 here"]["records"]
    assert "from windows" in twin and "carried from another notebook" in twin, \
        "following the bare label out of carried text lands here, and this says so"
    lin.ask("other", "R1 again, written here")
    assert "labels in text from another notebook" not in lin.open(
        "other", ["Q1"])["nodes"][0], "a bare label written here means this notebook's"


def test_a_label_cited_across_two_files_is_found_whichever_arrived_first(tmp_path):
    """Trace-from-photos' D4 and R19 cite its R16, which only cadbridge's
    file carries. Worked out as each file arrived, the answer would depend on
    which file was read first. It is worked out where the text is read, and
    the import that brought the record is the one that says so."""
    for first, second in (("curve", "tool"), ("tool", "curve")):
        win = Store(tmp_path / f"win-{first}.db")
        lin = Store(tmp_path / f"lin-{first}.db")
        win.start_project("curve", "images")
        win.start_project("tool", "the tool")
        win.request(project="tool", owner="tool", wanted="read sections from json",
                    because="b")                                   # only tool.json
        win.request(project="curve", owner="tool", wanted="as R1 says, for rails",
                    because="b")                                   # in both files
        lin.start_project("mine", "")
        for w in ("mine one", "mine two"):
            lin.request(project="mine", owner="mine", wanted=w, because="b")
        d = tmp_path / first
        share.export_project(win, "curve", str(d / "curve.json"))
        share.export_project(win, "tool", str(d / "tool.json"))
        share.import_file(lin, d / f"{first}.json")
        got = share.import_file(lin, d / f"{second}.json")
        r2 = next(x for x in lin._rd_rows("R", 2) if "rails" in x["wanted"])
        body = lin.open("curve", [lin._rd_label("R", r2)])["nodes"][0]
        assert "read sections from json" in \
            body["labels in text from another notebook"]["R1"], first
        if first == "curve":
            [place] = got["carried text whose bare labels are other records here"
                          ]["R1"]["named in"]
            assert "(carried by an earlier import)" in place
        win.close()
        lin.close()


def test_rename_reads_a_blank_card_as_the_project_here(two):
    """R30 (2). The other machine named its owner 'tool' and so made it a
    blank card there; here the project is 'Tool'. Matched by exact name
    only, its requests went to a second project with no work in it. The
    name is recorded, because the other machine goes on writing it."""
    win, lin, tmp = two
    win.start_project("curve", "images")
    win.request(project="curve", owner="tool", wanted="a camera", because="b")
    lin.start_project("Tool", "the tool, as this machine knows it")
    lin.ask("Tool", "does it hold")
    d = tmp / "repo"
    share.export_project(win, "curve", str(d))
    share.export_project(win, "tool", str(d))                     # the blank card
    got = share.import_path(lin, str(d), rename={"tool": "Tool"})["imported"]
    assert lin._project_row("tool", required=False) is None
    [r] = lin.defects("Tool")["requests"]
    assert (r["owner"], r["asked_by"]) == ("Tool", "curve")
    assert got[0]["read as"] == ["'tool' as 'Tool' -- recorded, so later imports "
                                 "read it the same way without being told"]
    assert "nothing new" in got[1]["result"]
    assert lin.trunk("Tool")["question"] == "Q1", "this notebook's card and work stay"

    win.request(project="curve", owner="tool", wanted="a second camera", because="b")
    share.export_project(win, "curve", str(d))
    again = share.import_file(lin, d / ".sainpost" / "curve.json")   # no rename=
    assert again["read as"] == ["'tool' as 'Tool' (recorded here earlier)"]
    assert lin._project_row("tool", required=False) is None
    assert len(lin.defects("Tool")["requests"]) == 2


def test_rename_is_refused_where_it_cannot_mean_what_it_says(two):
    win, lin, tmp = two
    win.start_project("curve", "images")
    win.request(project="curve", owner="tool", wanted="a camera", because="b")
    f = tmp / "curve.json"
    share.export_project(win, "curve", str(f))
    lin.start_project("Tool", "")
    lin.start_project("Other", "")
    with pytest.raises(NoteError) as e:
        share.import_file(lin, f, rename={"tol": "Tool"})
    assert "no record in" in str(e.value) and "'tool'" in str(e.value), \
        "a typo would otherwise do nothing, and the import would make the stub"
    share.import_file(lin, f, rename={"tool": "Tool"})
    with pytest.raises(NoteError) as e:
        share.import_file(lin, f, rename={"tool": "Other"})
    assert "already read as 'Tool'" in str(e.value)

    fresh = Store(tmp / "fresh.db")
    fresh.start_project("tool", "a project of this machine's own")
    with pytest.raises(NoteError) as e:
        share.import_file(fresh, f, rename={"tool": "Tool"})
    assert "already a project here" in str(e.value)
    fresh.close()


def test_rename_does_not_join_two_investigations(two):
    """What joins two projects is still what the import checks: a question
    that differs is refused at its label, named alike or not."""
    win, lin, tmp = two
    seed(win, "ddr")
    lin.start_project("DDR", "something else")
    lin.ask("DDR", "a different first question")
    share.export_project(win, "ddr", str(tmp / "ddr.json"))
    with pytest.raises(NoteError) as e:
        share.import_file(lin, tmp / "ddr.json", rename={"ddr": "DDR"})
    assert "Q1 is a different question on each side" in str(e.value)
    assert lin.db.execute("SELECT count(*) FROM aliases").fetchone()[0] == 0, \
        "a refused import records nothing, the name included"


def test_a_blank_card_named_only_in_case_is_said(two):
    """The file's own project was already said to arrive beside a case
    variant. A side of its requests was not, and it is the one that bit."""
    win, lin, tmp = two
    win.start_project("curve", "images")
    win.request(project="curve", owner="tool", wanted="a camera", because="b")
    lin.start_project("Tool", "")
    share.export_project(win, "curve", str(tmp / "curve.json"))
    said = " ".join(share.import_file(lin, tmp / "curve.json", dry_run=True
                                      )["would arrive beside"])
    assert "'tool'" in said and "'Tool'" in said and "rename={'tool': 'Tool'}" in said


def test_a_dry_run_of_several_files_is_what_importing_them_does(two):
    """Rolled back one file at a time, the second file was reported against a
    notebook the import never meets: whatever the first one added, the
    second was said to add again."""
    win, lin, tmp = two
    win.start_project("curve", "images")
    win.start_project("tool", "the tool")
    win.request(project="curve", owner="tool", wanted="a camera", because="b")
    d = tmp / "repo"
    share.export_project(win, "curve", str(d))
    share.export_project(win, "tool", str(d))
    dry = share.import_path(lin, str(d), dry_run=True)["would import"]
    assert "1 requests" in dry[0]["would add"]
    assert "requests" not in dry[1].get("would add", "")
    assert lin._project_row("curve", required=False) is None
    real = share.import_path(lin, str(d))["imported"]
    assert [r.get("added") for r in real] == [r.get("would add") for r in dry]


def test_a_re_filed_defect_names_the_one_it_supersedes_by_number_and_hash(two):
    """With two records under one number, the number alone does not say
    which was re-filed. The hash travels beside it -- only where there is
    one, so a record with no re-filing exports as it always did -- and the
    body names it by its label here. It printed the row's id."""
    win, lin, tmp = two
    seed(win)                                     # A2 open in ddr
    win.start_project("tool", "the tool")
    win.blocked(project="ddr", invocation="i", observed="first", needed="n",
                owner="tool", stopped=True)
    win.fixed("D1", "NOT_ACTIONABLE", cause="say which call")
    win.blocked(project="ddr", invocation="i2", observed="again", needed="n",
                owner="tool", supersedes="D1")
    f = tmp / "ddr.json"
    share.export_project(win, "ddr", str(f))
    first, again = json.loads(f.read_text(encoding="utf-8"))["defects"]
    assert "supersedes_ident" not in first
    assert again["supersedes"] == 1 and len(again["supersedes_ident"]) == 64
    lin.start_project("other", "")
    lin.blocked(project="other", invocation="x", observed="linux's own", needed="n",
                owner="tool")
    share.import_file(lin, f)
    assert lin.open("ddr", ["D2"])["nodes"][0]["supersedes"].startswith("D1@")


def test_an_export_beside_a_file_differing_only_in_case_is_refused(two):
    """Linux holds PcbRouter.json and pcbrouter.json side by side; a Windows
    checkout cannot, and one record is checked out over the other."""
    win, lin, tmp = two
    seed(win, "PcbRouter")
    seed(lin, "pcbrouter")
    share.export_project(win, "PcbRouter", str(tmp))
    with pytest.raises(NoteError) as e:
        share.export_project(lin, "pcbrouter", str(tmp))
    assert "only in case" in str(e.value)
    got = share.export_project(lin, "pcbrouter", str(tmp / ".sainpost" /
                                                    "pcbrouter-linux.json"))
    assert got["file"].endswith("pcbrouter-linux.json")


def test_one_projects_file_is_not_overwritten_by_anothers(two):
    win, _, tmp = two
    seed(win, "ddr")
    seed(win, "pdn")
    f = tmp / "same.json"
    share.export_project(win, "ddr", str(f))
    with pytest.raises(NoteError) as e:
        share.export_project(win, "pdn", str(f))
    assert "'ddr''s record, not 'pdn''s" in str(e.value)
