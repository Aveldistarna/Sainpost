"""The door: the schema a client is handed, and a real stdio session.

Written after every tool in this server shipped broken while 41 in-process
tests passed. Calling a decorated function directly skips schema validation,
so a wrapper that flattened the signature to (*a, **kw) was invisible from
inside. Both tests here fail against that version.
"""

import asyncio
import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from sainpost import server
from sainpost.store import Store

ROOT = Path(__file__).resolve().parents[1]

#: Parameters a caller must be able to send, per tool. Not derived from the
#: functions -- deriving it from the same source it checks would make the
#: test agree with any mistake.
EXPECTED = {
    "note_projects": set(),
    "note_start": {"project", "description", "repo"},
    "note_trunk": {"project", "question"},
    "note_path": {"project", "question"},
    "note_ask": {"project", "question", "supersedes", "parent", "headline"},
    "note_hypothesis": {"project", "hypothesis", "why_now", "measure",
                        "falsifier", "apparatus", "prompted_by", "question",
                        "headline"},
    "note_result": {"project", "result", "verdict", "attempt", "cites", "headline"},
    "note_answer": {"project", "answer", "question", "cites", "headline",
                    "user_said"},
    "note_postscript": {"project", "label", "text", "shown_by", "headline",
                        "answer_is", "user_said"},
    "note_open": {"project", "labels"},
    "note_search": {"query", "project"},
    "note_blocked": {"project", "invocation", "observed", "needed", "owner",
                     "attempt", "supersedes", "stopped"},
    "note_fixed": {"defect", "resolution", "cause", "change", "verify",
                   "invalidates"},
    "note_defects": {"project", "closed"},
    "note_request": {"project", "wanted", "because", "owner"},
    "note_decide": {"request", "decision", "why"},
    "note_query": {"defect", "project", "question"},
    "note_reply": {"defect", "project", "answer"},
    "note_export": {"project", "path"},
    "note_import": {"path", "dry_run", "rename"},
    "note_merge": {"into", "absorbed"},
}


def test_schema_advertises_the_real_parameters():
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert set(listed) == set(EXPECTED), "a tool was added or renamed"
    for name, want in EXPECTED.items():
        got = set(listed[name].inputSchema.get("properties", {}))
        assert got == want, f"{name} advertises {sorted(got)}"
        assert not (got & {"a", "kw", "args", "kwargs"}), \
            f"{name} is leaking a wrapper's signature"


def test_required_fields_are_the_ones_that_must_precede_the_data():
    """The pre-registration gate has to be visible in the schema, not only
    enforced after the call: a client fills in what it is asked for."""
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    req = set(listed["note_hypothesis"].inputSchema.get("required", []))
    assert {"hypothesis", "measure", "falsifier", "apparatus"} <= req
    assert "prompted_by" not in req            # the first attempt has no parent
    # why_now names the prior RESULT that sent you here, and a project's first
    # attempt has none. It was advertised required anyway, so an agent filled
    # it with a paragraph explaining that the field did not apply. The store
    # enforces it from the second attempt on; the schema now agrees.
    assert "why_now" not in req


def test_the_reporter_of_a_defect_is_never_offered_a_field_for_the_fix():
    """A client fills in what the schema asks for. If note_blocked advertised
    anywhere to put a cause or a proposed fix, agents would put one there --
    an unverified claim about code they do not own, arriving at whoever does
    own it as a starting point. The absence has to be visible in the schema,
    not only intended in the docstring."""
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    blocked = listed["note_blocked"].inputSchema
    got = set(blocked.get("properties", {}))
    assert not (got & {"cause", "fix", "suggestion", "suggested_fix", "where",
                       "diagnosis", "root_cause", "patch", "should"})
    assert {"invocation", "observed", "needed", "owner"} <= set(blocked.get("required", []))
    # ... and the cause exists exactly once, on the side that owns the rig.
    assert "cause" in set(listed["note_fixed"].inputSchema.get("required", []))


class Client:
    """A minimal JSON-RPC client over the launcher's stdio, like the real one."""

    def __init__(self, db: Path):
        # encoding="utf-8" because that is what the wire is. text=True alone
        # decodes with the machine's locale -- cp932 on a Japanese Windows --
        # and the very first frame carries an em dash out of a docstring, so
        # initialize() died on the handshake with a UnicodeDecodeError while
        # the server was answering perfectly. Left strict on purpose: a real
        # mojibake byte should still fail this test rather than be replaced.
        self.p = subprocess.Popen(
            [sys.executable, "launch.py"], cwd=str(ROOT),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
            env=dict(os.environ, SAINPOST_DB=str(db)))
        self._id = 0

    def _rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        return json.loads(self.p.stdout.readline())

    def initialize(self):
        r = self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "t", "version": "0"}})
        self._rpc("notifications/initialized", notify=True)
        return r["result"]

    def call(self, name, **args):
        r = self._rpc("tools/call", {"name": name, "arguments": args})
        return r["result"]["content"][0]["text"]

    def close(self):
        self.p.terminate()
        self.p.wait(timeout=10)


