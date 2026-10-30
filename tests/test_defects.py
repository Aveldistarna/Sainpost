"""The measurement that could not be taken, and who is allowed to say why.

A defect here is not a backlog item. It exists only while a specific
pre-registered measurement is stopped by it, and it carries a hard split:
the party that is blocked writes what it SAW, the party that owns the
apparatus writes what was WRONG. Every test below names which half it
guards, because the split is the whole feature.
"""

import pytest

from sainpost.store import INVALIDATES, NoteError, Store


@pytest.fixture()
def s(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "escape routing under a 0.5mm BGA")
    st.ask("ddr", "why do U2's four byte lanes jam")
    st.start_project("router-impl", "the escape router itself")
    st.ask("router-impl", "does the router hold its invariants")
    yield st
    st.close()


def pre(st, project="ddr", **kw):
    args = dict(hypothesis="via price is too high to escape to another layer",
                why_now="A0 showed order does not matter",
                measure="sweep via_cost_mm 0.1..8.0, count joined spans",
                falsifier="joined-span count does not move across the sweep",
                apparatus="kicad 10.0.1, repair=False, stale=false confirmed")
    args.update(kw)
    return st.hypothesis(project, **args)


def file_one(st, **kw):
    args = dict(project="ddr",
                invocation="pcb_propose_board_route(board='u2.kicad_pcb', repair=True)",
                observed="Traceback ...\n  escape.py:88 in _frontage\n"
                         "TypeError: NoneType is not subscriptable",
                needed="a proposal object, so I can count joined spans",
                owner="router-impl", stopped=True)
    args.update(kw)
    return st.blocked(**args)


# -- BLOCKED is not a result ------------------------------------------------

def test_blocked_cannot_be_reached_through_result(s):
    """note_result records numbers. There are no numbers here, and letting
    one arrive this way would mean a front closed as blocked with nobody
    named to unblock it."""
    pre(s)
    with pytest.raises(NoteError) as e:
        s.result("ddr", "it crashed", "BLOCKED")
    assert "not a result" in str(e.value)
    assert "note_blocked" in str(e.value)


def test_a_report_needs_no_measurement_of_its_own(s):
    """Requiring a stopped measurement shut out exactly the reporter who most
    needs to be heard: somebody USING the apparatus rather than measuring with
    it, who therefore has nothing of their own to stop. A real one existed --
    another agent recording an investigation had thirteen questions, no
    attempts, and no way to report anything about the notebook it was using.

    The wishlist this list must not become is kept out by `invocation` and
    `observed` demanding verbatim text, not by that requirement. "It would be
    nice if" cannot be written into "what came back, verbatim"."""
    got = file_one(s)                      # no open attempt in ddr at all
    assert got["defect"] == "D1"
    assert "not a measurement that stopped" in got["blocked"]
    assert "ddr was on Q1" in got["inherited_from_the_attempt"][
        "where the reporter was"]


def test_a_report_still_has_to_be_something_that_happened(s):
    """The guard that actually does the work."""
    for blank in ("invocation", "observed"):
        with pytest.raises(NoteError) as e:
            file_one(s, **{blank: "  "})
        assert blank in str(e.value)


def test_a_report_says_where_the_reporter_was(s):
    """No attempt means nothing to inherit the rig from, and the owner still
    has to be able to find the moment. Read, not typed."""
    file_one(s)
    body = s.open("ddr", ["D1"])["nodes"][0]
    assert "ddr was on Q1" in body["blocked"]
    assert body["apparatus (inherited from the attempt)"] is None


def test_a_stopped_measurement_still_closes_as_blocked(s):
    """The original path is unchanged: when there IS an attempt, it closes."""
    pre(s)
    got = file_one(s)
    assert got["blocked"] == "ddr A1"
    assert s.open("ddr", ["A1"])["nodes"][0]["verdict"] == "BLOCKED"


