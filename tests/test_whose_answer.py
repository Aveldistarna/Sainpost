"""Whose an answer is, and whether it still stands.

An answer is written by an agent. A paper's claim was one: the agent that laid
out the argument wrote it as the answer to "what does this paper claim", and
the author never accepted it. Two postscripts said so, and the answer's own
line went on reading as settled, ahead of them. The project's own look at why
its drafts kept drifting from what the author had said named sessions reading
that answer back as the author's as one of four routes (R76).

So an answer says whose it is on its own line, in every view: not endorsed by
the user until their own words say otherwise. And a note can say the answer
no longer stands -- the user rejected it, or its writer withdrew it -- which
moves the confirmed attempts under it out of STANDING.
"""

import json

import pytest

from sainpost import share
from sainpost.server import render_path, render_trunk
from sainpost.store import NoteError, Store

YES = "「1にしよう。」 (chat, 2026-09-30)"
NO = "「検査が有効とか、どうでもいいんじゃない？」 (review J11, 2026-09-28)"


def claim(st, project="paper"):
    """A claim an agent wrote as the answer, with the attempt it rested on."""
    st.start_project(project, "what a paper claims")
    st.ask(project, "what does this paper claim")
    st.hypothesis(project, hypothesis="an agent is held to what a working check reads",
                  why_now="", measure="38 events classified",
                  falsifier="3 or more events it cannot place", apparatus="episodes.md")
    st.result(project, "1 of 38 it cannot place", "CONFIRMED")
    st.answer(project, "an agent is held to what a working check reads")
    return project


@pytest.fixture()
def s(tmp_path):
    st = Store(tmp_path / "t.db")
    claim(st)
    yield st
    st.close()


def views(st, project="paper", q="Q1"):
    return (render_trunk(st.trunk(project, q)), render_path(st.trail(project)))


# -- an agent's answer says so ---------------------------------------------

def test_an_answer_nobody_put_to_the_user_says_it_is_not_theirs(s):
    """The default is the true state of an answer an agent wrote, so it
    needs nothing from the writer -- and "[answered]" alone is what read as
    the author's claim."""
    trunk, path = views(s)
    assert "ANSWER (not endorsed by the user) an agent is held" in trunk
    assert "[answered, not endorsed by the user]" in path
    assert "ANSWER  (not endorsed by the user) an agent is held" in path
    assert "1 question(s) answered (1 not endorsed by the user)" in path
    body = s.open("paper", ["Q1"])["nodes"][0]
    assert body["the answer is"].startswith("not endorsed by the user")
    keys = list(body)
    assert keys.index("the answer is") < keys.index("answer"), \
        "read before the answer, not after it"
    found = s.search("what does this paper claim", "paper")["questions"][0]
    assert found["the answer is"] == "not endorsed by the user"