@pytest.fixture()
def client(tmp_path):
    c = Client(tmp_path / "door.db")
    yield c
    c.close()


def test_a_whole_loop_runs_over_real_stdio(client):
    info = client.initialize()
    assert info["serverInfo"]["name"] == "Sainpost"
    assert "falsifier" in info["instructions"]

    assert "hs" in client.call("note_start", project="hs", description="the door")
    client.call("note_ask", project="hs", question="does the door work")

    refused = client.call("note_hypothesis", project="hs", hypothesis="h",
                          why_now="w", measure="m", falsifier="", apparatus="a")
    assert refused.startswith("REFUSED:") and "falsifier" in refused

    ok = json.loads(client.call(
        "note_hypothesis", project="hs", hypothesis="the stdio door is wired",
        why_now="in-process tests prove nothing about the door",
        measure="initialize, tools/list and tools/call over a real pipe",
        falsifier="any call returns an error or the process dies",
        apparatus="launch.py builds its own venv; SAINPOST_DB is a temp file"))
    assert ok["attempt"] == "A1"

    client.call("note_result", project="hs",
                result="9 tools listed; every call answered", verdict="CONFIRMED")
    trunk = client.call("note_trunk", project="hs")
    assert "A1   CONFIRMED" in trunk and "the stdio door is wired" in trunk


def test_a_false_reading_arrives_through_the_door_and_leaves_the_attempt_open(client):
    """A server drops an argument it does not declare without a word. A
    stopped=false that did not arrive would close the attempt as unmeasured --
    the thing it exists to prevent -- so only a real call shows it arrives."""
    client.initialize()
    client.call("note_start", project="hs", description="the door")
    client.call("note_ask", project="hs", question="does the door work")
    client.call("note_hypothesis", project="hs", hypothesis="h", measure="m",
                falsifier="f", apparatus="a")
    got = json.loads(client.call("note_blocked", project="hs", invocation="i",
                                 observed="o", needed="n", owner="tool",
                                 stopped=False))
    assert got["a false reading in"] == "hs A1"
    assert "A1   OPEN" in client.call("note_trunk", project="hs")


def test_a_rename_arrives_through_the_door(client, tmp_path):
    """The same silence, one argument over: a rename= that did not arrive
    would file the other machine's requests under a blank card, for good --
    nothing here is moved afterwards. And it is a mapping, the one argument
    here that is not a string or a flag."""
    from sainpost import share
    from sainpost.store import Store

    there = Store(tmp_path / "there.db")
    there.start_project("curve", "images")
    there.request(project="curve", owner="tool", wanted="a camera", because="b")
    share.export_project(there, "curve", str(tmp_path / "curve.json"))
    there.close()

    client.initialize()
    client.call("note_start", project="Tool", description="the tool")
    got = json.loads(client.call("note_import", path=str(tmp_path / "curve.json"),
                                 rename={"tool": "Tool"}))
    assert got["read as"][0].startswith("'tool' as 'Tool'")
    names = [p["project"] for p in json.loads(client.call("note_projects"))]
    assert "tool" not in names and {"Tool", "curve"} <= set(names)


def test_whose_answer_it_is_arrives_through_the_door(client):
    """The same silence again: a user_said that did not arrive would record
    the user's own acceptance as an agent's answer, and an answer_is that did
    not arrive would leave a rejected claim reading as settled -- the two
    states these arguments exist to end."""
    client.initialize()
    client.call("note_start", project="hs", description="the door")
    client.call("note_ask", project="hs", question="what does the paper claim")
    client.call("note_answer", project="hs", answer="a world you make is one you read",
                user_said="「それでいこう」 (chat, 2026-10-03)")
    assert "ANSWER (endorsed by the user" in client.call("note_trunk", project="hs")
    client.call("note_postscript", project="hs", label="Q1", text="turned down later",
                answer_is="REJECTED", user_said="「やっぱり違う」 (chat, 2026-10-04)")
    trunk = client.call("note_trunk", project="hs")
    assert "ANSWER REJECTED by the user" in trunk and "「やっぱり違う」" in trunk
    assert "[answered, then REJECTED by the user]" in client.call("note_path", project="hs")


def test_the_users_words_are_asked_for_verbatim_on_both_fields():
    """Filled in while being read: a paraphrase in user_said is the agent's
    reading of the user, recorded as the user."""
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for tool in ("note_answer", "note_postscript"):
        d = listed[tool].inputSchema["properties"]["user_said"]["description"]
        assert "VERBATIM" in d and "not theirs" in d, tool
    d = listed["note_postscript"].inputSchema["properties"]["answer_is"]["description"]
    assert all(w in d for w in ("ENDORSED", "REJECTED", "WITHDRAWN", "STANDING"))