def test_filing_frees_the_front(s):
    """Otherwise the project is held hostage to another project's schedule:
    one open attempt per project, and that one is waiting on somebody else."""
    pre(s)
    file_one(s)
    assert s._open_attempt(s._project_row("ddr")["id"]) is None
    pre(s, hypothesis="the pad frontage is blocked")     # refuses if it did not


def test_the_blocked_attempt_records_that_nothing_was_measured(s):
    """Its verdict says nothing about the hypothesis, and its result says so
    in words rather than leaving a plausible-looking blank."""
    pre(s)
    file_one(s)
    a = s.open("ddr", ["A1"])["nodes"][0]
    assert a["verdict"] == "BLOCKED"
    assert "not measured" in a["result (MEASURED)"]


# -- a false reading inside a measurement that went through -----------------
#
# R29. A seam inspection read a 0.1 mm step as a 138-degree crease, and it was
# filed after seven predictions and a control had all been measured. Filing
# closed every open attempt BLOCKED, "not measured", so the report recorded a
# finished measurement as one that never happened -- for good, since nothing
# here is edited -- and its numbers could only go back in as a note, rendered
# as INTERPRETATION.

SEAM = dict(invocation='inspect_seam(a="CenterFuselage", b="Spine")',
            observed='"crease_deg": {"max": 138.51, "at_mm": [5997.22, -473.7]}\n'
                     "the cross section there is a 0.111 mm step",
            needed="the step read as a step, not as a crease")


def test_with_an_attempt_to_touch_it_asks_what_the_failure_did_to_it(s):
    """Only the reporter knows whether a number came out, and either default
    is wrong for somebody. So nothing is assumed and nothing is written."""
    pre(s)
    with pytest.raises(NoteError) as e:
        file_one(s, stopped=None, owner="seam-tools")
    assert "stopped=true" in str(e.value) and "stopped=false" in str(e.value)
    assert s.open("ddr", ["A1"])["nodes"][0]["verdict"] == "OPEN"
    assert s.defects(closed=True)["defects"] == []
    assert s._project_row("seam-tools", required=False) is None, \
        "a refused call left a blank card for an owner nothing was filed against"


def test_with_nothing_to_touch_nothing_is_asked(s):
    got = file_one(s, stopped=None)            # no attempt open in ddr
    assert "not a measurement that stopped" in got["blocked"]


def test_a_false_reading_leaves_the_measurement_to_note_result(s):
    pre(s)
    got = file_one(s, stopped=False, **SEAM)
    assert got["a false reading in"] == "ddr A1"
    assert got["blocked"].startswith("nothing") and "A1 is still open" in got["blocked"]
    assert got["inherited_from_the_attempt"]["apparatus (the rig that broke)"] == \
        "kicad 10.0.1, repair=False, stale=false confirmed"
    closed = s.result("ddr", "(1) +0.000 mm (2) -0.10 mm; control not fired",
                      "CONFIRMED")
    assert closed["a reading in it was false"] == ["D1 -> router-impl [open]"], \
        "the verdict is checked against what is on record, beside the falsifier"
    a1 = s.open("ddr", ["A1"])["nodes"][0]
    assert a1["verdict"] == "CONFIRMED"
    assert a1["result (MEASURED)"].startswith("(1) +0.000 mm"), \
        "the numbers went in as a measurement, not as a note about one"


def test_the_reading_is_printed_wherever_the_verdict_is(s):
    """A verdict can rest on the reading -- the first one fired a falsifier --
    so it is read where the verdict is read, not only by opening the defect."""
    from sainpost.server import render_path, render_trunk
    pre(s)
    file_one(s, stopped=False, **SEAM)
    line = "a reading in it was false: D1 -> router-impl [open]"
    assert line in render_trunk(s.trunk("ddr")), "while the attempt is open"
    s.result("ddr", "(1) +0.000 mm", "FALSIFIED")
    assert line in render_trunk(s.trunk("ddr"))
    assert line in render_path(s.trail("ddr"))
    assert s.open("ddr", ["A1"])["nodes"][0]["a reading in it was false"] == \
        ["D1 -> router-impl [open]"]
    s.fixed("D1", "FIXED", cause="the step fell between samples 0.5 mm apart",
            change="sample across the seam at 0.05 mm",
            verify="inspect_seam(a='CenterFuselage', b='Spine')",
            invalidates="EVERY_MEASUREMENT_ON_THIS_RIG")
    assert "a reading in it was false: D1 -> router-impl [FIXED]" in \
        render_path(s.trail("ddr"))