def test_the_users_words_with_the_answer_make_it_theirs(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("paper", "")
    st.ask("paper", "what does this paper claim")
    got = st.answer("paper", "a world you make is one you can read", user_said=YES)
    assert got["whose"].startswith("endorsed by the user")
    assert YES not in json.dumps(got, ensure_ascii=False), \
        "a write does not hand back what it was just given"
    trunk, path = views(st)
    assert "ANSWER (endorsed by the user, recorded" in trunk and YES in trunk
    assert "[answered, endorsed by the user]" in path
    assert YES in st.open("paper", ["Q1"])["nodes"][0]["the answer is"]
    st.close()


def test_without_the_users_words_the_write_says_how_to_record_them(s):
    s.ask("paper", "what does it require")
    got = s.answer("paper", "R1..R8")
    assert got["whose"].startswith("not endorsed by the user")
    assert "note_postscript('Q2', answer_is=" in got["whose"]


# -- later: the user accepts it, rejects it, or it is withdrawn -------------

def test_endorsing_it_later_moves_where_it_stands_and_touches_nothing(s):
    before = s.open("paper", ["Q1"])["nodes"][0]["answer"]
    got = s.postscript("paper", "Q1", "the author read it and took it as the claim",
                       answer_is="ENDORSED", user_said=YES)
    assert got["the answer now"].startswith("endorsed by the user")
    body = s.open("paper", ["Q1"])["nodes"][0]
    assert body["answer"] == before, "the answer is never touched"
    assert body["learned later"][0]["answer_is"] == "ENDORSED"
    assert body["learned later"][0]["user_said"] == YES
    trunk, path = views(s)
    assert "[answered, endorsed by the user]" in path
    assert "LATER  (" in trunk and "the user ENDORSED the answer)" in trunk


def test_a_rejected_answer_no_longer_stands_wherever_it_is_read(s):
    s.postscript("paper", "Q1", "the author turned it down as the claim",
                 answer_is="REJECTED", user_said=NO)
    trunk, path = views(s)
    assert "[answered, then REJECTED by the user]" in path
    assert "ANSWER  (REJECTED by the user, recorded" in path
    assert "it no longer stands" in path
    assert "1 question(s) answered (1 rejected by the user)" in path
    line = [ln for ln in trunk.splitlines() if ln.startswith("  ANSWER")][0]
    assert line.startswith("  ANSWER REJECTED by the user") and NO in line
    body = s.open("paper", ["Q1"])["nodes"][0]
    assert body["the answer is"].startswith("REJECTED by the user")
    assert body["answer"] == "an agent is held to what a working check reads"


def test_what_was_confirmed_under_it_leaves_standing(s):
    """STANDING is read as what to rest on, and the hypothesis in it was the
    rejected claim itself. The measurement is kept, under a heading that says
    what it is no longer standing for."""
    assert [a["attempt"] for a in s.trail("paper")["standing"]] == ["A1"]
    s.postscript("paper", "Q1", "turned down", answer_is="REJECTED", user_said=NO)
    t = s.trail("paper")
    assert t["standing"] == []
    assert [a["attempt"] for a in t["no_longer_standing"]] == ["A1"]
    text = render_path(t)
    assert "STANDING -- what anything" not in text
    head = text.index("NO LONGER STANDING")
    assert head < text.index("A1   Q1") < text.index("THE PATH")
    for line in text.splitlines():
        assert len(line) < 140, line


def test_a_withdrawn_answer_leaves_standing_too(s):
    """The writer's own finding: replaced, or wrong. It needs no words of
    the user's, because saying an answer no longer stands costs nobody
    anything they were entitled to rest on."""
    got = s.postscript("paper", "Q1", "replaced by the claim in the brief",
                       answer_is="withdrawn")
    assert got["the answer now"].startswith("WITHDRAWN")
    t = s.trail("paper")
    assert [a["attempt"] for a in t["no_longer_standing"]] == ["A1"]
    assert "[answered, then WITHDRAWN]" in render_path(t)


def test_a_withdrawn_or_rejected_answer_is_one_line_in_the_trunk(tmp_path):
    """Whole, the answer came to the front ahead of the notes saying it no
    longer stood. It is still there whole, one call away."""
    st = Store(tmp_path / "t.db")
    st.start_project("paper", "")
    st.ask("paper", "what does this paper claim")
    st.answer("paper", "an agent is held to what a working check reads.\n"
              + "THE-REST-OF-THE-CLAIM " * 20, headline="held to what a working check reads")
    st.postscript("paper", "Q1", "turned down", answer_is="REJECTED", user_said=NO)
    trunk = render_trunk(st.trunk("paper"))
    assert "THE-REST-OF-THE-CLAIM" not in trunk
    assert "As written then, in one line: held to what a working check reads" in trunk
    assert "note_open('paper', 'Q1') gives it whole" in trunk
    assert trunk.index("REJECTED by the user") < trunk.index("held to what")
    assert "THE-REST-OF-THE-CLAIM" in st.open("paper", ["Q1"])["nodes"][0]["answer"]
    st.close()


def test_the_latest_note_says_where_it_stands_and_every_one_is_kept(s):
    s.postscript("paper", "Q1", "accepted", answer_is="ENDORSED", user_said=YES)
    s.postscript("paper", "Q1", "and then not", answer_is="REJECTED", user_said=NO)
    assert "[answered, then REJECTED by the user]" in render_path(s.trail("paper"))
    s.postscript("paper", "Q1", "a later finding, nothing about standing")
    assert "[answered, then REJECTED by the user]" in render_path(s.trail("paper")), \
        "a note that moves nothing leaves it where it was"
    s.postscript("paper", "Q1", "accepted again", answer_is="ENDORSED", user_said=YES)
    assert "[answered, endorsed by the user]" in render_path(s.trail("paper"))
    later = s.open("paper", ["Q1"])["nodes"][0]["learned later"]
    assert [n.get("answer_is") for n in later] == ["ENDORSED", "REJECTED", None, "ENDORSED"]


def test_answering_again_says_where_the_users_word_goes(s):
    """An agent coming back with the user's acceptance reaches for the call
    that wrote the answer. The refusal is where it learns the other one --
    and it says the answer in one line, not whole."""
    s.db.execute("UPDATE questions SET answer=? WHERE seq=1", ("x" * 3000,))
    with pytest.raises(NoteError) as e:
        s.answer("paper", "the same, now theirs", question="Q1", user_said=YES)
    msg = str(e.value)
    assert "note_postscript('Q1', text, answer_is='ENDORSED'" in msg
    assert "supersedes='Q1'" in msg
    assert "x" * 200 not in msg


def test_a_note_that_moves_nothing_reads_as_it_always_did(s):
    s.postscript("paper", "Q1", "the corridor model was missing")
    later = s.open("paper", ["Q1"])["nodes"][0]["learned later"][0]
    assert set(later) == {"when", "text", "headline"}
    trunk, _ = views(s)
    assert f"LATER  ({later['when'][:10]}) the corridor model was missing" in trunk


# -- only the user's words make it theirs ----------------------------------

@pytest.mark.parametrize("mark", ["ENDORSED", "REJECTED"])
def test_only_the_users_own_words_endorse_or_reject_it(s, mark):
    """A claim that the user holds something is itself a claim, and it is
    not free -- the same reason a note on an attempt with nothing measured
    behind it renders as INTERPRETATION."""
    with pytest.raises(NoteError) as e:
        s.postscript("paper", "Q1", "they agreed", answer_is=mark)
    msg = str(e.value)
    assert "VERBATIM" in msg and "not theirs" in msg and "Nothing was written" in msg
    assert s.open("paper", ["Q1"])["nodes"][0]["learned later"] is None


def test_a_withdrawal_with_the_users_words_is_a_rejection(s):
    with pytest.raises(NoteError) as e:
        s.postscript("paper", "Q1", "they said no", answer_is="WITHDRAWN", user_said=NO)
    assert "answer_is='REJECTED'" in str(e.value)


def test_their_words_go_with_where_the_answer_stands(s):
    with pytest.raises(NoteError) as e:
        s.postscript("paper", "Q1", "they said something", user_said=NO)
    assert "goes with answer_is" in str(e.value)


def test_where_it_stands_is_a_closed_vocabulary(s):
    with pytest.raises(NoteError) as e:
        s.postscript("paper", "Q1", "x", answer_is="SUPERSEDED")
    assert "ENDORSED" in str(e.value) and "WITHDRAWN" in str(e.value)


def test_only_an_answer_has_a_standing(s):
    with pytest.raises(NoteError) as e:
        s.postscript("paper", "A1", "x", answer_is="WITHDRAWN")
    assert "an attempt" in str(e.value)
    s.request(project="paper", owner="tool", wanted="w", because="b")
    s.decide("R1", "ACCEPTED", "y")
    with pytest.raises(NoteError):
        s.postscript("paper", "R1", "x", user_said=NO)
    s.ask("paper", "is it the wrong question")
    s.ask("paper", "the right one", supersedes="Q2")
    with pytest.raises(NoteError) as e:
        s.postscript("paper", "Q2", "x", answer_is="WITHDRAWN")
    assert "without being answered" in str(e.value)
    s.postscript("paper", "Q2", "a plain note still goes on it")


# -- where else it is read -------------------------------------------------

def test_a_question_serving_a_rejected_answer_says_so(tmp_path):
    st = Store(tmp_path / "t.db")
    st.start_project("paper", "")
    st.ask("paper", "what does this paper claim")
    st.ask("paper", "what must be shown for it", parent="Q1")
    st.answer("paper", "R1..R8", question="Q2")
    st.answer("paper", "held to what a check reads", question="Q1")
    st.postscript("paper", "Q1", "turned down", answer_is="REJECTED", user_said=NO)
    trunk = render_trunk(st.trunk("paper", "Q2"))
    under = [ln for ln in trunk.splitlines() if ln.startswith("  under")][0]
    assert under.endswith("[answered, then REJECTED by the user]")
    st.close()


def test_citing_it_warns_and_so_does_citing_what_stood_under_it(s):
    """A paper's requirements cited the attempt that WAS its claim, as
    support, five times; the citing rows went on reading as sound."""
    s.start_project("other", "")
    s.ask("other", "does the paper hold")
    s.hypothesis("other", hypothesis="h", why_now="", measure="m", falsifier="f",
                 apparatus="a")
    s.result("other", "r", "CONFIRMED",
             cites="paper/Q1, paper/A1, records: paper/A1")
    s.postscript("paper", "Q1", "turned down", answer_is="REJECTED", user_said=NO)
    got = s.open("other", ["A1"])["nodes"][0]["the result rests on"]
    q1, a1, rec = got
    assert q1["whose answer"].startswith("REJECTED by the user")
    assert any("its answer was REJECTED" in w for w in q1["READ IT AGAIN"])
    assert any("it stood under paper/Q1" in w for w in a1["READ IT AGAIN"])
    assert any("it stood under paper/Q1" in w for w in rec["READ IT AGAIN"]), \
        "learned later, so it warns however the citation leans"
    assert "it stood under paper/Q1" in render_trunk(s.trunk("other"))


def test_the_map_names_every_answer_that_no_longer_stands(s):
    """A map lists about a dozen questions. The tally counts the answers
    that no longer stand; this names them, so the one a reader must not pick
    up is not hidden in a branch the map left out."""
    body = "この問いで確かめたことを、実物の記録と同じ長さで書いておく。" * 10
    pad = "、そしてこの続きが実物の見出しと同じ長さになるまで書かれている" * 2
    for i in range(14):
        s.ask("paper", f"Q{i} " + body, headline=f"問い {i}{pad}"[:96])
        s.hypothesis("paper", hypothesis=body, headline=f"仮説 {i}{pad}"[:96],
                     why_now="A1", prompted_by="A1", measure="m", falsifier="f",
                     apparatus="a")
        s.result("paper", body, "CONFIRMED", headline=f"結果 {i}{pad}"[:96])
        s.answer("paper", body, headline=f"答え {i}{pad}"[:96])
    s.postscript("paper", "Q1", "turned down", answer_is="REJECTED", user_said=NO)
    s.postscript("paper", "Q2", "replaced", answer_is="WITHDRAWN")
    text = render_path(s.trail("paper"))
    assert "the map of it" in text
    assert "answers that no longer stand: Q1 (REJECTED by the user), Q2 (WITHDRAWN)" in text
    assert "(13 not endorsed by the user, 1 rejected by the user, 1 withdrawn)" in text


def test_an_answered_question_that_was_replaced_says_so_on_its_line(s):
    """note_ask(supersedes=) on an answered question keeps it answered and
    links the two -- and the line said only "[answered]"."""
    s.ask("paper", "what does the author's brief claim", supersedes="Q1")
    text = render_path(s.trail("paper"))
    assert "[answered, not endorsed by the user, then replaced by Q2]" in text


# -- the record underneath -------------------------------------------------

def test_a_notebook_older_than_these_columns_opens_and_keeps_every_row(tmp_path):
    db = tmp_path / "old.db"
    st = Store(db)
    claim(st)
    st.postscript("paper", "Q1", "a note from before")
    st.db.execute("ALTER TABLE questions DROP COLUMN answer_user_said")
    st.db.execute("ALTER TABLE postscripts DROP COLUMN answer_is")
    st.db.execute("ALTER TABLE postscripts DROP COLUMN user_said")
    counts = {t: st.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("questions", "attempts", "postscripts")}
    st.close()
    again = Store(db)
    assert {t: again.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in counts} == counts
    assert "[answered, not endorsed by the user]" in render_path(again.trail("paper"))
    again.postscript("paper", "Q1", "turned down", answer_is="REJECTED", user_said=NO)
    assert "[answered, then REJECTED by the user]" in render_path(again.trail("paper"))
    again.close()


def test_what_a_server_older_than_these_columns_writes_still_reads(s):
    """Every session on the machine keeps the server it started with, so an
    older one goes on writing into a notebook that has these columns: its
    inserts name their columns, and leave these NULL."""
    s.db.execute("INSERT INTO postscripts (question_id, text, headline, created_at)"
                  " SELECT id, 'from an older server', NULL, '2026-10-02T00:00:00+09:00'"
                  " FROM questions WHERE seq=1")
    s.ask("paper", "answered by an older server")
    s.db.execute("UPDATE questions SET status='answered', answer='old', closed_at="
                 "'2026-10-02T00:00:00+09:00' WHERE seq=2")
    text = render_path(s.trail("paper"))
    assert "from an older server" in text
    assert text.count("[answered, not endorsed by the user]") == 2


# -- another machine -------------------------------------------------------

@pytest.fixture()
def two(tmp_path):
    win, lin = Store(tmp_path / "win.db"), Store(tmp_path / "lin.db")
    yield win, lin, tmp_path
    win.close()
    lin.close()


def marked(st):
    claim(st)
    st.ask("paper", "what does the brief claim")
    st.answer("paper", "a world you make is one you can read", user_said=YES)
    st.postscript("paper", "Q1", "turned down", answer_is="REJECTED", user_said=NO)


def test_whose_answer_it_is_crosses_to_the_other_machine(two):
    win, lin, tmp = two
    marked(win)
    share.export_project(win, "paper", str(tmp / "paper.json"))
    got = share.import_file(lin, tmp / "paper.json")
    assert "REFUSED" not in json.dumps(got)
    assert share.snapshot(lin, "paper") == share.snapshot(win, "paper")
    text = render_path(lin.trail("paper"))
    assert "[answered, then REJECTED by the user]" in text
    assert "[answered, endorsed by the user]" in text
    again = share.import_file(lin, tmp / "paper.json")
    assert again["result"].startswith("nothing new")


def test_a_record_with_none_of_this_exports_as_it_always_did(two):
    """The file is a pure function of the record, and a record that says
    nothing about whose its answers are says nothing in the file either."""
    win, _, tmp = two
    claim(win)
    win.postscript("paper", "Q1", "a plain note")
    q = share.snapshot(win, "paper")["questions"][0]
    assert "answer_user_said" not in q
    assert set(q["postscripts"][0]) == {"text", "headline", "created_at"}


def stripped(data):
    """The same record as a server older than these fields writes it."""
    for q in data["questions"]:
        q.pop("answer_user_said", None)
        for ps in q["postscripts"]:
            ps.pop("answer_is", None)
            ps.pop("user_said", None)
    return data


def test_a_file_from_a_machine_older_than_these_marks_is_not_a_disagreement(two):
    """That machine imported the record and could not keep the marks; what
    it sends back says nothing about them, which is not the same as saying
    they are absent."""
    win, lin, tmp = two
    marked(win)
    f = tmp / "paper.json"
    share.export_project(win, "paper", str(f))
    f.write_text(share.render(stripped(json.loads(f.read_text(encoding="utf-8")))),
                 encoding="utf-8")
    got = share.import_file(win, f)
    assert "REFUSED" not in json.dumps(got)
    assert "[answered, then REJECTED by the user]" in render_path(win.trail("paper"))


def test_marks_an_older_import_could_not_carry_arrive_once(two):
    win, lin, tmp = two
    marked(win)
    f = tmp / "paper.json"
    share.export_project(win, "paper", str(f))
    full = f.read_text(encoding="utf-8")
    f.write_text(share.render(stripped(json.loads(full))), encoding="utf-8")
    share.import_file(lin, f)                      # what an older import kept
    assert "[answered, not endorsed by the user]" in render_path(lin.trail("paper"))
    f.write_text(full, encoding="utf-8")
    got = share.import_file(lin, f)
    assert "REFUSED" not in json.dumps(got)
    news = " ".join(got.get("closed or settled since", []))
    assert "Q1's note" in news and "the user's words endorsing its answer" in news
    assert share.snapshot(lin, "paper") == share.snapshot(win, "paper")
    assert share.import_file(lin, f)["result"].startswith("nothing new")


def test_a_mark_this_notebook_does_not_know_is_not_read_as_one(two):
    win, lin, tmp = two
    claim(win)
    win.postscript("paper", "Q1", "a note")
    f = tmp / "paper.json"
    share.export_project(win, "paper", str(f))
    data = json.loads(f.read_text(encoding="utf-8"))
    data["questions"][0]["postscripts"][0]["answer_is"] = "SOMETHING_NEWER"
    f.write_text(share.render(data), encoding="utf-8")
    got = share.import_file(lin, f)
    assert any("SOMETHING_NEWER" in n for n in got["not carried"])
    assert "[answered, not endorsed by the user]" in render_path(lin.trail("paper"))
