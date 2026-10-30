"""What the record refuses, and why each refusal exists.

Every test here names the failure it prevents. A test that passes against a
store with the guard removed is fixing nothing, so the guards are asserted
directly rather than through happy paths that happen to touch them.
"""

import pytest

from sainpost.store import NoteError, Store, similarity


@pytest.fixture()
def s(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "escape routing under a 0.5mm BGA")
    st.ask("ddr", "why do U2's four byte lanes jam")
    yield st
    st.close()


def pre(st, project="ddr", **kw):
    args = dict(hypothesis="via price is too high to escape to another layer",
                why_now="A0 showed order does not matter",
                measure="sweep via_cost_mm 0.1..8.0, count joined spans",
                falsifier="joined-span count does not move across the sweep",
                apparatus="stale=false checked; repair=False noted")
    args.update(kw)
    return st.hypothesis(project, **args)


# -- the pre-registration gate -------------------------------------------

def test_a_result_cannot_exist_without_a_pre_registered_attempt(s):
    """The whole mechanism. There is no route to a number that skipped the
    falsifier, because there is no attempt to attach it to."""
    with pytest.raises(NoteError) as e:
        s.result("ddr", "6/8 unchanged", "FALSIFIED")
    assert "no open attempt" in str(e.value)


@pytest.mark.parametrize("blank", ["falsifier", "apparatus", "measure"])
def test_the_fields_written_before_the_data_are_required(s, blank):
    with pytest.raises(NoteError) as e:
        pre(s, **{blank: "   "})
    assert blank in str(e.value)


def test_why_now_is_required_once_a_result_exists_to_name_and_not_before(s):
    """It names the prior RESULT that sent you here. Before one exists there
    is none, and requiring it bought only a paragraph explaining that the
    field did not apply -- which is exactly what a cold agent wrote into it.
    An arm opened beside the first attempt is in that position too: the
    project's second attempt, with nothing yet measured."""
    pre(s, why_now="   ")
    pre(s, hypothesis="the pad frontage is blocked, not the price", why_now="   ")
    s.result("ddr", "6/8 unchanged", "FALSIFIED", attempt="A1")
    s.result("ddr", "3 vias", "FALSIFIED", attempt="A2")
    with pytest.raises(NoteError) as e:
        pre(s, hypothesis="the layer count is too low", why_now="   ")
    assert "why_now" in str(e.value)


def test_an_attempt_closes_once_and_is_never_edited(s):
    pre(s)
    s.result("ddr", "6/8 unchanged; vias 12<->6", "FALSIFIED")
    with pytest.raises(NoteError) as e:
        s.result("ddr", "actually 7/8", "CONFIRMED", attempt="A1")
    assert "append-only" in str(e.value)
    assert "FALSIFIED" in str(e.value)


def test_the_verdict_is_checked_against_a_closed_vocabulary(s):
    pre(s)
    with pytest.raises(NoteError):
        s.result("ddr", "6/8", "probably wrong")


def test_closing_returns_the_falsifier_that_was_committed_to(s):
    """So the call is checked against the prediction, not against memory."""
    pre(s)
    out = s.result("ddr", "6/8 unchanged", "FALSIFIED")
    assert out["predicted_falsifier"] == "joined-span count does not move across the sweep"


# -- one position at a time ----------------------------------------------

def cpu(st, project="ddr"):
    return pre(st, project, hypothesis="the solver is faster vectorised on the CPU",
               measure="wall time of bench/solve.py at N=1e6, 5 runs",
               falsifier="CPU median is not below 0.8x the baseline",
               apparatus="baseline 12.4s at this commit, same machine")


def gpu(st, project="ddr"):
    return pre(st, project, hypothesis="the solver is faster on the GPU",
               measure="wall time of bench/solve.py at N=1e6, 5 runs",
               falsifier="GPU median is not below 0.8x the baseline",
               apparatus="baseline 12.4s at this commit, CUDA 12.4 visible")


def test_arms_of_one_question_are_open_side_by_side(s):
    """Two competing hypotheses for one question, measured in parallel. The
    position is still one question; the trunk shows both arms, each with the
    falsifier it committed to."""
    assert cpu(s)["attempt"] == "A1"
    second = gpu(s)
    assert second["attempt"] == "A2"
    [beside] = second["open beside it, under the same question"]
    assert beside["attempt"] == "A1" and beside["measure"].startswith("wall time"), \
        "the second arm sees how the first will be measured, before measuring"
    t = s.trunk("ddr")
    assert [(a["attempt"], a["verdict"]) for a in t["attempts"]] == \
        [("A1", "OPEN"), ("A2", "OPEN")]
    assert all(a["falsifier"] for a in t["attempts"])
    assert [r["open_attempts"] for r in s.projects()] == [[
        "A1  the solver is faster vectorised on the CPU",
        "A2  the solver is faster on the GPU"]]