def test_the_owner_reads_which_attempt_the_reading_was_in(s):
    pre(s)
    file_one(s, stopped=False, **SEAM)
    d = s.open("ddr", ["D1"])["nodes"][0]
    assert d["a false reading in"].startswith("ddr A1  via price")
    assert d["blocked"] == "ddr (no measurement stopped)"
    assert d["apparatus (inherited from the attempt)"].startswith("kicad 10.0.1")


def test_the_two_calls_can_come_in_either_order(s):
    """note_result first was the only order that kept the numbers, and
    nothing said so. A reading can be filed against a closed attempt too,
    and its verdict is left as it is."""
    pre(s)
    s.result("ddr", "(1) +0.000 mm", "CONFIRMED")
    for said in (None, True):
        with pytest.raises(NoteError) as e:
            file_one(s, attempt="A1", stopped=said, **SEAM)
        assert "stopped=false" in str(e.value)
    got = file_one(s, attempt="A1", stopped=False, **SEAM)
    assert got["a false reading in"] == "ddr A1"
    assert "closed as CONFIRMED" in got["blocked"]
    assert "note_postscript" in got["blocked"]
    a1 = s.open("ddr", ["A1"])["nodes"][0]
    assert a1["verdict"] == "CONFIRMED" and a1["result (MEASURED)"] == "(1) +0.000 mm"


def test_a_refiled_reading_keeps_its_link_and_stops_nothing(s):
    pre(s)
    file_one(s, stopped=False, **SEAM)
    s.fixed("D1", "NOT_ACTIONABLE", cause="missing: which of the three runs")
    again = file_one(s, supersedes="D1", stopped=None, **SEAM)
    assert again["a false reading in"] == "ddr A1"
    assert s.open("ddr", ["A1"])["nodes"][0]["verdict"] == "OPEN"


def test_a_reading_names_its_arm_when_several_are_open(s):
    pre(s)
    pre(s, hypothesis="the pad frontage is blocked")
    with pytest.raises(NoteError) as e:
        file_one(s, stopped=False, **SEAM)
    assert "say which" in str(e.value).lower()
    assert "closes" not in str(e.value), "this call closes nothing"
    got = file_one(s, stopped=False, attempt="A2", **SEAM)
    assert got["a false reading in"] == "ddr A2"
    assert [a["verdict"] for a in s.trunk("ddr")["attempts"]] == ["OPEN", "OPEN"]


# -- the reporter writes observation, and only observation -----------------

def test_the_reporter_has_nowhere_to_put_a_cause(s):
    """Not a docstring convention -- there is no parameter. A cause asserted
    without a measurement, handed to the party that owns the code as its
    starting point, is this record's own failure mode crossing an agent
    boundary."""
    import inspect
    params = set(inspect.signature(Store.blocked).parameters)
    assert not (params & {"cause", "fix", "suggestion", "where", "diagnosis"})
    assert {"invocation", "observed", "needed", "owner"} <= params


def test_the_three_observations_are_required(s):
    pre(s)
    for blank in ("invocation", "observed", "needed"):
        with pytest.raises(NoteError) as e:
            file_one(s, **{blank: "   "})
        assert blank in str(e.value)
        assert "no field for the cause" in str(e.value)