def test_the_launcher_keeps_stdout_clean(tmp_path):
    """One stray print in the bootstrap corrupts the handshake, and the
    launcher is the only code that runs before the protocol starts."""
    c = Client(tmp_path / "clean.db")
    try:
        assert c.initialize()["serverInfo"]["name"] == "Sainpost"
    finally:
        c.close()


def test_every_field_that_carries_a_commitment_says_so_on_itself():
    """A client fills in what it is asked for, and for a while each of these
    advertised nothing but {"title": "Observed", "type": "string"} -- the
    whole explanation lived in the tool description, which is read when
    CHOOSING a tool, not when filling one in."""
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for tool, fields in {
        "note_hypothesis": ("falsifier", "apparatus", "measure", "why_now"),
        "note_blocked": ("invocation", "observed", "needed", "owner", "stopped"),
        "note_fixed": ("cause", "verify", "invalidates"),
        "note_result": ("result", "verdict"),
    }.items():
        props = listed[tool].inputSchema["properties"]
        for f in fields:
            assert props[f].get("description"), f"{tool}.{f} advertises no description"


def test_the_field_that_must_be_verbatim_says_verbatim_on_the_field():
    """The one instruction most likely to be quietly ignored, at the exact
    moment it is being ignored."""
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    d = listed["note_blocked"].inputSchema["properties"]["observed"]["description"]
    assert "VERBATIM" in d.upper() and "summarise" in d


def test_choosing_the_wrong_tool_for_a_crash_is_warned_about_where_it_is_chosen():
    """No refusal can reach this one. An attempt that crashed can be closed
    ABANDONED and the server will accept it -- the call is valid, it is just
    untrue. The only place to catch it is where the agent picks the tool."""
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    d = listed["note_result"].description
    assert "note_blocked" in d
    assert "ABANDONED" in d and "budget" in d


def test_the_weakest_channel_is_kept_short_on_purpose():
    """The instructions block is read once, before any concrete situation,
    and nothing goes wrong if it is skimmed. It is where guidance goes to be
    ignored, so it holds only what no refusal and no field can carry: making
    an agent reach for a tool it would otherwise never call.

    And past 2048 characters it is not skimmed but gone: Claude Code cuts
    server instructions there with "… [truncated]". Measured on 2026-09-11,
    when the block was 7003 and a session received it only as far as
    note_path -- the loop, note_blocked and note_import never arrived. The
    budget used to be 7000; it was a guess. The database path closes the
    block and varies by machine, so the rest leaves room for a long one."""
    assert len(server.mcp.instructions) < 2048, "prune it, or move it to a field"


def test_no_tool_description_is_cut_off_in_transit():
    """Claude Code cuts a tool's description at 2048 characters, the same as
    the instructions. note_blocked was 2623: what arrived stopped mid-word,
    before the paragraph saying how to resume once the defect is fixed."""
    for t in asyncio.run(server.mcp.list_tools()):
        assert len(t.description or "") < 2048, f"{t.name} is cut off in transit"


def test_no_parameter_advertises_a_type_its_default_contradicts():
    """`note_defects.closed` shipped as {"type": "string", "default": false} --
    a schema that contradicts itself, to a client that fills in what it is
    asked for. The cause is that the helper building these returns
    Annotated[str, ...] and nothing stopped it being used on a flag.

    This pair is what the guard has to compare, and finding that out cost a
    measurement: comparing the ANNOTATION against the advertised type -- the
    obvious check -- returns zero mismatches, because for `closed` those two
    agreed with each other and both disagreed with the default.
    """
    listed = asyncio.run(server.mcp.list_tools())
    json_type = {str: "string", bool: "boolean", int: "integer"}
    checked = 0
    for t in listed:
        fn = inspect.unwrap(server.mcp._tool_manager.get_tool(t.name).fn)
        props = t.inputSchema.get("properties", {})
        for name, param in inspect.signature(fn).parameters.items():
            if param.default is inspect.Parameter.empty:
                continue
            checked += 1
            if param.default is None:
                # "Not said" as a value of its own: note_blocked.stopped, where
                # either boolean default is wrong for somebody. It has to be
                # advertised as null beside the one type it stands in for.
                kinds = {s.get("type") for s in props[name].get("anyOf", [])}
                assert "null" in kinds and len(kinds) == 2, \
                    f"{t.name}.{name} defaults to None and advertises {props[name]}"
                continue
            assert props[name].get("type") == json_type[type(param.default)], \
                f"{t.name}.{name} advertises {props[name].get('type')!r} " \
                f"with default {param.default!r}"
    assert checked > 10, "the sweep found nothing to check"


