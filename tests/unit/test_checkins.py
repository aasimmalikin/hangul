"""The morning check-in on Today: the streak, Hangul's reply, and the prompt line."""

from datetime import date, timedelta

import pytest

from harness.db import checkins

TODAY = date(2026, 10, 5)


def days(*offsets: int) -> set[str]:
    return {(TODAY - timedelta(days=o)).isoformat() for o in offsets}


def test_streak_counts_consecutive_days_ending_today():
    n, week = checkins.streak_from(days(0, 1, 2, 4), TODAY)
    assert n == 3
    assert week == [False, False, True, False, True, True, True]      # oldest first, today last


def test_streak_still_counts_before_todays_check_in():
    # not checked in yet today: yesterday's run is still alive (encouragement, not a debt)
    assert checkins.streak_from(days(1, 2, 3), TODAY)[0] == 3


def test_a_gap_ends_the_streak():
    assert checkins.streak_from(days(2, 3, 4), TODAY)[0] == 0
    assert checkins.streak_from(set(), TODAY) == (0, [False] * 7)


def test_every_mood_has_a_reply_and_a_prompt_line():
    for mood in ("great", "ok", "tired", "busy"):
        assert checkins.reply_for(mood)
        assert checkins.prompt_line(mood).startswith("How they said they feel today:")
    assert "light" in checkins.prompt_line("tired")
    assert checkins.prompt_line(None) == "" and checkins.prompt_line("ecstatic") == ""


def test_unknown_moods_are_refused():
    with pytest.raises(ValueError):
        checkins.record("1", TODAY, "ecstatic")


def test_mood_now_never_raises_without_a_database(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no db")
    monkeypatch.setattr(checkins, "today_mood", boom)
    assert checkins.mood_now("1", "Asia/Kolkata") is None