def test_the_owner_inherits_the_rig_without_the_reporter_restating_it(s):
    """Half of what the owner needs is already in the attempt: which rig, what
    was being measured, and why anyone cares. Restating it by hand is how the
    two copies drift apart."""
    pre(s)
    got = file_one(s)
    inherited = got["inherited_from_the_attempt"]
    assert inherited["apparatus (the rig that broke)"] == \
        "kicad 10.0.1, repair=False, stale=false confirmed"
    assert inherited["measure"].startswith("sweep via_cost_mm")
    assert inherited["hypothesis"].startswith("via price")


def test_the_defect_names_who_owns_the_fix_and_who_is_stopped(s):
    pre(s)
    got = file_one(s)
    assert got["defect"] == "D1"
    assert got["owner"] == "router-impl" and got["reported_by"] == "ddr"
    assert got["blocked"] == "ddr A1"


def test_an_owner_nobody_has_started_yet_gets_a_blank_card_not_a_guess(s):
    """It used to refuse, which forced the reporter to run note_start for
    another team: writing a description of an investigation it knows nothing
    about, and picking a repo for them. An agent did exactly that, wrote a
    disclaimer into the description to cope, and pointed out that the tool had
    required of it the one thing this record exists to prevent."""
    pre(s)
    got = file_one(s, owner="nobody-here-yet")
    assert got["owner"] == "nobody-here-yet"
    row = s._project_row("nobody-here-yet")
    assert row["stub"] == 1 and row["description"] == "" and row["repo"] == ""


def test_the_owner_writes_their_own_card_when_they_arrive(s):
    """Not an edit: it is the first time that project's own team has spoken."""
    pre(s)
    file_one(s, owner="corridor-team")           # nobody has started it
    got = s.start_project("corridor-team", "the escape router itself")
    assert "referral stub" in got["adopted"]
    assert s._project_row("corridor-team")["description"] == "the escape router itself"

    with pytest.raises(NoteError) as e:
        s.start_project("corridor-team", "again")
    assert "already exists" in str(e.value)


def test_a_defect_still_needs_somebody_to_own_it(s):
    pre(s)
    with pytest.raises(NoteError) as e:
        file_one(s, owner="  ")
    assert "needs an owner" in str(e.value)
    assert s._open_attempt(s._project_row("ddr")["id"]) is not None


# -- the owner writes the cause, once --------------------------------------

def test_cause_is_required_on_every_resolution(s):
    pre(s)
    file_one(s)
    for r in ("FIXED", "NOT_REPRODUCIBLE", "NOT_ACTIONABLE", "NOT_A_DEFECT"):
        with pytest.raises(NoteError) as e:
            s.fixed("D1", r, cause="  ")
        assert "cause is required" in str(e.value)


def test_fixed_will_not_close_without_what_the_blocked_party_needs(s):
    pre(s)
    file_one(s)
    with pytest.raises(NoteError) as e:
        s.fixed("D1", "FIXED", cause="_frontage returned None for edge pads")
    for field in ("change", "verify", "invalidates"):
        assert field in str(e.value)


def test_invalidates_is_a_closed_vocabulary(s):
    """It is written on every fix, and prose written on every fix stops being
    read. The point is that a number taken through a broken rig cannot stay
    in the record unexamined."""
    pre(s)
    file_one(s)
    with pytest.raises(NoteError) as e:
        s.fixed("D1", "FIXED", cause="c", change="ch", verify="v",
                invalidates="probably fine")
    assert "invalidates must be one of" in str(e.value)
    # It asks about OTHER measurements, never the blocked one -- which by
    # definition produced no number, so a value naming it could not mean
    # anything. A cold agent picked it and said so.
    assert set(INVALIDATES) == {"NOTHING", "EVERY_MEASUREMENT_ON_THIS_RIG"}


def test_not_reproducible_must_say_what_was_run(s):
    """It passing there and failing here is a difference between two rigs --
    an apparatus finding. 'Works for me' is not one."""
    pre(s)
    file_one(s)
    with pytest.raises(NoteError) as e:
        s.fixed("D1", "NOT_REPRODUCIBLE", cause="passes on this machine")
    assert "verify" in str(e.value)


