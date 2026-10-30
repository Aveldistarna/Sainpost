"""Which commit a node was created against.

This module used to capture the state as well -- build a tree, write a
commit, move a ref, push it. That made a lab notebook write into the thing it
was observing, and every fault the design produced came from that one
decision: a working tree pushed off the machine before anything said so, refs
left in repositories the notebook did not own, and a fresh timestamped commit
at each capture that made "the code moved under this measurement" fire on
identical code.

So the promise is now the narrow one, and the first section here is what
holds it: the notebook reads, and writes nothing anywhere.

Real git repositories throughout. The whole mechanism is git's behaviour, so
a version that passes against a mock is not evidence about anything.
"""

import subprocess

import pytest

from sainpost import rig
from sainpost.store import Store


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def fingerprint(repo):
    """Every file under .git, with size and mtime. Catches a written object, a
    moved ref, a refreshed index -- anything at all."""
    out = []
    for f in sorted((repo / ".git").rglob("*")):
        if f.is_file():
            st = f.stat()
            out.append((str(f.relative_to(repo)), st.st_size, st.st_mtime_ns))
    return out


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "router"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    (r / "escape.py").write_text("def frontage(pad):\n    return None\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r


@pytest.fixture()
def s(tmp_path, repo):
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "escape routing", repo=str(repo))
    st.ask("ddr", "why do U2's four byte lanes jam")
    yield st
    st.close()


def pre(st, project="ddr", **kw):
    args = dict(hypothesis="via price is too high to escape to another layer",
                why_now="A0 showed order does not matter",
                measure="sweep via_cost_mm 0.1..8.0",
                falsifier="the joined-span count does not move",
                apparatus="kicad 10.0.1, repair=False")
    args.update(kw)
    return st.hypothesis(project, **args)


# -- the promise ------------------------------------------------------------

def test_nothing_under_git_is_written_at_all(s, repo):
    """Not a commit, not a ref, not an object, not the index's stat cache.
    A notebook that modifies what it observes is not a notebook, and every
    fault the previous design produced came from doing exactly that."""
    (repo / "escape.py").write_text("half-finished edit\n")
    (repo / "scratch.txt").write_text("untracked\n")
    before = fingerprint(repo)
    pre(s)
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    assert fingerprint(repo) == before


def test_the_working_tree_and_the_branch_are_untouched(s, repo):
    (repo / "escape.py").write_text("half-finished edit\n")
    (repo / "scratch.txt").write_text("untracked\n")
    before = (git(repo, "status", "--porcelain"), git(repo, "rev-parse", "HEAD"),
              git(repo, "stash", "list"), git(repo, "for-each-ref"))
    pre(s)
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    assert (git(repo, "status", "--porcelain"), git(repo, "rev-parse", "HEAD"),
            git(repo, "stash", "list"), git(repo, "for-each-ref")) == before


def test_the_module_cannot_write_even_by_accident(s):
    """A guard against this growing back. There is no capture, no ref, no
    push -- and nothing that would need one."""
    assert not {"capture", "push", "ref_for", "fetch_command", "notebook_remote"} \
        & set(dir(rig))
    # Every git subcommand this module can reach, from the source rather than
    # from a grep: a dict key named "commit" and a call to `git commit` look
    # the same to a substring search, and only one of them is a write.
    import ast
    import inspect
    READS = {"rev-parse", "status"}
    tree = ast.parse(inspect.getsource(rig))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_git"]
    assert calls, "the guard is looking at the wrong function"
    for c in calls:
        verb = c.args[1]
        assert isinstance(verb, ast.Constant) and verb.value in READS, \
            f"git {getattr(verb, 'value', '?')} is not a read"


# -- what is recorded -------------------------------------------------------

def test_a_clean_tree_records_the_commit_and_nothing_else(s, repo):
    got = pre(s)["measured_against"]
    assert got["commit"] == git(repo, "rev-parse", "HEAD")[:12]
    assert len(got) == 1


def test_a_modified_tracked_file_is_reported_as_not_reproducible(s, repo):
    """The real one: the code the number came out of is in no commit. Still
    not a defect to be repaired by committing on somebody's behalf, and the
    message now says so -- a receiving agent reported the old wording as an
    alarm with no path to ever being satisfied, since the notebook never
    commits and its own instructions say to commit only when asked."""
    (repo / "escape.py").write_text("def frontage(pad):\n    return []\n")
    got = pre(s)["measured_against"]
    assert got["commit"] == git(repo, "rev-parse", "HEAD")[:12]
    said = got["TRACKED FILES DIFFER FROM THIS COMMIT"]
    assert "is in no commit" in said and "not a task" in said


