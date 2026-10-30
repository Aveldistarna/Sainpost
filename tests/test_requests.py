"""What somebody wants the apparatus to DO.

Kept apart from defects because nothing is broken, and because the two need
different guards. A defect proves it happened by pasting what came back; a
request has no output to paste. What stops it being a wish is `because` --
what you were doing when you wanted it, and what not having it cost.

The line is not "no suggestions". Naming the shape you want is allowed: you
know your own need. Telling an owner how to fix something that BROKE is not,
and has no field anywhere in this record.
"""

import pytest

from sainpost.server import render_trunk
from sainpost.store import DECISIONS, NoteError, Store


@pytest.fixture()
def s(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("pcbrouter", "the EDA work")
    st.ask("pcbrouter", "why does the router stall at pad edges")
    st.start_project("sainpost-itself", "the notebook")
    yield st
    st.close()


def ask(st, **kw):
    args = dict(project="pcbrouter", owner="sainpost-itself",
                wanted="write several questions in one call",
                because="Q1 through Q13 went in as thirteen separate calls")
    args.update(kw)
    return st.request(**args)


def test_a_request_needs_no_measurement_of_anyones_to_be_stopped(s):
    got = ask(s)
    assert got["request"] == "R1" and got["owner"] == "sainpost-itself"
    assert "owner's call" in got["note"]


def test_the_cost_is_what_stops_it_being_a_wish(s):
    """A defect proves it happened by pasting output. A request has none, so
    this field carries the weight."""
    for blank in ("wanted", "because"):
        with pytest.raises(NoteError) as e:
            ask(s, **{blank: "  "})
        assert blank in str(e.value)
    assert "not that it would be nice" in str(
        pytest.raises(NoteError, ask, s, wanted="").value).lower()


def test_naming_the_shape_you_want_is_allowed(s):
    """Unlike a defect, which has no field for a proposed fix. Wanting a tool
    to do something is not a claim about code you do not own."""
    got = ask(s, wanted="a batch call taking a list of questions")
    assert "batch call" in got["wanted"]


def test_where_the_asker_was_is_read_not_typed(s):
    assert "pcbrouter was on Q1" in ask(s)["where the asker was"]


def test_where_the_asker_was_is_one_line_of_the_question_not_its_body(s):
    """A question carries its materials and its checklist, and a paper's ran
    to 900 characters. Six calls in one afternoon -- two pre-registrations
    and four requests -- each handed that body back to the agent that had
    just written it. One line per node is a size rule everywhere else."""
    s.ask("pcbrouter", "what does this paper claim\n\nmaterials:\n"
          + "- an article nobody has read yet\n" * 40)
    body = s.open("pcbrouter", ["Q2"])["nodes"][0]["text"]
    assert len(body) > 900, "the question keeps its body"
    for where in (ask(s)["where the asker was"],
                  s.hypothesis("pcbrouter", hypothesis="h", why_now="",
                               measure="m", falsifier="f", apparatus="a")["under"]):
        assert "what does this paper claim" in where
        assert "an article nobody has read yet" not in where
        assert len(where) < 200


def test_it_reaches_the_owner_where_they_already_look(s):
    """One answer to "what is on my plate", not two lists to remember."""
    ask(s)
    theirs = s.trunk("sainpost-itself")
    assert any("R1" in line for line in theirs["waiting_on_you"])
    assert "R1" in render_trunk(theirs)
    mine = s.trunk("pcbrouter")
    assert any("R1" in line for line in mine["blocked_on"])


def test_it_lists_beside_the_defects_rather_than_somewhere_else(s):
    ask(s)
    both = s.defects("sainpost-itself")
    assert [r["request"] for r in both["requests"]] == ["R1"]
    assert both["defects"] == []


def test_a_decision_carries_its_reason_either_way(s):
    """DECLINED with no reason reads as nobody looked. ACCEPTED with none
    loses what was actually agreed to, which is rarely the whole of what was
    asked."""
    ask(s)
    for d in DECISIONS:
        with pytest.raises(NoteError) as e:
            s.decide("R1", d, "   ")
        assert "why is required" in str(e.value)
    got = s.decide("R1", "ACCEPTED", "the retrospective case is real; batching "
                                     "questions only, not attempts")
    assert got["decision"] == "ACCEPTED" and got["tell"] == "pcbrouter"


def test_a_decision_is_made_once(s):
    ask(s)
    s.decide("R1", "DECLINED", "the loop is meant to be one at a time")
    with pytest.raises(NoteError) as e:
        s.decide("R1", "ACCEPTED", "changed my mind")
    assert "append-only" in str(e.value) and "files a new one" in str(e.value)


def test_a_decided_request_leaves_the_plate(s):
    ask(s)
    s.decide("R1", "ACCEPTED", "worth doing")
    assert s.trunk("sainpost-itself")["waiting_on_you"] == []
    assert s.defects("sainpost-itself")["requests"] == []
    assert len(s.defects(closed=True)["requests"]) == 1


def test_the_vocabulary_is_not_the_defect_one(s):
    """A request is not broken and cannot be fixed. It is wanted or it is not."""
    ask(s)
    with pytest.raises(NoteError) as e:
        s.decide("R1", "FIXED", "x")
    assert "ACCEPTED" in str(e.value)
    assert set(DECISIONS) == {"ACCEPTED", "DECLINED"}


def test_an_owner_nobody_has_started_yet_gets_a_blank_card(s):
    got = ask(s, owner="some-other-tool")
    assert got["owner"] == "some-other-tool"
    assert s._project_row("some-other-tool")["stub"] == 1