def test_closing_tells_the_blocked_party_what_to_run_before_measuring_again(s):
    pre(s)
    file_one(s)
    got = s.fixed("D1", "FIXED",
                  cause="_frontage returned None for pads on the board edge",
                  change="return an empty corridor list instead of None",
                  verify="pcb_propose_board_route(board='u2.kicad_pcb', repair=True)",
                  invalidates="EVERY_MEASUREMENT_ON_THIS_RIG")
    assert got["tell"] == "ddr"
    assert got["verify (run this before measuring again)"].startswith("pcb_propose")
    assert got["invalidates"] == "EVERY_MEASUREMENT_ON_THIS_RIG"


def test_a_defect_closes_once_and_is_never_edited(s):
    pre(s)
    file_one(s)
    s.fixed("D1", "NOT_A_DEFECT", cause="repair=True needs a board loaded first")
    with pytest.raises(NoteError) as e:
        s.fixed("D1", "FIXED", cause="x", change="y", verify="z",
                invalidates="NOTHING")
    assert "append-only" in str(e.value)
    assert "supersedes=D1" in str(e.value)


# -- the round trip, without a comment thread ------------------------------

def test_what_comes_back_unactionable_is_refiled_not_edited(s):
    """The one exchange a bug report actually needs -- 'I cannot act on this'
    -- as a new node with an edge back, the same shape a re-run of a
    falsified attempt takes."""
    pre(s)
    file_one(s)
    s.fixed("D1", "NOT_ACTIONABLE",
            cause="missing: which board file, and whether it was loaded first")
    again = file_one(s, supersedes="D1",
                     invocation="pcb_load_board('u2.kicad_pcb'); "
                                "pcb_propose_board_route(repair=True)",
                     observed="same TypeError at escape.py:88")
    assert again["defect"] == "D2" and again["supersedes"] == "D1"
    assert again["blocked"] == "ddr A1", "it still points at the stopped measurement"


def test_refiling_needs_no_second_front_to_burn(s):
    """The attempt was closed when the first one was filed. Requiring a fresh
    open attempt to re-file would mean opening one you cannot measure."""
    pre(s)
    file_one(s)
    s.fixed("D1", "NOT_ACTIONABLE", cause="missing the board file")
    assert s._open_attempt(s._project_row("ddr")["id"]) is None
    file_one(s, supersedes="D1")


def test_an_open_defect_is_not_refiled(s):
    pre(s)
    file_one(s)
    with pytest.raises(NoteError) as e:
        file_one(s, supersedes="D1")
    assert "still open" in str(e.value)


def test_the_retry_is_a_new_attempt_pointing_at_the_blocked_one(s):
    pre(s)
    file_one(s)
    s.fixed("D1", "FIXED", cause="None for edge pads", change="return []",
            verify="rerun the proposal", invalidates="EVERY_MEASUREMENT_ON_THIS_RIG")
    again = pre(s, why_now="D1 was fixed; A1 never ran", prompted_by="A1")
    assert again["prompted_by"] == "A1"


# -- where it is visible ---------------------------------------------------

def test_the_trunk_shows_both_directions_of_blockage(s):
    """Why your own front is empty, and whose front you are the reason for."""
    pre(s)
    file_one(s)
    mine = s.trunk("ddr")
    assert mine["blocked_on"] and "router-impl" in mine["blocked_on"][0]
    assert mine["waiting_on_you"] == []

    theirs = s.trunk("router-impl")
    assert theirs["waiting_on_you"] and "ddr" in theirs["waiting_on_you"][0]
    assert theirs["blocked_on"] == []


def test_a_closed_defect_leaves_the_trunk(s):
    pre(s)
    file_one(s)
    s.fixed("D1", "NOT_A_DEFECT", cause="a board has to be loaded first")
    assert s.trunk("ddr")["blocked_on"] == []
    assert s.trunk("router-impl")["waiting_on_you"] == []


