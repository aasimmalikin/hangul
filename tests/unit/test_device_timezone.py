"""Times follow the user's device: the browser's timezone is adopted while
the user's timezone is automatic (the default), and ignored once they pin
one in Personalisation. Fakes the session; no Postgres."""
from types import SimpleNamespace

import pytest

from harness.db import settings as st
from harness.db import tasks as tasks_db


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, model, uid): return self.rows.get(uid)
    def add(self, row): self.rows[row.user_id] = row
    def commit(self): pass


@pytest.fixture
def rows(monkeypatch):
    rows: dict = {}
    monkeypatch.setattr(st, "SessionLocal", lambda: FakeSession(rows))
    retimed = []
    monkeypatch.setattr(tasks_db, "retime_daily", lambda uid, tz: retimed.append((uid, tz)))
    rows["retimed"] = retimed
    return rows


def _row(tz="UTC", auto=True):
    return SimpleNamespace(user_id=7, display_name="", instructions="", tone="balanced",
                           timezone=tz, timezone_auto=auto, language="")


def test_a_new_user_gets_their_device_timezone(rows):
    out = st.adopt_device_timezone("7", "Asia/Kolkata")
    assert out.timezone == "Asia/Kolkata" and out.timezone_auto
    assert rows[7].timezone == "Asia/Kolkata"
    assert rows["retimed"] == [("7", "Asia/Kolkata")]        # daily tasks follow


def test_travelling_moves_the_timezone(rows):
    rows[7] = _row("Asia/Kolkata")
    assert st.adopt_device_timezone("7", "Europe/London").timezone == "Europe/London"


def test_a_pinned_timezone_is_left_alone(rows):
    rows[7] = _row("Asia/Kolkata", auto=False)
    assert st.adopt_device_timezone("7", "Europe/London").timezone == "Asia/Kolkata"
    assert rows["retimed"] == []


def test_junk_or_unchanged_timezones_do_nothing(rows):
    rows[7] = _row("Asia/Kolkata")
    assert st.adopt_device_timezone("7", "Mars/Olympus").timezone == "Asia/Kolkata"
    assert st.adopt_device_timezone("7", "Asia/Kolkata").timezone == "Asia/Kolkata"
    assert st.adopt_device_timezone("7", None).timezone == "Asia/Kolkata"
    assert rows["retimed"] == []


def test_legacy_browser_names_are_stored_by_their_current_name(rows):
    # Chrome reports India as Asia/Calcutta
    assert st.adopt_device_timezone("7", "Asia/Calcutta").timezone == "Asia/Kolkata"


def test_the_prompt_shows_local_time():
    from datetime import datetime, timezone
    block = st.prompt_block(st.Settings(timezone="Asia/Kolkata"), now=datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc))
    assert "Asia/Kolkata (local time now: Friday 2026-10-02 19:00)" in block