def test_pycache_alone_does_not_claim_the_number_is_irreproducible(s, repo):
    """The failure two agents hit. Running any Python program under test
    creates __pycache__/, so conflating untracked files with a modified tree
    made the alarm fire on essentially every Python investigation -- and the
    claim was false, because the tracked source had not moved. One agent
    passed that false claim to another team inside a defect, telling them
    they could not reproduce something they could."""
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "escape.cpython-310.pyc").write_bytes(b"\x00")
    got = pre(s)["measured_against"]
    assert "TRACKED FILES DIFFER FROM THIS COMMIT" not in got
    assert "__pycache__" in got["untracked files, in no commit"]


def test_an_untracked_file_is_named_rather_than_judged(s, repo):
    """It can equally be the experiment itself. Only a reader can tell that
    from build noise, so the names are what comes back."""
    (repo / "sweep.py").write_text("for c in range(80): ...\n")
    got = pre(s)["measured_against"]
    assert got["untracked files, in no commit"] == "sweep.py"
    assert "TRACKED FILES DIFFER FROM THIS COMMIT" not in got


def test_both_are_reported_when_both_are_true(s, repo):
    (repo / "escape.py").write_text("edited\n")
    (repo / "sweep.py").write_text("new\n")
    got = pre(s)["measured_against"]
    assert "TRACKED FILES DIFFER FROM THIS COMMIT" in got
    assert got["untracked files, in no commit"] == "sweep.py"