def test_the_list_is_machine_wide_and_carries_only_live_blockage(s):
    pre(s)
    file_one(s)
    assert len(s.defects()["defects"]) == 1
    s.fixed("D1", "FIXED", cause="c", change="ch", verify="v", invalidates="NOTHING")
    assert s.defects()["defects"] == []
    assert len(s.defects(closed=True)["defects"]) == 1


def test_the_list_can_be_narrowed_to_one_project_in_both_directions(s):
    pre(s)
    file_one(s)
    assert len(s.defects("router-impl")["defects"]) == 1     # owes the fix
    assert len(s.defects("ddr")["defects"]) == 1             # is stopped by it


def test_open_gives_the_body_and_labels_which_side_wrote_what(s):
    pre(s)
    file_one(s)
    s.fixed("D1", "FIXED", cause="_frontage returned None for edge pads",
            change="return []", verify="rerun it", invalidates="NOTHING")
    d = s.open("ddr", ["D1"])["nodes"][0]
    assert d["observed"].startswith("Traceback")
    assert d["cause (found by the owner)"] == "_frontage returned None for edge pads"
    assert d["apparatus (inherited from the attempt)"].startswith("kicad 10.0.1")


def test_the_trunk_stays_one_line_per_attempt_when_a_traceback_arrives(s):
    """A pasted traceback is the whole point of `observed`, and it would swamp
    the trunk if it were copied onto the attempt. It lives in the defect; the
    attempt points at it."""
    pre(s)
    file_one(s)
    line = s.trunk("ddr")["attempts"][0]["result"]
    assert "\n" not in line
    assert "D1" in line and "apparatus failed" in line


def test_the_one_line_summary_is_the_error_not_the_word_traceback(s):
    """The first line of a traceback is the one line of it that says nothing."""
    pre(s)
    file_one(s)
    assert "TypeError" in s.trunk("router-impl")["waiting_on_you"][0]
    assert "most recent call last" not in s.trunk("router-impl")["waiting_on_you"][0]


def test_filing_against_your_own_project_is_sanctioned(s):
    """A solo investigator's crash is still a measurement that did not happen.
    note_result forbids BLOCKED in loud terms, so if this were also refused
    there would be no honest way to close the attempt at all -- a cold agent
    did exactly this, and reported doing it against the tool's stated intent."""
    pre(s)
    got = file_one(s, owner="ddr")
    assert got["owner"] == "ddr" and got["reported_by"] == "ddr"
    mine = s.trunk("ddr")
    assert mine["blocked_on"] and mine["waiting_on_you"]
    s.fixed("D1", "FIXED", cause="None for edge pads", change="return []",
            verify="rerun it", invalidates="NOTHING")


def test_a_bug_in_a_tool_you_are_only_using_closes_none_of_your_arms(s):
    """The tool's own description promises this: report a bug in a tool you
    are merely using, and nothing of yours is closed. With arms open it was
    unreachable -- omitting the label asked which arm this closes, and naming
    one either closed a measurement the tool had not stopped or filed the bug
    as a false reading inside a measurement it had nothing to do with. An
    agent with two arms open filed nothing at all, and asked for a way."""
    pre(s)
    pre(s, hypothesis="the pad frontage is blocked, not the price")
    with pytest.raises(NoteError) as e:
        file_one(s, stopped=None, owner="sainpost-itself")
    assert "attempt='none'" in str(e.value), "the way out is named where it is needed"

    got = file_one(s, attempt="none", stopped=None, owner="sainpost-itself")
    assert got["defect"] == "D1"
    assert [a["attempt"] for a in s.trunk("ddr")["attempts"]
            if a["verdict"] == "OPEN"] == ["A1", "A2"], "both arms still running"
    body = s.open("ddr", ["D1"])["nodes"][0]
    assert body["blocked"].startswith("ddr was on Q1"), \
        "no attempt to inherit the rig from, so where they were is read from the record"


