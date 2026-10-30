"""What was learned after a question was answered.

An answered question was a dead end: it could not be superseded and could not
be answered again. That is right for the answer and wrong for the question --
six months on, an answer can turn out to have been partial, and the only move
was to open an unrelated new question that pointed at nothing. A cold agent
reported it from the outside before it was fixed.
"""

import pytest

from sainpost.server import render_path, render_trunk
from sainpost.store import NoteError, Store


@pytest.fixture()
def s(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "escape routing")
    st.ask("ddr", "why do the four byte lanes jam")
    st.hypothesis("ddr", hypothesis="via price is too high", why_now="",
                  measure="m", falsifier="f", apparatus="a")
    st.result("ddr", "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    st.answer("ddr", "not a cost problem: the count never moves with price")
    yield st
    st.close()


def test_a_write_does_not_hand_the_body_back(s):
    """note_result echoes its falsifier for a stated reason: the call gets
    checked against the prediction rather than against memory of it. There is
    no equivalent here -- nothing was committed to in advance. An agent
    writing up one history measured the cost: roughly four thousand
    characters of its own text returning into a context that already held it,
    on a single call."""
    got = s.postscript("ddr", "Q1", "x" * 3000, headline="x, three thousand times")
    assert "3000 characters" == got["added"]
    assert not any(len(str(v)) > 200 for v in got.values())
    answered = s.answer("ddr", "y" * 3000, question="Q1") if False else None


def test_answering_does_not_hand_the_answer_back(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "")
    st.ask("ddr", "q")
    got = st.answer("ddr", "z" * 3000, headline="z, three thousand times")
    assert got["recorded"] == "3000 characters"
    assert not any(len(str(v)) > 200 for v in got.values())
    st.close()


def test_the_answer_is_never_touched(s):
    """An answer quietly improved is the failure this record exists to stop,
    wearing its own clothes: what was believed at the time, and on what
    evidence, is the thing that made it worth writing down."""
    before = s.trunk("ddr")["answer"]
    s.postscript("ddr", "Q1", "D1's fix changed the default path, so the 6/8 "
                 "baseline was measured on a rig that no longer exists",
                 headline="D1's fix changed the default path under the baseline")
    assert s.trunk("ddr")["answer"] == before


def test_both_are_kept_with_their_own_dates(s):
    s.postscript("ddr", "Q1", "later: the corridor model was missing entirely")
    body = s.open("ddr", ["Q1"])["nodes"][0]
    assert body["answer"].startswith("not a cost problem")
    later = body["learned later"]
    assert len(later) == 1 and later[0]["text"].startswith("later: the corridor")
    assert later[0]["when"], "a postscript without a date says nothing about order"


def test_an_answer_can_be_qualified_more_than_once(s):
    """Not a comment thread, but an answer really can age twice over years."""
    s.postscript("ddr", "Q1", "first qualification")
    s.postscript("ddr", "Q1", "second, eighteen months later")
    assert [p["text"] for p in s.trunk("ddr")["learned_later"]] == [
        "first qualification", "second, eighteen months later"]


def test_it_appears_wherever_the_answer_appears(s):
    s.postscript("ddr", "Q1", "the baseline was measured on a rig that is gone")
    for text in (render_trunk(s.trunk("ddr")), render_path(s.trail("ddr"))):
        assert "ANSWER" in text and "LATER" in text
        assert "rig that is gone" in text
        assert text.index("ANSWER") < text.index("LATER"), \
            "what was concluded then comes before what is known now"


def test_an_open_question_has_no_answer_to_add_to(s):
    """Keep working under it, or supersede it. A postscript is not a way to
    annotate work in flight."""
    s.ask("ddr", "what blocks the pad frontage")
    with pytest.raises(NoteError) as e:
        s.postscript("ddr", "Q2", "some thoughts")
    assert "still open" in str(e.value)
    assert "supersedes='Q2'" in str(e.value)


def test_a_superseded_question_can_still_be_qualified(s):
    """It is closed, and it is exactly the kind that gets revisited: the chain
    of reformulations is the most reusable thing in the record."""
    s.ask("ddr", "what blocks the pad frontage")
    s.ask("ddr", "is there a corridor model at all", supersedes="Q2")
    s.postscript("ddr", "Q2", "Q2 was closer than it looked; see A7")
    assert s.open("ddr", ["Q2"])["nodes"][0]["learned later"]


def test_a_postscript_says_something(s):
    with pytest.raises(NoteError) as e:
        s.postscript("ddr", "Q1", "   ")
    assert "turned out to be true later" in str(e.value)


def test_a_question_that_was_never_asked_is_refused(s):
    with pytest.raises(NoteError):
        s.postscript("ddr", "Q9", "x")


def test_a_notebook_written_before_postscripts_existed_still_opens(tmp_path):
    db = tmp_path / "old.db"
    st = Store(db)
    st.db.execute("DROP TABLE postscripts")
    st.close()
    again = Store(db)
    again.start_project("ddr", "")
    again.ask("ddr", "q")
    again.answer("ddr", "a")
    again.postscript("ddr", "Q1", "later")
    again.close()


# -- a measurement that was invalid, and nobody noticed --------------------

def test_a_closed_attempt_can_be_marked_without_touching_its_verdict(s):
    """The case is not an outdated finding -- that is a new attempt with an
    edge back. It is a sweep run against a broken rig, which produces a
    plausible number that is indistinguishable from a sound one once written
    down. Nothing could mark it."""
    before = s.open("ddr", ["A1"])["nodes"][0]
    s.postscript("ddr", "A1", "the sweep never resolved the annotations, so this "
                              "number is about nothing")
    after = s.open("ddr", ["A1"])["nodes"][0]
    assert after["verdict"] == before["verdict"] == "FALSIFIED"
    assert after["result (MEASURED)"] == before["result (MEASURED)"]
    assert after["learned later"][0]["text"].startswith("the sweep never resolved")


def test_a_note_backed_by_a_measurement_names_it(s):
    s.ask("ddr", "what actually blocks it")
    s.hypothesis("ddr", hypothesis="the rig was resolving nothing", why_now="A1",
                 prompted_by="A1", measure="m", falsifier="f", apparatus="a")
    s.result("ddr", "0/46 resolved; the control failed", "CONFIRMED")
    got = s.postscript("ddr", "A1", "measured against a rig that resolved nothing",
                       shown_by="A2")
    assert got["shown_by"] == "A2"
    assert s.open("ddr", ["A1"])["nodes"][0]["learned later"][0]["shown_by"] == "A2"


def test_a_note_with_no_evidence_is_labelled_interpretation(s):
    """A claim that a measurement was invalid is itself a claim, and it is not
    free. why_now is labelled the same way for the same reason."""
    from sainpost.server import render_path, render_trunk
    s.postscript("ddr", "A1", "I think the rig was misconfigured")
    for text in (render_trunk(s.trunk("ddr")), render_path(s.trail("ddr"))):
        assert "INTERPRETATION" in text
    assert "INTERPRETATION" in s.postscript("ddr", "A1", "again")["shown_by"]


def test_an_open_attempt_has_no_result_to_annotate(s):
    s.ask("ddr", "next")
    s.hypothesis("ddr", hypothesis="h", why_now="w", measure="m", falsifier="f",
                 apparatus="a")
    with pytest.raises(NoteError) as e:
        s.postscript("ddr", "A2", "something")
    assert "still open" in str(e.value) and "note_blocked" in str(e.value)


def test_an_attempt_cannot_be_its_own_evidence(s):
    with pytest.raises(NoteError) as e:
        s.postscript("ddr", "A1", "x", shown_by="A1")
    assert "its own evidence" in str(e.value)


def test_a_question_postscript_takes_no_evidence_label(s):
    with pytest.raises(NoteError) as e:
        s.postscript("ddr", "Q1", "x", shown_by="A1")
    assert "does not take one" in str(e.value)


# -- a question that was answered can still be replaced --------------------

def test_an_answered_question_can_be_superseded(s):
    """Answered is not superseded, and one message refused both by naming the
    wrong one. A settled question is exactly the kind whose frame later turns
    out to be wrong: the measurements under it stay valid and stop meaning
    what they were taken to mean."""
    got = s.ask("ddr", "is the cost model in reach at all", supersedes="Q1")
    assert got["supersedes"] == "Q1" and "stays answered" in got["note"]
    q1 = s.open("ddr", ["Q1"])["nodes"][0]
    assert q1["status"] == "answered", "it really was answered, and still is"
    assert q1["answer"].startswith("not a cost problem")
    assert q1["superseded_by"] == "Q2"
    assert q1["attempts"], "its attempts stay under it"


def test_new_measurement_goes_under_the_successor(s):
    s.ask("ddr", "is the cost model in reach at all", supersedes="Q1")
    s.hypothesis("ddr", hypothesis="there is no cost field anywhere",
                 why_now="Q1's answer assumed one", prompted_by="A1",
                 measure="m", falsifier="f", apparatus="a")
    s.result("ddr", "key union is {corridor}", "CONFIRMED")
    trail = {q["question"]: [a["attempt"] for a in q["attempts"]]
             for q in s.trail("ddr")["trail"]}
    assert trail == {"Q1": ["A1"], "Q2": ["A2"]}


def test_a_question_is_still_only_replaced_once(s):
    s.ask("ddr", "second framing", supersedes="Q1")
    with pytest.raises(NoteError) as e:
        s.ask("ddr", "third framing", supersedes="Q1")
    assert "already replaced by Q2" in str(e.value)
    assert "Supersede that one instead" in str(e.value)
