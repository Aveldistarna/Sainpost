"""The whole path of trial and error, seen at once.

`trunk` answers "where am I" and stays small by showing one question. That is
the wrong shape for the other thing an agent arrives wanting: what has
already been ruled out here. Three cold agents in a row rebuilt that by hand,
calling trunk once per question after guessing the labels -- and a FALSIFIED
row is the most valuable kind in this record, worth nothing unread.
"""

import pytest

from sainpost.server import render_path
from sainpost.store import NoteError, Store


@pytest.fixture()
def s(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "escape routing")
    st.ask("ddr", "why do the four byte lanes jam")
    yield st
    st.close()


def run(st, hyp, result, verdict, headline="", hyp_headline="", **kw):
    args = dict(hypothesis=hyp, why_now="", measure="m",
                falsifier="f", apparatus="a", headline=hyp_headline or None)
    args.update(kw)
    st.hypothesis("ddr", **args)
    st.result("ddr", result, verdict, headline=headline or None)


def test_a_project_with_nothing_in_it_says_so(s):
    t = s.trail("ddr")
    assert t["tally"] == "no attempt has reached a verdict; 1 still open"
    assert "(nothing tried under this one)" in render_path(t)


def test_the_dead_ends_are_pulled_out_of_the_chronology(s):
    """In a long project they are buried in the middle of the trail, and they
    are the rows that stop the next agent spending the days that bought them."""
    run(s, "via price is too high", "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    run(s, "the pad frontage is blocked", "5 of 8 blocked", "CONFIRMED",
        why_now="A1 was falsified", prompted_by="A1")
    t = s.trail("ddr")
    assert [a["attempt"] for a in t["closed_off"]] == ["A1"]
    assert [a["attempt"] for a in t["standing"]] == ["A2"]
    text = render_path(t)
    assert "Do not re-derive" in text
    assert text.index("CLOSED OFF") < text.index("THE PATH"), \
        "the digest is what an arriving agent reads; it goes first"


def test_the_numbers_that_closed_them_come_along(s):
    """'MAX_DETOUR_MM is defined somewhere' on its own does not tell anyone it
    is not."""
    run(s, "MAX_DETOUR_MM is defined somewhere", "named once in a docstring, "
        "defined in no scope", "FALSIFIED")
    assert "defined in no scope" in render_path(s.trail("ddr"))


def test_what_is_unsettled_is_not_filed_with_what_is_dead(s):
    """BLOCKED, INCONCLUSIVE and OPEN each mean something different, and none
    of them means "ruled out". Retiring them would close live work."""
    run(s, "the sweep varies with cost", "no clear trend", "INCONCLUSIVE")
    s.hypothesis("ddr", hypothesis="repair raises the count", why_now="A1",
                 prompted_by="A1", measure="m", falsifier="f", apparatus="a")
    s.start_project("router-impl", "")
    s.blocked("ddr", invocation="sweep --repair", observed="TypeError: boom",
              needed="a count", owner="router-impl", stopped=True)
    t = s.trail("ddr")
    assert t["closed_off"] == [] and t["standing"] == []
    assert [a["attempt"] for a in t["open_now"]] == ["A1", "A2"]
    assert "D1 -> router-impl" in render_path(t)


def test_the_reformulation_chain_is_the_headline(s):
    """Reformulating the question is usually the actual finding, so it is
    visible before any attempt is -- and ONLY where it happened. The headline
    used to print every question in the project as one arrow chain, "the
    question moved: Q1* -> Q2 -> Q3", over questions that had superseded
    nothing. A reader who trusted it read a project as one long
    reformulation, with the earlier questions as abandoned framings; the
    reporter that found it was looking at eight such questions, none of
    which had replaced any other."""
    run(s, "via price is too high", "6/8 unchanged", "FALSIFIED")
    s.answer("ddr", "not a cost problem")
    s.ask("ddr", "what blocks the pad frontage")
    s.ask("ddr", "is there a corridor model at all", supersedes="Q2")
    text = render_path(s.trail("ddr"))
    assert "reformulated:  Q2 -> Q3" in text
    assert "Q1" not in text.split("THE PATH")[0].split("\n")[2], \
        "Q1 replaced nothing and belongs in no chain"
    # "[answered" and not "[answered]": the bracket goes on to say whose the
    # answer is (tests/test_whose_answer.py).
    assert "[became Q3]" in text and "[answered, not endorsed by the user]" in text