def test_none_and_stopped_together_are_refused(s):
    """stopped says what this did to a measurement of yours. Saying there is
    none and then answering that question is two different reports."""
    pre(s)
    with pytest.raises(NoteError) as e:
        file_one(s, attempt="none", stopped=True)
    assert "nothing to apply to" in str(e.value)


# -- one question back, and one answer -------------------------------------

def test_the_owner_can_ask_without_closing_anything(s):
    """There was no way to do this. The levers were all resolutions, so an
    agent that needed to ask "what is this flag even supposed to do?" had to
    choose between NOT_ACTIONABLE -- wrong, the crash was plainly actionable
    and plainly theirs -- and silence."""
    pre(s)
    file_one(s)
    got = s.query("D1", "router-impl",
                  "is repair meant to recover a corridor, or is the flag "
                  "aspirational?")
    assert got["of"] == "ddr" and "did not close it" in got["still"]
    assert len(s.defects()["defects"]) == 1
    body = s.open("ddr", ["D1"])["nodes"][0]
    assert body["router-impl asks"].startswith("is repair meant")
    assert body["answered"] == "(not yet)"


def test_the_reporter_answers_and_it_still_does_not_close(s):
    pre(s)
    file_one(s)
    s.query("D1", "router-impl", "what should repair return for a pad with no corridor?")
    got = s.reply("D1", "ddr", "nothing in board.py carries a length; there is no source "
                        "to recover one from")
    assert got["of"] == "router-impl"
    assert s.open("ddr", ["D1"])["nodes"][0]["answered"].startswith(
        "nothing in board.py")
    assert len(s.defects()["defects"]) == 1


def test_it_is_one_exchange_and_not_a_thread(s):
    """A second question means the report itself was wrong, and re-filing
    already exists for that."""
    pre(s)
    file_one(s)
    s.query("D1", "router-impl", "first")
    with pytest.raises(NoteError) as e:
        s.query("D1", "router-impl", "second")
    assert "NOT_ACTIONABLE" in str(e.value)
    s.reply("D1", "ddr", "answered")
    with pytest.raises(NoteError):
        s.reply("D1", "ddr", "again")


def test_there_is_nothing_to_reply_to_until_something_is_asked(s):
    pre(s)
    file_one(s)
    with pytest.raises(NoteError) as e:
        s.reply("D1", "ddr", "here you go")
    assert "has not asked anything" in str(e.value)


def test_a_closed_defect_takes_no_more_questions(s):
    pre(s)
    file_one(s)
    s.fixed("D1", "NOT_A_DEFECT", cause="a board has to be loaded first")
    with pytest.raises(NoteError) as e:
        s.query("D1", "router-impl", "too late?")
    assert "supersedes=D1" in str(e.value)


def test_either_side_may_ask(s):
    """It was owner-to-reporter only, on the strength of one agent needing that
    direction -- and the very next agent was the reporter, read the tool's
    description, found its own situation named in it and the door pointed the
    wrong way. `needed` is a one-shot at filing time and cannot carry a
    question only the owner can answer."""
    pre(s)
    file_one(s)
    got = s.query("D1", "ddr", "what is MAX_DETOUR_MM supposed to be?")
    assert got["of"] == "router-impl"
    body = s.open("ddr", ["D1"])["nodes"][0]
    assert body["ddr asks"].startswith("what is MAX_DETOUR_MM")
    assert s.reply("D1", "router-impl", "nobody knows; it was never written down"
                   )["of"] == "ddr"


def test_you_cannot_answer_your_own_question(s):
    pre(s)
    file_one(s)
    s.query("D1", "ddr", "what is it supposed to do?")
    with pytest.raises(NoteError) as e:
        s.reply("D1", "ddr", "I know, actually")
    assert "cannot answer yourself" in str(e.value)


def test_a_third_party_has_no_business_in_someone_elses_defect(s):
    pre(s)
    file_one(s)
    s.start_project("unrelated", "")
    with pytest.raises(NoteError) as e:
        s.query("D1", "unrelated", "just passing")
    assert "is neither" in str(e.value)


