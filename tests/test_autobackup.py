"""A write to the notebook starts a backup; nothing else does.

Run by hand, backup.py was not run, and for three weeks the destination held
only a test fixture. These pin the trigger: which calls start one, and that
a burst of writes costs at most one run beyond the one already going.
"""

import threading
import time

import pytest

from sainpost import server


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("SAINPOST_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(server, "_STORE", None)
    calls = []
    monkeypatch.setattr(server._AUTO, "changed", lambda: calls.append(1))
    yield server, calls
    server._STORE = None


def test_a_write_starts_a_backup(tools):
    t, calls = tools
    t.note_start("ddr", "escape routing under a 0.5mm BGA")
    assert calls, "note_start wrote and nothing was backed up"


def test_a_read_does_not(tools):
    t, calls = tools
    t.note_start("ddr", "escape routing under a 0.5mm BGA")
    calls.clear()
    t.note_projects()
    t.note_trunk("ddr")
    assert not calls


def test_a_refusal_that_wrote_nothing_does_not(tools):
    t, calls = tools
    t.note_start("ddr", "escape routing under a 0.5mm BGA")
    calls.clear()
    assert t.note_answer("ddr", "nothing asked yet").startswith("REFUSED")
    assert not calls


def _slow(monkeypatch, runs, release):
    def once(self):
        runs.append(1)
        release.wait(5)
        return "ok"
    monkeypatch.setattr(server._AutoBackup, "_once", once)
    monkeypatch.setenv("SAINPOST_AUTOBACKUP", "1")


def test_writes_during_a_run_make_one_more_run(monkeypatch):
    """Not one per write: the run after snapshots all of them."""
    runs, release = [], threading.Event()
    _slow(monkeypatch, runs, release)
    a = server._AutoBackup()
    a.changed()
    for _ in range(5):
        a.changed()
    release.set()
    deadline = time.monotonic() + 5
    while a._running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not a._running
    assert len(runs) == 2


def test_it_can_be_turned_off(monkeypatch):
    runs, release = [], threading.Event()
    _slow(monkeypatch, runs, release)
    monkeypatch.setenv("SAINPOST_AUTOBACKUP", "0")
    a = server._AutoBackup()
    a.changed()
    release.set()
    assert not a._running and not runs