def test_with_arms_open_side_by_side_a_close_must_say_which(s):
    """Guessing would close somebody else's arm with your number."""
    cpu(s)
    gpu(s)
    with pytest.raises(NoteError) as e:
        s.result("ddr", "9.1s median", "CONFIRMED")
    assert "A1, A2 are open side by side" in str(e.value)
    got = s.result("ddr", "9.1s median", "CONFIRMED", attempt="A1")
    assert got["still open beside it"] == ["A2  the solver is faster on the GPU"]
    assert "still open beside it" not in s.result(
        "ddr", "14.0s median", "FALSIFIED", attempt="A2")


def test_a_blocked_arm_is_named_too(s):
    cpu(s)
    gpu(s)
    with pytest.raises(NoteError) as e:
        s.blocked("ddr", invocation="solve --gpu", observed="CUDA error 999",
                  needed="a GPU run", owner="cuda-rig")
    assert "say which" in str(e.value).lower()
    s.blocked("ddr", invocation="solve --gpu", observed="CUDA error 999",
              needed="a GPU run", owner="cuda-rig", attempt="A2", stopped=True)
    assert [a["attempt"] for a in s.trunk("ddr")["attempts"]
            if a["verdict"] == "OPEN"] == ["A1"]


def test_replacing_the_question_mid_measurement_leaves_the_position_with_the_work(s):
    """The README said the position does not move while an attempt is open,
    "equally when you superseded your own question mid-measurement". Nothing
    tested it, and it had stopped being true: superseding moved the trunk to
    the successor, and the open arm's falsifier left the view re-read at
    every checkpoint."""
    cpu(s)
    got = s.ask("ddr", "is it the memory layout, not the device", supersedes="Q1")
    assert got["position"].startswith("unchanged -- A1 is open")
    t = s.trunk("ddr")
    assert (t["question"], t["status"], t["superseded_by"]) == ("Q1", "superseded", "Q2")
    assert t["attempts"][0]["falsifier"] == "CPU median is not below 0.8x the baseline"
    assert s.projects()[0]["current_question"].startswith("Q1")
    with pytest.raises(NoteError) as e:
        gpu(s)
    assert "A1 is still open under Q1, which was replaced by Q2" in str(e.value), \
        "no work opens under a second question while the first still has some"
    s.result("ddr", "budget spent", "ABANDONED")
    assert s.trunk("ddr")["question"] == "Q2"
    assert gpu(s)["under"].startswith("Q2")


def test_prompted_by_cannot_name_an_arm_still_in_flight(s):
    """While one attempt at a time was the rule this held by itself. With
    arms side by side a sibling can be named, and it has no result yet."""
    cpu(s)
    with pytest.raises(NoteError) as e:
        pre(s, hypothesis="GPU, prompted by the CPU arm", why_now="A1",
            prompted_by="A1")
    assert "A1 is still open" in str(e.value) and "prompted_by" in str(e.value)


def test_abandoning_is_a_verdict_so_the_front_can_always_be_closed(s):
    pre(s)
    s.result("ddr", "budget spent, 3h, no signal", "ABANDONED")
    assert pre(s, hypothesis="the layer count is too low")["attempt"] == "A2"


