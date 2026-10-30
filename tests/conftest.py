import itertools

import pytest

from sainpost import store


@pytest.fixture(autouse=True)
def distinct_notebook_names(monkeypatch):
    """Each notebook a test opens gets a name no other one in it has. Drawn at
    random, two in one test would share one about once in thirty thousand
    runs, and an import between them would be refused for it."""
    n = itertools.count(1)
    monkeypatch.setattr(store, "new_notebook_name", lambda: f"n{next(n):02d}")


@pytest.fixture(autouse=True)
def no_real_backup_destination(monkeypatch):
    """backup.send() reads SAINPOST_DRIVE, and on a machine where the user
    set it, every test that ran bk.backup() without setting it sent its
    fixture notebook to the real destination -- moving the real copy aside
    under history/ and putting 'ddr' in its place. Every copy there, from
    2026-09-10 on, held nothing but test data. A test that wants a
    destination sets one.

    The server starts backup.py after every write, and backup.py writes its
    dump into this checkout: every tool test would put its fixture there. A
    test that wants that trigger turns it back on."""
    monkeypatch.delenv("SAINPOST_DRIVE", raising=False)
    monkeypatch.setenv("SAINPOST_AUTOBACKUP", "0")