def test_an_ignored_file_is_neither(s, repo):
    (repo / ".gitignore").write_text("*.log\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "ignore logs")
    (repo / "noise.log").write_text("x" * 1000)
    assert len(pre(s)["measured_against"]) == 1


# -- the reason it exists ---------------------------------------------------

def test_the_code_moving_under_a_measurement_is_reported(s, repo):
    """Nothing else in this record can see it. Both halves look entirely
    normal: a pre-registration with a falsifier, and a number."""
    pre(s)
    (repo / "escape.py").write_text("def frontage(pad):\n    return []\n")
    git(repo, "commit", "-qam", "fix the guard")
    got = s.result("ddr", "6/8 unchanged across 0.1..8.0", "FALSIFIED")
    assert "not about the code you predicted from" in \
        got["THE CODE MOVED UNDER THIS MEASUREMENT"]


def test_the_head_holding_still_is_never_reported_as_movement(s, repo):
    """Including while the tree is dirty at both ends, which is the normal
    state of real work. The previous design made a fresh timestamped commit
    at each end, so this fired on identical code -- a cold agent hit it three
    times out of three in one session, and said the thing that makes it worse
    than noise: on the attempt where the code HAD changed, the real signal
    was indistinguishable from the false ones."""
    (repo / "escape.py").write_text("work in progress\n")
    pre(s)
    got = s.result("ddr", "6/8 unchanged", "FALSIFIED")
    assert "THE CODE MOVED UNDER THIS MEASUREMENT" not in got
    assert "THE CODE MOVED UNDER THIS MEASUREMENT" not in \
        s.open("ddr", ["A1"])["nodes"][0]


def test_both_commits_are_kept_so_the_move_can_be_diffed(s, repo):
    pre(s)
    (repo / "escape.py").write_text("def frontage(pad):\n    return []\n")
    git(repo, "commit", "-qam", "fix the guard")
    s.result("ddr", "6/8 unchanged", "FALSIFIED")
    body = s.open("ddr", ["A1"])["nodes"][0]
    a = body["pre-registered against"].split()[0]
    b = body["measured against"].split()[0]
    assert git(repo, "diff", "--name-only", a, b) == "escape.py"


# -- projects that are not about code --------------------------------------

def test_a_project_without_a_repo_still_works(tmp_path):
    st = Store(tmp_path / "t.db")
    assert "none given" in st.start_project("bench", "a physical measurement")["repo"]
    st.ask("bench", "why does the rail sag")
    assert pre(st, project="bench")["measured_against"] is None
    st.close()


def test_a_repo_path_that_is_not_one_is_refused_out_loud_at_the_start(tmp_path):
    """Said once, now -- not silently on every attempt that records nothing."""
    st = Store(tmp_path / "t.db")
    out = st.start_project("ddr", "", repo=str(tmp_path / "nowhere"))
    assert "NOT A GIT REPOSITORY" in out["repo"]
    st.close()


def test_the_record_is_written_even_when_the_state_cannot_be_read(tmp_path,
                                                                  monkeypatch, repo):
    """A node whose commit could not be read is worth less than one whose
    could, and far more than no node at all."""
    monkeypatch.setattr(rig, "observe",
                        lambda *a: (_ for _ in ()).throw(rig.RigError("boom")))
    st = Store(tmp_path / "t.db")
    st.start_project("ddr", "", repo=str(repo))
    st.ask("ddr", "q")
    got = pre(st)
    assert got["attempt"] == "A1"
    assert "boom" in got["measured_against"]["code_state"]
    st.close()


# -- defects carry it too ---------------------------------------------------

def test_the_owner_is_told_which_version_broke_without_asking(s, repo):
    s.start_project("router-impl", "", repo=str(repo))
    s.ask("router-impl", "does it hold its invariants")
    pre(s)
    got = s.blocked("ddr", invocation="propose_route(repair=True)",
                    observed="TypeError: 'NoneType' object is not subscriptable",
                    needed="a proposal object", owner="router-impl",
                    stopped=True)
    assert got["broke_at"]["commit"] == git(repo, "rev-parse", "HEAD")[:12]
    assert "broke at" in s.open("ddr", ["D1"])["nodes"][0]


def test_a_defect_seen_on_a_dirty_tree_says_the_owner_cannot_reproduce_it(s, repo):
    s.start_project("router-impl", "", repo=str(repo))
    s.ask("router-impl", "does it hold its invariants")
    pre(s)
    (repo / "escape.py").write_text("mid-edit\n")
    s.blocked("ddr", invocation="propose_route(repair=True)", observed="TypeError",
              needed="a proposal", owner="router-impl", stopped=True)
    assert "cannot reproduce" in s.open("ddr", ["D1"])["nodes"][0]["broke at"]


def test_a_defect_seen_with_only_build_noise_says_no_such_thing(s, repo):
    """The false claim that reached another team."""
    s.start_project("router-impl", "", repo=str(repo))
    s.ask("router-impl", "does it hold its invariants")
    pre(s)
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    s.blocked("ddr", invocation="propose_route(repair=True)", observed="TypeError",
              needed="a proposal", owner="router-impl", stopped=True)
    broke = s.open("ddr", ["D1"])["nodes"][0]["broke at"]
    assert "cannot reproduce" not in broke
    assert "__pycache__" in broke


def test_the_fix_is_recorded_against_the_repository_that_owns_it(s, repo, tmp_path):
    other = tmp_path / "impl"
    other.mkdir()
    git(other, "init", "-q")
    git(other, "config", "user.email", "t@t")
    git(other, "config", "user.name", "t")
    (other / "impl.py").write_text("x = 1\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "base")
    s.start_project("router-impl", "", repo=str(other))
    s.ask("router-impl", "does it hold its invariants")
    pre(s)
    s.blocked("ddr", invocation="propose_route(repair=True)", observed="TypeError",
              needed="a proposal", owner="router-impl", stopped=True)
    got = s.fixed("D1", "FIXED", cause="None for edge pads", change="return []",
                  verify="rerun the proposal", invalidates="NOTHING")
    assert got["fixed_at"]["commit"] == git(other, "rev-parse", "HEAD")[:12]


# -- an old notebook grows the columns -------------------------------------

def test_a_notebook_written_before_any_of_this_still_opens(tmp_path):
    """CREATE TABLE IF NOT EXISTS does nothing to a table that exists, so the
    columns have to be added on open. Adding is the only migration a record
    with no edit path can need."""
    db = tmp_path / "old.db"
    st = Store(db)
    st.db.execute("ALTER TABLE attempts DROP COLUMN open_commit")
    st.db.execute("ALTER TABLE projects DROP COLUMN repo")
    st.close()
    again = Store(db)
    assert "open_commit" in {r["name"] for r in
                             again.db.execute("PRAGMA table_info(attempts)")}
    again.start_project("ddr", "")
    again.close()