def test_an_attempt_needs_a_question_to_hang_off(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("bare")
    with pytest.raises(NoteError) as e:
        pre(st, project="bare")
    assert "no current question" in str(e.value)


def test_a_question_cannot_be_answered_while_work_is_open_under_it(s):
    pre(s)
    with pytest.raises(NoteError) as e:
        s.answer("ddr", "it was the orientation")
    assert "A1 is still open" in str(e.value)


def test_a_question_waits_for_every_arm_before_it_is_answered(s):
    """An answer that skips an arm still in flight is a summary of half the
    comparison."""
    cpu(s)
    gpu(s)
    s.result("ddr", "9.1s median", "CONFIRMED", attempt="A1")
    with pytest.raises(NoteError) as e:
        s.answer("ddr", "the CPU")
    assert "A2 is still open" in str(e.value)
    s.result("ddr", "14.0s median", "FALSIFIED", attempt="A2")
    s.answer("ddr", "the CPU: 9.1s against 14.0s at N=1e6")


# -- where the pointer rests ----------------------------------------------

def test_a_question_asked_under_open_work_becomes_current_when_it_closes(s):
    """note_ask said so ("close that attempt and it becomes current") and
    nothing did it: the pointer stayed on the old question after the close."""
    cpu(s)
    gpu(s)
    got = s.ask("ddr", "does it scale past N=1e7")
    assert "A1, A2 are open" in got["position"]
    s.result("ddr", "9.1s", "CONFIRMED", attempt="A1")
    assert s.trunk("ddr")["question"] == "Q1", "one arm is still open under Q1"
    s.result("ddr", "14.0s", "FALSIFIED", attempt="A2")
    assert s.trunk("ddr")["question"] == "Q2"


def test_a_pointer_left_on_a_closed_question_is_read_past(s):
    """sainpost-itself sat on answered Q7 with Q5 open: the pointer had
    closed before the fix that moves it at close existed, so nothing ever
    moved it, and note_hypothesis refused the project everything."""
    s.ask("ddr", "a second question, left open")                 # Q2, current
    s.answer("ddr", "answered", question="Q2")
    s.db.execute("UPDATE projects SET current_question=(SELECT id FROM questions"
                 " WHERE seq=2)")                                # as it was before
    s.db.commit()
    assert s.trunk("ddr")["question"] == "Q1"
    assert pre(s)["under"].startswith("Q1")


# -- the edge is a result you read, not a taxonomic parent ----------------

def test_prompted_by_can_only_ever_name_an_attempt_that_has_a_result(s):
    """Once held by the one-open-attempt rule alone, and this test said that
    dropping the rule would quietly let an in-flight attempt become an edge.
    The rule was relaxed to arms side by side (Q8 of sainpost-itself), and
    the guard is written out now."""
    pre(s)
    with pytest.raises(NoteError) as e:
        s.hypothesis("ddr", hypothesis="x", why_now="y", measure="m",
                     falsifier="f", apparatus="a", prompted_by="A1")
    assert "still open" in str(e.value)

    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    assert s.hypothesis("ddr", hypothesis="x", why_now="y", measure="m",
                        falsifier="f", apparatus="a",
                        prompted_by="A1")["prompted_by"] == "A1"


def test_the_tree_assembles_from_those_edges(s):
    pre(s)
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    pre(s, hypothesis="the part is facing the wrong way", prompted_by="A1")
    s.result("ddr", "270deg: 21->28/32", "CONFIRMED")
    node = s.open("ddr", ["A1"])["nodes"][0]
    assert node["prompted_these"][0].startswith("A2")
    assert s.trunk("ddr")["attempts"][1]["prompted_by"] == "A1"


# -- reformulating the question is a node, not a rename -------------------

def test_superseding_keeps_the_chain_and_moves_the_position(s):
    s.ask("ddr", "the pad frontage is blocked, not the order", supersedes="Q1")
    t = s.trunk("ddr")
    assert t["question"] == "Q2"
    assert [r["question"] for r in t["reformulated_from"]] == ["Q1"]


def test_a_superseded_question_keeps_its_attempts_readable(s):
    pre(s)
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    s.ask("ddr", "the pad frontage is blocked", supersedes="Q1")
    old = s.trunk("ddr", question="Q1")
    assert old["status"] == "superseded"
    assert old["attempts"][0]["verdict"] == "FALSIFIED"


def test_a_question_is_not_superseded_twice(s):
    s.ask("ddr", "second", supersedes="Q1")
    with pytest.raises(NoteError):
        s.ask("ddr", "third", supersedes="Q1")


# -- one line, written rather than cut -------------------------------------

LONG = ("[R1] 設計に要る構造（理由・公差付きの寸法・動き・由来）は、エージェントの観測"
        "（画像認識の出力・製造用の設計ファイル）に含まれていないか。"
        "見た目のように観測の中に在るものは、知覚で扱えるか。")


def test_a_body_too_long_for_one_line_is_refused_without_one(s):
    """Every view but note_open shows a node as one line. That line used to
    be the body with a machine's cut in it -- a summary nobody wrote and
    nobody checked, which is the one kind of claim this record refuses
    everywhere else. It also cut badly: this question came out as "[R1]"."""
    with pytest.raises(NoteError) as e:
        s.ask("ddr", LONG)
    assert "headline" in str(e.value) and "96" in str(e.value)
    assert "note_open gives it whole" in str(e.value)
    got = s.ask("ddr", LONG, headline="[R1] 設計の構造は観測に含まれるか")
    assert got["question"] == "Q2"


def test_a_short_body_needs_none_because_it_is_already_its_own_line(s):
    """Asking for a second copy of a one-sentence question is a field that
    gets filled with the same words -- which is how why_now came to hold
    paragraphs explaining that it did not apply."""
    s.ask("ddr", "does the pad frontage block the lanes")
    assert s.trunk("ddr", "Q2")["question"] == "Q2"
    assert "does the pad frontage" in s.trail("ddr")["trail"][1]["text"]


def test_a_headline_is_one_line_and_no_longer_than_one(s):
    for bad, says in ((LONG, "96 is the width"), ("two\nlines", "one line")):
        with pytest.raises(NoteError) as e:
            s.ask("ddr", LONG, headline=bad)
        assert says in str(e.value)


def test_the_written_line_is_what_every_one_line_view_shows(s):
    """And the body is untouched underneath it."""
    body = "扱えるかは構造が書かれているかで決まる。" * 8
    pre(s, hypothesis=body, headline="扱えるかを決めるのは構造であって知覚ではない")
    s.result("ddr", "23件中20件を説明。" + "内訳。" * 200, "CONFIRMED",
             headline="23件中20件を説明、残り3件は記録の欠落")
    [row] = s.trail("ddr")["standing"]
    assert row["headline"] == "扱えるかを決めるのは構造であって知覚ではない"
    assert row["result"] == "23件中20件を説明、残り3件は記録の欠落"
    whole = s.open("ddr", ["A1"])["nodes"][0]
    assert whole["hypothesis"] == body, "the body is kept exactly as written"
    assert whole["result (MEASURED)"].startswith("23件中20件を説明。内訳。")


def test_a_row_written_before_headlines_existed_is_still_cut_to_fit(s):
    """No headline can be written for it now: this record has no edit path,
    and inventing one would be the summary nobody checked, arriving by the
    door that was built to keep it out."""
    s.db.execute("INSERT INTO questions (project_id, seq, text, created_at)"
                 " SELECT id, 2, ?, '2026-09-01T00:00:00+09:00' FROM projects"
                 " WHERE name='ddr'", (LONG,))
    s.db.commit()
    line = s.trunk("ddr", "Q1")["other_open_questions"][0]
    assert line.startswith("Q2  [R1] 設計に要る構造") and line.endswith("...")


# -- a question can stand under another ------------------------------------

def tree(s):
    """The shape a paper's argument took: a claim, what it requires, and
    what shows the requirement."""
    s.answer("ddr", "not the lanes", question="Q1")
    s.ask("ddr", "what does this paper claim, in one sentence")
    s.ask("ddr", "the claim must explain the failures too", parent="Q2")
    s.ask("ddr", "which material shows that", parent="Q3")


def test_a_question_opened_under_another_is_not_a_reformulation_of_it(s):
    """The only relation there used to be said the earlier question was
    WRONG. A requirement is the opposite: the claim stands, and this is part
    of answering it. Used as supersedes it would be a lie; left off, the
    requirement became a question related to nothing."""
    tree(s)
    assert s.open("ddr", ["Q4"])["nodes"][0]["in service of"] == \
        ["Q2  what does this paper claim, in one sentence",
         "Q3  the claim must explain the failures too"]
    assert s.open("ddr", ["Q3"])["nodes"][0]["opened under it"] == \
        ["Q4  which material shows that"]
    assert s.trunk("ddr", "Q3")["in_service_of"] == \
        ["Q2  what does this paper claim, in one sentence"]
    q3 = s.open("ddr", ["Q3"])["nodes"][0]
    assert q3["supersedes"] is None and q3["superseded_by"] is None


def test_the_parent_waits_for_everything_under_it_at_any_depth(s):
    """The same rule as an open attempt, one level up: an answer written
    over an open requirement is a summary, not a conclusion. The grandchild
    counts -- the requirement is not settled while what shows it is open."""
    tree(s)
    with pytest.raises(NoteError) as e:
        s.answer("ddr", "it claims X", question="Q2")
    assert "Q3" in str(e.value) and "Q4" in str(e.value)
    s.answer("ddr", "the DESIGN.md table", question="Q4")
    with pytest.raises(NoteError):
        s.answer("ddr", "it claims X", question="Q2")
    s.answer("ddr", "it must explain the failures", question="Q3")
    s.answer("ddr", "it claims X", question="Q2")


def test_a_replacement_stands_where_the_replaced_question_stood(s):
    """Reformulating a requirement does not move it out from under what
    required it, so the two cannot be passed together either."""
    tree(s)
    s.ask("ddr", "which material shows it, take two", supersedes="Q4")
    assert s.open("ddr", ["Q5"])["nodes"][0]["in service of"][-1].startswith("Q3")
    with pytest.raises(NoteError) as e:
        s.ask("ddr", "both at once", supersedes="Q3", parent="Q2")
    assert "already keeps the parent" in str(e.value)


def test_nothing_opens_under_a_question_that_is_already_settled(s):
    """Its answer is written, and this record does not edit one. A
    requirement added afterwards would be a gate that never held."""
    tree(s)
    s.answer("ddr", "the table", question="Q4")
    with pytest.raises(NoteError) as e:
        s.ask("ddr", "a requirement thought of too late", parent="Q4")
    assert "nothing can be opened under it" in str(e.value)


# -- moving onto a question that is already open ---------------------------

def test_work_can_be_opened_under_a_question_that_is_not_the_current_one(s):
    """The pointer only ever moved to the question most recently ASKED, so a
    tree laid out before any work began left every requirement but the last
    unreachable. The only order that worked was to open one question and
    measure it before writing the next -- the opposite of laying the
    argument out first, which was the whole reason for the tree."""
    s.answer("ddr", "not the lanes", question="Q1")
    s.ask("ddr", "what does this paper claim")
    for r in ("it must explain the failures", "it must name its materials"):
        s.ask("ddr", r, parent="Q2")
    assert s.trunk("ddr")["question"] == "Q4", "the last one asked"
    got = pre(s, question="Q3")
    assert got["under"].startswith("Q3")
    assert s.trunk("ddr")["question"] == "Q3", "the position followed the work"


def test_closing_work_you_moved_to_leaves_the_position_there(s):
    """The position followed the work to Q3; finishing it must not throw the
    position at Q4 because Q4 happens to carry a higher number. What moves
    the position after a close is a question asked WHILE the work was open,
    and nothing else."""
    s.answer("ddr", "not the lanes", question="Q1")
    s.ask("ddr", "what does this paper claim")
    s.ask("ddr", "it must explain the failures", parent="Q2")
    s.ask("ddr", "it must name its materials", parent="Q2")     # Q4, asked before
    pre(s, question="Q3")
    s.result("ddr", "r", "CONFIRMED")
    assert s.trunk("ddr")["question"] == "Q3"
    pre(s, hypothesis="the next arm", question="Q3")
    s.ask("ddr", "a question that arrived mid-measurement")     # Q5, asked during
    s.result("ddr", "r", "CONFIRMED")
    assert s.trunk("ddr")["question"] == "Q5"


def test_it_will_not_move_while_work_is_open_under_another_question(s):
    """One front. Moving with an arm still running is two positions, and the
    trunk shows one."""
    s.answer("ddr", "not the lanes", question="Q1")
    s.ask("ddr", "what does this paper claim")
    s.ask("ddr", "it must explain the failures", parent="Q2")
    pre(s, question="Q3")
    with pytest.raises(NoteError) as e:
        pre(s, hypothesis="something under the other one", question="Q2")
    assert "open under Q3" in str(e.value)
    s.result("ddr", "budget spent", "ABANDONED")
    assert pre(s, hypothesis="something under the other one",
               question="Q2")["under"].startswith("Q2")


def test_reading_another_question_survives_a_percent_sign_in_open_work(s):
    """The open attempt's hypothesis went into an f-string and then through
    "%" formatting. On this machine's notebook an open attempt says "…は 3%
    以上短くなり、…", and note_trunk on any other question of that project
    came back as ValueError: unsupported format character."""
    s.ask("ddr", "a second question")
    pre(s, hypothesis="合計は 3% 以上短くなり、(e) も変わらない", question="Q2")
    t = s.trunk("ddr", "Q1")
    assert t["open_elsewhere"] == ["A1  合計は 3% 以上短くなり、(e) も変わらない  (under Q2)"]


# -- what a result or an answer rests on, elsewhere ------------------------

def board(s):
    """Another project's measurement, the kind a write-up stands on."""
    s.start_project("adc", "the board")
    s.ask("adc", "how many nets are left unrouted after the second pass")
    s.hypothesis("adc", hypothesis="the second pass leaves 113", why_now="",
                 measure="count unrouted", falsifier="not 113", apparatus="kicad 10.0.5")
    s.result("adc", "113 unrouted, registered run", "CONFIRMED")


def test_a_result_can_rest_on_another_projects_record_as_a_link(s):
    """Prose could already name one. A name in a sentence is not checked and
    does not change when what it names does -- the first draft of a paper
    cited "119" from an article when the registered number was 113, and
    nothing could have told it."""
    board(s)
    pre(s)
    got = s.result("ddr", "20 of 23 events explained", "CONFIRMED", cites="adc/A1")
    assert [c["cites"] for c in got["rests on"]] == ["adc/A1"]
    assert got["rests on"][0]["verdict"] == "CONFIRMED"
    assert "READ IT AGAIN" not in got["rests on"][0]


def test_a_write_does_not_hand_back_what_it_was_just_given(s):
    """A result runs to thousands of characters and the caller wrote it. The
    falsifier does come back -- that is the check this call exists to make
    possible, and it is a sentence. Measured on this machine's notebook: the
    median result is 1,362 characters and the median falsifier 208."""
    board(s)
    pre(s)
    numbers = "the sweep, in full:\n" + "row after row of it\n" * 200
    got = s.result("ddr", numbers, "CONFIRMED", cites="adc/A1",
                   headline="the sweep ran; every row is in the body")
    assert numbers not in str(got)
    assert got["recorded"] == f"{len(numbers.strip())} characters"
    assert got["predicted_falsifier"] == \
        "joined-span count does not move across the sweep"
    assert "result" not in got["rests on"][0], "nor the cited row's numbers"
    assert len(str(got)) < 1500
    assert s.open("ddr", ["A1"])["nodes"][0]["result (MEASURED)"] == numbers.strip()


def test_prior_art_comes_back_as_one_line_of_what_fell_over(s):
    """Four of these arrived whole on one pre-registration -- 7,000
    characters of numbers nobody had asked for -- with six more questions
    still to register, each two to four times."""
    s.start_project("adc", "the board")
    s.ask("adc", "how many nets are left unrouted after the second pass")
    s.hypothesis("adc", hypothesis="the second pass leaves 113", why_now="",
                 measure="count unrouted", falsifier="not 113", apparatus="kicad")
    s.result("adc", "113 unrouted, registered run\n" + "row after row\n" * 300,
             "FALSIFIED", headline="113 unrouted, registered run")
    s.start_project("hat", "another board")
    s.ask("hat", "how many nets are left unrouted after the second pass")
    got = pre(s, project="hat",
              hypothesis="the second pass leaves 113 nets unrouted")
    [prior] = got["already_tried"]
    assert prior["attempt"] == "A1" and prior["verdict"] == "FALSIFIED"
    assert prior["result"] == "113 unrouted, registered run", "the line that fell over"
    assert prior["hypothesis"], "the hypothesis is what the similarity was on"
    assert len(str(got)) < 1500


def test_a_citation_that_names_nothing_is_refused(s):
    """It reads as a reference and cannot be followed."""
    board(s)
    pre(s)
    with pytest.raises(NoteError) as e:
        s.result("ddr", "r", "CONFIRMED", cites="adc/A9")
    assert "'adc/A9'" in str(e.value)
    assert s.trunk("ddr")["attempts"][0]["verdict"] == "OPEN", "nothing was closed"


def test_the_cited_record_is_read_as_it_stands_now_not_as_it_was(s):
    """The failure this exists for: the board annotates its own measurement
    -- the number was an artefact -- and the write-up that rests on it goes
    on reading as sound. An unverified intermediate promoted to a fact,
    crossing a project boundary."""
    board(s)
    pre(s)
    s.result("ddr", "20 of 23 events explained", "CONFIRMED", cites="adc/A1")
    s.postscript("adc", "A1", "the 113 came off a rig that double-counted courtyards")
    [rests] = s.open("ddr", ["A1"])["nodes"][0]["the result rests on"]
    assert "double-counted" in rests["READ IT AGAIN"][0]
    assert any("adc/A1" in line for line in s.trunk("ddr")["attempts"][0]["rests_on"])


def test_resting_on_something_still_open_says_so(s):
    """An open attempt has no result to rest on, and a question that is
    still open has no answer."""
    board(s)
    s.hypothesis("adc", hypothesis="a third pass helps", why_now="A1 left 113",
                 prompted_by="A1", measure="count", falsifier="still 113",
                 apparatus="kicad 10.0.5")
    pre(s)
    got = s.result("ddr", "r", "CONFIRMED", cites="adc/A2, adc/Q1")
    assert [c["READ IT AGAIN"][0] for c in got["rests on"]] == [
        "it is still open: there is no result yet to rest on",
        "it is still open: there is no answer yet to rest on"]


def test_an_answer_rests_on_things_too(s):
    board(s)
    s.answer("ddr", "it was the corridor model", cites="adc/A1")
    body = s.open("ddr", ["Q1"])["nodes"][0]
    assert body["the answer rests on"][0]["cites"] == "adc/A1"


def test_citing_something_as_a_record_of_what_happened_does_not_warn_of_it(s):
    """A falsified attempt cited BECAUSE it was falsified is not a shaky
    result to lean on; it is the event. Nine citations of that kind came
    back with six warnings, five of them "not a standing result", and the
    one that mattered -- a note saying the number was an artefact -- was a
    line among them. A warning stops being one when it is always there."""
    board(s)
    s.hypothesis("adc", hypothesis="a third pass helps", why_now="A1 left 113",
                 prompted_by="A1", measure="count", falsifier="still 113",
                 apparatus="kicad 10.0.5")
    s.result("adc", "still 113", "FALSIFIED")
    pre(s)
    got = s.result("ddr", "20 of 23 events explained", "CONFIRMED",
                   cites="records:adc/A2, adc/A1")
    events, leaned = got["rests on"]
    assert events["as"] == "records" and "READ IT AGAIN" not in events
    assert events["verdict"] == "FALSIFIED", "the verdict is still shown"
    assert leaned["as"] == "supports"

    s.postscript("adc", "A2", "the count came off a rig that double-counted")
    [events, _] = s.open("ddr", ["A1"])["nodes"][0]["the result rests on"]
    assert "double-counted" in events["READ IT AGAIN"][0], \
        "what was learned later is a warning whichever way it was cited"


def test_a_refutation_is_something_to_lean_on_and_warns_the_other_way(s):
    """A FALSIFIED row is the most valuable kind in this record, and an
    argument standing on a rival explanation having been killed stands on
    exactly that. Cited as `supports` it warned; cited as `records` it would
    stop warning and also stop saying anything was leaning on it."""
    board(s)
    s.hypothesis("adc", hypothesis="perception is what decides", why_now="A1 left 113",
                 prompted_by="A1", measure="count", falsifier="a counterexample",
                 apparatus="the three articles")
    s.result("adc", "two counterexamples", "FALSIFIED")
    pre(s)
    got = s.result("ddr", "the rival is dead", "CONFIRMED",
                   cites="refutes:adc/A2, refutes:adc/A1")
    killed, standing = got["rests on"]
    assert killed["as"] == "refutes" and "READ IT AGAIN" not in killed
    assert "no refutation here to rest on" in standing["READ IT AGAIN"][0], \
        "A1 is CONFIRMED, so it refutes nothing"

    s.postscript("adc", "A2", "the counterexamples were the same board twice")
    [killed, _] = s.open("ddr", ["A1"])["nodes"][0]["the result rests on"]
    assert "the same board twice" in killed["READ IT AGAIN"][0], \
        "what was learned later warns whichever way it was cited"


def test_leaning_on_a_falsified_result_still_warns(s):
    board(s)
    s.hypothesis("adc", hypothesis="a third pass helps", why_now="A1 left 113",
                 prompted_by="A1", measure="count", falsifier="still 113",
                 apparatus="kicad 10.0.5")
    s.result("adc", "still 113", "FALSIFIED")
    pre(s)
    got = s.result("ddr", "r", "CONFIRMED", cites="adc/A2")
    assert "not a standing result" in got["rests on"][0]["READ IT AGAIN"][0]


# -- the search that the write path forces you through --------------------

def test_pre_registering_surfaces_the_same_hypothesis_from_another_project(s):
    pre(s)
    s.result("ddr", "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    s.start_project("hat", "another board entirely")
    s.ask("hat", "why will these spans not route")
    hits = pre(s, project="hat")["already_tried"]
    assert hits and hits[0]["project"] == "ddr"
    assert hits[0]["verdict"] == "FALSIFIED"
    assert "0.1..8.0" in hits[0]["result"]


def test_an_open_attempt_is_not_offered_as_prior_art(s):
    """It has no verdict yet, so it cannot tell anyone anything."""
    pre(s)
    assert s.already_tried("via price is too high") == []


def test_similarity_survives_japanese_without_spaces():
    a = "ビア価格が高すぎて別層に逃げない"
    assert similarity(a, "ビア価格が高すぎるので別の層に逃げられない") > 0.30
    assert similarity(a, "部品の向きが悪い") < 0.30


# -- reading ---------------------------------------------------------------

def test_the_trunk_shows_the_commitment_while_the_attempt_is_open(s):
    pre(s)
    a = s.trunk("ddr")["attempts"][0]
    assert a["verdict"] == "OPEN"
    assert a["falsifier"] and a["apparatus"] and a["since"]


def test_the_trunk_drops_the_commitment_once_the_result_is_in(s):
    """Closed rows are one line. The trunk is re-read constantly; bodies
    are what note_open is for."""
    pre(s)
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    a = s.trunk("ddr")["attempts"][0]
    assert a["falsifier"] is None and a["result"] == "6/8 unchanged"


def test_open_separates_what_was_measured_from_what_was_interpreted(s):
    pre(s)
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    node = s.open("ddr", ["A1"])["nodes"][0]
    assert node["result (MEASURED)"] == "6/8 unchanged"
    assert node["why_now (INTERPRETATION, n=1)"].startswith("A0 showed")


def test_other_open_questions_stay_visible_in_the_footer(s):
    s.ask("ddr", "an unrelated question")          # no supersedes
    assert s.trunk("ddr")["other_open_questions"][0].startswith("Q1")


def test_an_unknown_project_lists_the_ones_that_exist(s):
    with pytest.raises(NoteError) as e:
        s.trunk("nope")
    assert "ddr" in str(e.value)


def test_the_successor_is_named_as_such_not_listed_as_unrelated_work(s):
    """Reading a superseded question, its replacement must read as the
    replacement. Printing it in the "other open questions" footer is true
    and unreadable -- the successor is the one thing that explains why this
    question stopped."""
    s.ask("ddr", "the pad frontage is blocked", supersedes="Q1")
    old = s.trunk("ddr", question="Q1")
    assert old["superseded_by"] == "Q2"
    assert old["other_open_questions"] == []


def test_naming_an_attempt_in_why_now_without_the_edge_is_refused(s):
    """Two fields encode the same link and only one was enforced. An agent
    named A1 in why_now, forgot prompted_by, and lost the edge with nothing
    said -- while the information sat in the field one over. Prose does not
    assemble the tree."""
    pre(s)
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    with pytest.raises(NoteError) as e:
        pre(s, hypothesis="the pad frontage is blocked",
            why_now="A1 was falsified, so it is not a cost problem")
    assert "prompted_by='A1'" in str(e.value)
    pre(s, hypothesis="the pad frontage is blocked",
        why_now="A1 was falsified, so it is not a cost problem", prompted_by="A1")


def test_an_attempt_that_does_not_exist_yet_is_not_mistaken_for_an_edge(s):
    """A9 in prose is not a reference to anything. Only labels that resolve to
    a closed attempt in this project count."""
    pre(s, why_now="the A9 revision of the datasheet says the pads are 0.4mm")


def test_a_closed_notebook_is_complete_in_one_file(tmp_path):
    """WAL keeps recent writes in research.db-wal, so copying just the .db of
    a live notebook yields a file that opens cleanly and holds nothing. Three
    sessions of records were lost to exactly that. A notebook nobody is
    attached to has to be whole, or "plain SQLite, anyone can read it" is not
    true."""
    import shutil
    db = tmp_path / "n.db"
    st = Store(db)
    st.start_project("ddr", "")
    st.ask("ddr", "why do the lanes jam")
    st.close()

    shutil.copy(db, tmp_path / "copy.db")            # the naive copy
    again = Store(tmp_path / "copy.db")
    assert [r["project"] for r in again.projects()] == ["ddr"]
    assert again.trunk("ddr")["text"] == "why do the lanes jam"
    again.close()


def test_a_repo_path_can_be_repointed_only_once_it_has_gone_stale(tmp_path):
    """A repo path is not a claim about the world at a moment -- which is what
    everything else here is, and why none of it can be edited. It is a
    pointer, and pointers move: the trial records that found half the faults
    in this server name commits in a directory that will be cleaned up.

    Only a path that no longer resolves may be re-pointed, so this cannot
    quietly become a general edit path."""
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "escape routing", repo=str(old))

    with pytest.raises(NoteError) as e:
        st.start_project("ddr", "", repo=str(new))
    assert "still exists" in str(e.value), "a live path is not stale"

    old.rmdir()
    new.mkdir()
    got = st.start_project("ddr", "", repo=str(new))
    assert got["repo"] == str(new) and "no longer exists" in got["repointed"]
    assert st._project_row("ddr")["repo"] == str(new)
    assert st._project_row("ddr")["description"] == "escape routing", \
        "re-pointing moves the pointer and nothing else"
    st.close()


def test_a_stale_path_does_not_open_the_description_to_editing(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "the original account", repo=str(old))
    old.rmdir()
    (tmp_path / "new").mkdir()
    st.start_project("ddr", "a rewritten account", repo=str(tmp_path / "new"))
    assert st._project_row("ddr")["description"] == "the original account"
    st.close()


def test_answering_moves_off_the_question_onto_one_that_is_open(s):
    """The pointer only ever moved when a question was ASKED, so answering the
    current one left it on an answered question -- and that is not a display
    fault. note_hypothesis attaches to the current question and refuses a
    closed one, so a project with two open questions and a stale pointer
    could not pre-register anything. The instruction it got back, "note_ask
    opens the next one", asked it to invent a question it did not have in
    order to reach one it already had.

    Reported from outside, by a project whose entry-point row read
    `current_question Q13 [answered]` while Q10 and Q11 were open."""
    s.ask("ddr", "second question, left open")
    s.ask("ddr", "third question, answered now")
    s.answer("ddr", "settled")
    assert s.trunk("ddr")["status"] == "open"
    pre(s, hypothesis="and now this can be measured")


def test_a_project_whose_questions_are_all_answered_says_so(s):
    """Clearing the pointer instead made the trunk report "no question yet"
    about a project full of them -- the same fault in the other direction."""
    s.answer("ddr", "settled")
    t = s.trunk("ddr")
    assert t["question"] == "Q1" and t["status"] == "answered"


def test_superseding_also_moves_off_the_question_it_closes(s):
    s.ask("ddr", "a second, left open")
    s.ask("ddr", "a third", supersedes="Q1")
    assert s.trunk("ddr")["status"] == "open"