def test_the_schema_and_the_store_agree_on_what_is_optional():
    """A parameter with a default that is still advertised as required makes a
    client fill in a field the server does not want -- which is exactly what
    an agent did with why_now on a first attempt, writing a paragraph to
    explain that the field did not apply."""
    for t in asyncio.run(server.mcp.list_tools()):
        fn = inspect.unwrap(server.mcp._tool_manager.get_tool(t.name).fn)
        required = set(t.inputSchema.get("required", []))
        for name, param in inspect.signature(fn).parameters.items():
            has_default = param.default is not inspect.Parameter.empty
            assert has_default != (name in required), \
                f"{t.name}.{name}: default={has_default}, advertised required=" \
                f"{name in required}"


def test_a_field_does_not_advertise_a_rule_the_store_does_not_enforce():
    """why_now advertised "required from a project's SECOND attempt on". The
    store requires it once the project has a RESULT to name, which is not the
    same thing: an arm opened beside the first attempt is a second attempt
    with nothing measured yet. An agent in exactly that position read the
    field, believed it, and wrote the paragraph the rule exists to prevent --
    then filed it as a request, because the advertised rule IS the rule to a
    client that fills in what it is asked for.
    """
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    why = listed["note_hypothesis"].inputSchema["properties"]["why_now"]["description"]
    assert "second" not in why.lower(), \
        "the field counts attempts; the store counts results"
    assert "RESULT" in why

    db = Path(tempfile.mkdtemp()) / "t.db"
    st = Store(db)
    st.start_project("paper", "")
    st.ask("paper", "what does it claim")
    for h in ("claim one", "claim two, the rival"):
        st.hypothesis("paper", hypothesis=h, why_now="", measure="m",
                      falsifier="f", apparatus="a")          # no result yet: allowed
    st.close()


# -- one bootstrap at a time ----------------------------------------------

LOCK_WORKER = """
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
import launch
launch.LOCK = Path(sys.argv[2])
go = float(sys.argv[3])
while time.time() < go:                 # everybody reaches it at one instant
    time.sleep(0.001)
with launch.one_at_a_time():
    held = [time.time()]
    time.sleep(0.4)                     # stand in for venv + pip
    held.append(time.time())
print(json.dumps(held))
"""


def test_only_one_process_bootstraps_the_venv_at_a_time(tmp_path):
    """"A fresh clone needs no manual steps" means every session on the
    machine reaches the bootstrap at the same moment.

    Nothing serialised it, so four of them ran `python -m venv` and then
    `pip install` into one directory. Measured on a fresh checkout with four
    clients: they came up at 1.0, 3.0, 13.2 and 27.8 seconds, and the ones
    whose build lost fell back to whatever interpreter had launched them --
    which worked only because that interpreter happened to carry `mcp`. On a
    machine without it they would have died, and twenty-eight seconds is
    already past what several MCP clients wait for a server.

    The lock is what is under test, not pip: four processes hold it in turn
    and no two of the intervals may overlap.
    """
    import json
    import subprocess
    import sys
    import time

    root = str(Path(__file__).resolve().parents[1])
    worker = tmp_path / "hold.py"
    worker.write_text(LOCK_WORKER, encoding="utf-8")
    lock = tmp_path / ".venv.lock"

    go = time.time() + 2.0
    ps = [subprocess.Popen(
        [sys.executable, str(worker), root, str(lock), str(go)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace") for _ in range(4)]
    spans = []
    for p in ps:
        out = (p.communicate(timeout=90)[0] or "").strip()
        spans.append(json.loads(out.splitlines()[-1]))

    spans.sort()
    for (_, first_end), (second_start, _) in zip(spans, spans[1:]):
        assert second_start >= first_end, f"two builds overlapped: {spans}"
    assert not lock.exists(), "the lock outlived the last holder"


def test_a_lock_left_by_a_killed_process_does_not_wedge_the_machine(
        tmp_path, monkeypatch):
    """A build that was killed must not stop every later session forever.

    The lock is a file, so nothing releases it when its holder dies. It is
    therefore believed only for a while -- long enough for pip on a cold
    cache, and no longer.
    """
    import os
    import time

    import launch

    lock = tmp_path / ".venv.lock"
    lock.write_text("99999\n", encoding="utf-8")
    old = time.time() - (launch.LOCK_STALE + 60)
    os.utime(lock, (old, old))
    monkeypatch.setattr(launch, "LOCK", lock)
    monkeypatch.setattr(launch, "LOCK_WAIT", 5)

    with launch.one_at_a_time():
        assert lock.exists(), "the abandoned lock was taken, not merely deleted"
    assert not lock.exists()