def test_the_path_is_a_tree_when_questions_stand_under_one_another(s):
    """Printed flat, a requirement reads as an unrelated question -- or as
    one more step in a reformulation, which is what the digest called it."""
    s.answer("ddr", "not the lanes")
    s.ask("ddr", "what does this paper claim")
    s.ask("ddr", "it must explain the failures too", parent="Q2")
    s.ask("ddr", "which material shows that", parent="Q3")
    t = s.trail("ddr")
    assert [(q["question"], q["depth"]) for q in t["trail"]] == \
        [("Q1", 0), ("Q2", 0), ("Q3", 1), ("Q4", 2)]
    assert t["reformulated"] == [], "nothing here replaced anything"
    text = render_path(t)
    lines = {ln.strip().split("  ")[0]: len(ln) - len(ln.lstrip())
             for ln in text.splitlines() if ln.strip().startswith("Q")}
    assert lines["Q2"] < lines["Q3"] < lines["Q4"], "each sits under what it serves"


def test_every_attempt_appears_exactly_once_in_the_chronology(s):
    run(s, "one", "r1", "FALSIFIED")
    run(s, "two", "r2", "CONFIRMED", why_now="A1", prompted_by="A1")
    t = s.trail("ddr")
    seen = [a["attempt"] for q in t["trail"] for a in q["attempts"]]
    assert seen == ["A1", "A2"]


# -- what one reply can carry ----------------------------------------------

def crowd(st, questions=12, each=8):
    """A project too big for one reply: 96 attempts under 12 questions, each
    node as long as the record's real ones."""
    body = "この試行で測ったことを、記録の実物と同じ長さで書いておく。" * 8
    pad = "、そしてこの続きが実物の見出しと同じ長さになるまで書かれている" * 2
    for q in range(questions):
        st.ask("ddr", f"Q{q} " + body, headline=f"問い{q}: 何が配線を塞いでいるか{pad}"[:96])
        for a in range(each):
            st.hypothesis("ddr", hypothesis=body,
                          headline=f"仮説{q}-{a}: 価格が高すぎる{pad}"[:96],
                          why_now="the one before it", measure="m",
                          falsifier="f", apparatus="a")
            st.result("ddr", body, "FALSIFIED" if a % 2 else "CONFIRMED",
                      headline=f"結果{q}-{a}: 数は動かなかった{pad}"[:96])
        st.answer("ddr", body, headline=f"答え{q}: 価格ではなかった{pad}"[:96])


def test_a_trail_too_big_for_one_reply_becomes_the_map_of_itself(s):
    """A project's record outgrows one reply long before it outgrows the
    client's limit, and 28 KB of trail spent on "where does this project
    stand" is 28 KB the work does not get. The same move the record itself
    makes: a line that says what is there, with the body one call below."""
    crowd(s)
    text = render_path(s.trail("ddr"))
    assert len(text.encode()) <= 6_000, len(text.encode())
    assert "the map of it" in text and "note_path('ddr', question=" in text
    assert "note_search(" in text, "and how to find a branch by what it is about"
    assert "more question(s), by label" in text


def test_a_small_project_still_gets_the_whole_trail(s):
    """The rule is one reply's worth, not a shape imposed on everything: a
    project with three attempts has nothing to page through."""
    run(s, "via price is too high", "6/8 unchanged", "FALSIFIED")
    text = render_path(s.trail("ddr"))
    assert "CLOSED OFF" in text and "6/8 unchanged" in text
    assert "the map of it" not in text


def test_the_map_leads_with_where_the_work_is(s):
    crowd(s, questions=8, each=6)
    s.ask("ddr", "what is left to route", headline="何が残っているか")
    s.hypothesis("ddr", hypothesis="the last two are the frontage", why_now="w",
                 measure="m", falsifier="f", apparatus="a")
    text = render_path(s.trail("ddr"))
    now = [ln for ln in text.splitlines() if ln.startswith("  NOW")]
    assert len(now) == 1 and s.trunk("ddr")["question"] in now[0], now
    assert "1 OPEN" in now[0], "and what is running under it"


def test_a_branch_too_big_for_one_reply_names_its_attempts(s):
    """Counted and not named, there is nothing left to open: a branch is
    usually one question, and its attempts are its content."""
    crowd(s, questions=1, each=60)
    text = render_path(s.trail("ddr", "Q2"))
    assert len(text.encode()) <= 6_000
    assert "A30" in text and "FALSIFIED" in text
    assert "note_open('ddr', 'A12,Q7')" in text


def test_each_attempt_is_told_once(s):
    """The digest says what it found; the tree says where it sits. Printing
    the hypothesis in both put 275 attempts through twice."""
    run(s, "via price is too high", "6/8 unchanged", "FALSIFIED")
    text = render_path(s.trail("ddr"))
    assert text.count("via price is too high") == 1
    digest, tree = text.split("THE PATH")
    assert "A1   Q1" in digest, "the digest names the question it sits under"
    assert "A1" not in tree and "1 attempt(s): 1 FALSIFIED" in tree