def test_an_older_notebook_grows_out_of_the_not_null_without_losing_a_row(tmp_path):
    """defects.attempt_id was NOT NULL and had to stop being. SQLite cannot
    relax a constraint in place, so this is the one migration that rebuilds a
    table rather than adding to it -- every row is copied and the count is
    verified before the old table is dropped. No recorded fact changes; only
    what the schema will accept next."""
    import sqlite3
    db = tmp_path / "old.db"
    st = Store(db)
    st.start_project("a", "")
    st.start_project("b", "")
    st.ask("a", "q")
    st.hypothesis("a", hypothesis="h", why_now="", measure="m", falsifier="f",
                  apparatus="ap")
    st.blocked("a", invocation="what was run", observed="what came back",
               needed="n", owner="b", stopped=True)
    cols = [r["name"] for r in st.db.execute("PRAGMA table_info(defects)")
            if r["name"] != "id"]
    st.close()

    c = sqlite3.connect(db)                              # put NOT NULL back
    decl = ", ".join(f"{n} INTEGER NOT NULL" if n == "attempt_id" else n
                     for n in cols)
    c.execute("ALTER TABLE defects RENAME TO d2")
    c.execute(f"CREATE TABLE defects (id INTEGER PRIMARY KEY, {decl})")
    c.execute(f"INSERT INTO defects (id, {', '.join(cols)})"
              f" SELECT id, {', '.join(cols)} FROM d2")
    c.execute("DROP TABLE d2")
    c.commit()
    c.close()

    again = Store(db)
    assert [r["notnull"] for r in again.db.execute("PRAGMA table_info(defects)")
            if r["name"] == "attempt_id"] == [0]
    d = again.open("a", ["D1"])["nodes"][0]
    assert d["invocation"] == "what was run" and d["observed"] == "what came back"
    assert {x[0] for x in again.db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'defects%'"
    )} == {"defects_by_owner", "defects_by_reporter", "defects_by_seq"}
    again.close()


def test_an_older_notebook_grows_the_column_a_false_reading_needs(tmp_path):
    """Every notebook on a machine predates reading_in, and every session opens
    it: a column read and never added would stop the server on the first
    defect it rendered."""
    import sqlite3
    db = tmp_path / "old.db"
    st = Store(db)
    st.start_project("a", "")
    st.start_project("b", "")
    st.ask("a", "q")
    st.hypothesis("a", hypothesis="h", why_now="", measure="m", falsifier="f",
                  apparatus="ap")
    st.blocked("a", invocation="what was run", observed="what came back",
               needed="n", owner="b", stopped=True)
    cols = [r["name"] for r in st.db.execute("PRAGMA table_info(defects)")
            if r["name"] not in ("id", "reading_in")]
    st.close()

    c = sqlite3.connect(db)                  # the table as it was before
    c.execute("ALTER TABLE defects RENAME TO d2")
    c.execute(f"CREATE TABLE defects (id INTEGER PRIMARY KEY, {', '.join(cols)})")
    c.execute(f"INSERT INTO defects (id, {', '.join(cols)})"
              f" SELECT id, {', '.join(cols)} FROM d2")
    c.execute("DROP TABLE d2")
    c.commit()
    c.close()

    again = Store(db)
    assert "reading_in" in {r["name"] for r in
                            again.db.execute("PRAGMA table_info(defects)")}
    assert again.open("a", ["D1"])["nodes"][0]["blocked"].startswith("a A1")
    again.close()


def test_the_schema_builds_every_table_before_the_migration_runs(tmp_path):
    """Indexes name columns, so building them before the missing columns are
    added made opening an older notebook fail on the first index over a column
    added since -- the schema refusing to open the database it was meant to
    grow. Splitting at the first CREATE INDEX instead of per statement left
    every table declared after it unbuilt, which was worse."""
    st = Store(tmp_path / "n.db")
    tables = {r[0] for r in st.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"projects", "questions", "attempts", "defects", "postscripts",
            "attempt_notes"} <= tables
    st.close()
