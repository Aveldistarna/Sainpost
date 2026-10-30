"""What a decided request or a closed defect turned out to rest on.

The case that asked for this: a request was ACCEPTED with a reason that
quoted "16 of 89 near constraints affected". That afternoon the check behind
the number was fixed and it found 5 -- and two of the eleven that vanished
were refuted outright by copper the router had already laid on that board.
The correction existed, in a commit message and a CLAUDE.md. note_postscript
refused the R-label, so the request still said 16, as decided, to everyone
arriving through the notebook -- which is who the notebook is for.

The decision itself stands, the way a verdict does. It was made on what was
known then, and rewriting it would lose exactly that.
"""

import pytest

from sainpost.store import NoteError, Store


@pytest.fixture()
def s(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("pcbrouter", "the EDA work")
    st.ask("pcbrouter", "does the near check measure reachable paths")
    st.start_project("sainpost-itself", "the notebook")
    st.start_project("cadbridge", "somebody else entirely")
    st.request(project="sainpost-itself", owner="pcbrouter",
               wanted="measure near along a reachable path, not a straight line",
               because="R11 and R12 were both on this board")
    yield st
    st.close()


def decided(st):
    st.decide("R1", "ACCEPTED", "on the reported board 16 of 89 are affected")


def defect(st):
    st.blocked(project="pcbrouter", invocation="note_path('pcbrouter')",
               observed="65,177 bytes returned", needed="the whole path",
               owner="sainpost-itself")


def test_a_decided_request_takes_what_was_learned_later(s):
    decided(s)
    got = s.postscript("pcbrouter", "R1", "the entry edge was fixed to the "
                                          "nearest one; corrected, 16 became 5")
    assert got["on"] == "R1"
    assert "unchanged" in got["note"]
    body = s.open("pcbrouter", ["R1"])["nodes"][0]
    assert body["why"] == "on the reported board 16 of 89 are affected", \
        "the decision is what was believed then, and it stays that"
    later = body["learned later"]
    assert len(later) == 1 and "16 became 5" in later[0]["text"]
    assert later[0]["by"] == "pcbrouter" and later[0]["when"]


def test_it_appears_wherever_the_decision_does(s):
    decided(s)
    s.postscript("pcbrouter", "R1", "16 became 5")
    listed = s.defects(closed=True)["requests"][0]
    assert listed["learned later"][0]["text"] == "16 became 5"
    opened = s.open("cadbridge", ["R1"])["nodes"][0]
    assert opened["learned later"][0]["text"] == "16 became 5", \
        "R labels are notebook-wide; anyone can read them from anywhere"


def test_either_side_may_add_and_the_note_says_which(s):
    """A correction from the owner and one from the asker are different
    claims, and on a notebook-wide label nothing else says who wrote it."""
    decided(s)
    s.postscript("pcbrouter", "R1", "from the owner")
    s.postscript("sainpost-itself", "R1", "from the asker")
    assert [(n["by"], n["text"]) for n in
            s.open("pcbrouter", ["R1"])["nodes"][0]["learned later"]] == [
        ("pcbrouter", "from the owner"), ("sainpost-itself", "from the asker")]


def test_a_third_project_cannot_write_in_their_record(s):
    decided(s)
    with pytest.raises(NoteError) as e:
        s.postscript("cadbridge", "R1", "I think the number is wrong")
    assert "neither side" in str(e.value) and "Tell them" in str(e.value)


def test_a_project_that_asked_itself_is_named_once(s):
    s.request(project="pcbrouter", owner="pcbrouter", wanted="w", because="c")
    s.decide("R2", "ACCEPTED", "y")
    with pytest.raises(NoteError) as e:
        s.postscript("cadbridge", "R2", "x")
    assert "R2 belongs to pcbrouter" in str(e.value)


def test_an_undecided_request_has_no_decision_to_add_to(s):
    with pytest.raises(NoteError) as e:
        s.postscript("pcbrouter", "R1", "early thoughts")
    assert "not been decided" in str(e.value) and "note_decide" in str(e.value)


def test_evidence_names_its_project_because_the_label_does_not(s):
    """A9 means nothing on a notebook-wide label -- whose A9?"""
    decided(s)
    s.hypothesis("pcbrouter", hypothesis="the entry edge choice inflates the count",
                 why_now="", measure="m", falsifier="f", apparatus="a")
    s.result("pcbrouter", "16 -> 5 after the fix", "CONFIRMED")
    got = s.postscript("pcbrouter", "R1", "16 became 5", shown_by="A1")
    assert got["shown_by"] == "pcbrouter A1"
    note = s.open("pcbrouter", ["R1"])["nodes"][0]["learned later"][0]
    assert note["shown_by"] == "pcbrouter A1"


def test_without_evidence_it_is_interpretation(s):
    decided(s)
    s.postscript("pcbrouter", "R1", "16 became 5")
    note = s.open("pcbrouter", ["R1"])["nodes"][0]["learned later"][0]
    assert "INTERPRETATION" in note["shown_by"]


def test_the_refusal_to_decide_twice_points_here(s):
    """Where somebody who wants to amend a decision actually lands."""
    decided(s)
    with pytest.raises(NoteError) as e:
        s.decide("R1", "DECLINED", "the figure was wrong")
    assert "note_postscript('R1')" in str(e.value)


def test_a_closed_defect_takes_one_too(s):
    defect(s)
    s.fixed("D1", "FIXED", cause="answers were printed whole",
            change="first lines only", verify="note_path under 64 KiB",
            invalidates="NOTHING")
    s.postscript("sainpost-itself", "D1",
                 "the cause was half of it; postscripts were the other half")
    body = s.open("pcbrouter", ["D1"])["nodes"][0]
    assert body["cause (found by the owner)"] == "answers were printed whole"
    assert body["learned later"][0]["by"] == "sainpost-itself"
    assert s.defects(closed=True)["defects"][0]["learned later"]


def test_an_open_defect_has_note_query_instead(s):
    defect(s)
    with pytest.raises(NoteError) as e:
        s.postscript("pcbrouter", "D1", "more detail")
    assert "still open" in str(e.value) and "note_query" in str(e.value)


def test_nothing_learned_later_prints_nothing(s):
    decided(s)
    assert "learned later" not in s.open("pcbrouter", ["R1"])["nodes"][0]


def test_a_notebook_written_before_these_existed_still_opens(tmp_path):
    db = tmp_path / "old.db"
    st = Store(db)
    st.db.execute("DROP TABLE request_notes")
    st.db.execute("DROP TABLE defect_notes")
    st.close()
    again = Store(db)
    again.start_project("a", "")
    again.start_project("b", "")
    again.request(project="a", owner="b", wanted="w", because="c")
    again.decide("R1", "ACCEPTED", "y")
    again.postscript("b", "R1", "later")
    again.close()