def test_a_branch_can_be_read_on_its_own(s):
    crowd(s, questions=3, each=2)
    whole = render_path(s.trail("ddr"))
    branch = render_path(s.trail("ddr", "Q3"))
    assert "one branch: Q3" in branch
    assert "\n    Q2  " in whole and "\n    Q2  " not in branch
    assert len(branch.encode()) < len(whole.encode())


def test_the_edges_survive_a_question_boundary(s):
    """prompted_by points at the result that sent you here, which is often
    under the question before this one. That edge is the path."""
    run(s, "via price is too high", "6/8 unchanged", "FALSIFIED")
    s.answer("ddr", "not a cost problem")
    s.ask("ddr", "what blocks the pad frontage")
    run(s, "the inner pads have no frontage", "5 of 8 blocked", "CONFIRMED",
        why_now="A1 was falsified", prompted_by="A1")
    assert "<-A1" in render_path(s.trail("ddr"))


def test_it_stays_one_line_per_node(s):
    """Bodies come from note_open, as everywhere. A traceback pasted into a
    result must not turn this into a dump."""
    s.hypothesis("ddr", hypothesis="repair works", why_now="", measure="m",
                 falsifier="f", apparatus="a")
    s.result("ddr", "Traceback:\n  a\n  b\n  c\nValueError: no\n" + "x" * 400,
             "INCONCLUSIVE", headline="ValueError: no -- the rig never ran")
    for line in render_path(s.trail("ddr")).splitlines():
        assert len(line) < 140, line


def test_the_repo_is_named_because_the_path_is_about_that_code(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "", repo=str(tmp_path))
    st.ask("ddr", "q")
    assert str(tmp_path) in render_path(st.trail("ddr"))
    st.close()


def test_an_unknown_project_lists_the_ones_that_exist(s):
    with pytest.raises(NoteError) as e:
        s.trail("nope")
    assert "ddr" in str(e.value)


def test_the_headline_counts_questions_too(s):
    """Counting only attempt verdicts opened a project holding thirteen
    answered questions -- and the measurements written up inside them -- with
    "nothing yet", saying the opposite of what it holds to the reader who has
    not scrolled yet. Reported from outside, with this project's own row as
    the second example."""
    s.answer("ddr", "settled without a pre-registered attempt")
    s.ask("ddr", "and another, still open")
    t = s.trail("ddr")
    assert "1 question(s) answered" in t["tally"]
    assert "1 still open" in t["tally"]
    assert "nothing yet" not in render_path(t)


def test_the_bodies_are_one_line_here_as_the_rule_already_said(s):
    """"Still one line per node; bodies come from note_open" was written in
    the manual two lines from the code that printed whole answers. On the
    project that hit it, answers and postscripts were 94% of the render and
    it reached 65,177 bytes against a 64 KiB tool-result ceiling -- 359 bytes
    of headroom, one answer from going over, and the client truncates rather
    than refuses, so a reader would have got a path stopping mid-answer with
    nothing saying so."""
    s.answer("ddr", "settled. " + "そのうえで詳細を述べると、" * 200,
             headline="settled: the corridor model was missing entirely")
    s.postscript("ddr", "Q1", "later. " + "補足を続けると、" * 200,
                 headline="later: the corridor model turned out to exist")
    text = render_path(s.trail("ddr"))
    assert len(text.encode()) < 4000, "the body does not come along"
    for line in text.splitlines():
        assert len(line) < 160, line
    assert "the corridor model was missing" in text, "its headline does"


def test_it_says_how_much_was_left_out_and_how_to_get_it(s):
    """The reporter's own design, arrived at by hitting this six times in
    another project: name every entry, let the caller ask for specific ones
    in full, and always say how many were left out. It applies to what has
    no headline -- rows written before headlines existed -- because
    everything written since carries its own line."""
    s.answer("ddr", "settled")
    s.db.execute("INSERT INTO postscripts (question_id, text, created_at)"
                 " SELECT id, ?, '2026-09-01T00:00:00+09:00' FROM questions"
                 " WHERE seq=1", ("x" * 4000,))            # an older server's row
    s.db.commit()
    text = render_path(s.trail("ddr"))
    assert "characters in all" in text and "4," in text
    assert "note_open" in text and "never truncated" in text
    assert "x" * 200 not in text


def test_a_hypothesis_is_one_line_here_too(s):
    """Not reported: found while checking the fix for the notes, in the same
    view, on the same project. The median hypothesis in this notebook is 224
    characters and the longest 2,028; forty of them printed whole is the
    trail nobody reads."""
    run(s, "the price never reaches the computation, " + "and here is why " * 40,
        "6/8 unchanged", "FALSIFIED",
        hyp_headline="the price never reaches the computation")
    text = render_path(s.trail("ddr"))
    assert "the price never reaches the computation" in text
    assert text.count("and here is why") < 10
    assert max(len(ln) for ln in text.splitlines()) < 200


def test_a_note_on_an_attempt_is_one_line_here_too(s):
    """It says a measurement was invalid and why, which runs long by nature.
    One of them was 760 characters and buried the tree it sat in."""
    run(s, "via price is too high", "6/8 unchanged", "FALSIFIED")
    s.postscript("ddr", "A1", "the 6/8 came off a rig that double-counted.\n"
                 + "- one more line of the reasoning\n" * 20 + "AND-THE-LAST-WORD",
                 headline="the 6/8 came off a rig that double-counted")
    text = render_path(s.trail("ddr"))
    assert "came off a rig that double-counted" in text, "the finding survives"
    assert "AND-THE-LAST-WORD" not in text
    assert max(len(ln) for ln in text.splitlines()) < 200
    whole = s.open("ddr", ["A1"])["nodes"][0]["learned later"][0]["text"]
    assert whole.endswith("AND-THE-LAST-WORD"), "note_open keeps it all"


def test_a_line_with_no_spaces_is_cut_at_the_width_not_at_its_first_space(s):
    """Where there is no headline -- a notebook written before they existed
    -- the line is still a cut, and the cut backed up to the last space.
    A Japanese line has none: the only space in "[R1] 設計に要る構造（…" is
    after the tag, so a 97-character question came back as "[R1]", a tree of
    them each showing nothing but its label."""
    text = ("[R1] 設計に要る構造（理由・公差付きの寸法・動き・由来）は、エージェントの観測"
            "（画像認識の出力・製造用の設計ファイル）に含まれていないか。"
            "見た目のように観測の中に在るものは、知覚で扱えるか。")
    s.db.execute("INSERT INTO questions (project_id, seq, text, created_at)"
                 " SELECT id, 2, ?, '2026-09-01T00:00:00+09:00' FROM projects"
                 " WHERE name='ddr'", (text,))          # as an older server wrote it
    s.db.commit()
    line = [ln for ln in render_path(s.trail("ddr")).splitlines()
            if ln.strip().startswith("Q2")][0]
    assert "エージェントの観測" in line, "the question, not just its tag"
    assert len(line) > 90 and len(line) < 200


def test_the_line_is_the_one_that_was_written(s):
    """Where a node carries a headline, that is the line -- not the body's
    first 96 characters, which is a summary nobody wrote."""
    s.ask("ddr", "[R1] 設計に要る構造は観測に含まれないか。" + "詳しくは次のとおり。" * 30,
          headline="[R1] 設計の構造は観測に含まれるか")
    s.answer("ddr", "含まれない。" + "根拠を述べる。" * 100, question="Q2",
             headline="含まれない: 観測にあるのは見た目だけだった")
    text = render_path(s.trail("ddr"))
    assert "Q2  [R1] 設計の構造は観測に含まれるか" in text
    assert "詳しくは次のとおり" not in text
    # Behind where the answer stands, which comes first on its line.
    assert "ANSWER  (not endorsed by the user) 含まれない: 観測にあるのは見た目だけだった" in text
    assert "根拠を述べる" not in text


def test_a_question_is_one_line_here_like_every_other_node(s):
    """The one kind of body this view printed whole. Nothing noticed while
    questions were a sentence long; a paper then opened questions carrying
    their materials and their checklist, and the tree this view exists to
    show was buried under them."""
    s.ask("ddr", "what does this paper claim\n\nmaterials:\n"
          + "- an article nobody has read yet\n" * 40)
    text = render_path(s.trail("ddr"))
    assert "what does this paper claim" in text
    assert "an article nobody has read yet" not in text
    assert max(len(ln) for ln in text.splitlines()) < 200


def test_a_short_answer_is_not_marked_as_cut(s):
    s.answer("ddr", "not a cost problem")
    text = render_path(s.trail("ddr"))
    assert "not a cost problem" in text and "..." not in text


def test_note_open_still_gives_the_whole_thing(s):
    """The half that must never truncate."""
    body = "y" * 5000
    s.answer("ddr", body, headline="the whole of it is kept")
    assert s.open("ddr", ["Q1"])["nodes"][0]["answer"] == body
