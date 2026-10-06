"""The living stag's suggestion: what the user usually asks at this time of day."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from harness import habits

TZ = ZoneInfo("Asia/Kolkata")


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    base = datetime(2026, 10, 4, tzinfo=TZ)
    return (base - timedelta(days=day_offset)).replace(hour=hour, minute=minute)


def test_kinds_by_whole_word():
    assert habits.kind_of("Give me my morning brief") == "brief"
    assert habits.kind_of("summarise my inbox") == "inbox"
    assert habits.kind_of("remind me to call mom at 7") == "reminders"
    assert habits.kind_of("lunch places near me") == "places"
    assert habits.kind_of("what's 2+2") is None
    assert habits.kind_of("emailing") is None            # whole words only


def test_a_habit_needs_three_times_in_the_same_part_of_the_day():
    now = at(0, 8, 15)
    msgs = [(at(1, 8), "brief me"), (at(2, 7, 30), "my morning brief please")]
    s = habits.suggest(msgs, now)
    assert s["learned"] is False and s["kind"] == "brief"      # the default for the morning
    s = habits.suggest(msgs + [(at(3, 9), "brief")], now)
    assert s["learned"] is True and s["count"] == 3
    assert "usually" in s["line"] and s["chips"][0]["label"] == "Brief me"


def test_only_the_current_window_and_the_last_30_days_count():
    now = at(0, 11)                                    # 10:00-12:00
    msgs = [(at(d, 8), "summarise my inbox") for d in range(1, 6)]          # mornings, wrong window
    msgs += [(at(40 + d, 11), "check my calendar") for d in range(5)]        # too old
    s = habits.suggest(msgs, now)
    assert s["learned"] is False and s["kind"] == "inbox"     # the 10-12 default


def test_the_top_habit_wins_and_the_runner_up_becomes_a_second_chip():
    now = at(0, 19)
    msgs = [(at(d, 19), "plan my tomorrow") for d in range(1, 5)] + [(at(d, 20), "add milk to my grocery list") for d in range(1, 4)]
    s = habits.suggest(msgs, now)
    assert s["kind"] == "tomorrow" and s["count"] == 4
    assert [c["label"] for c in s["chips"]] == ["Plan tomorrow", "My lists"]


def test_late_at_night_offers_to_sleep_in():
    s = habits.suggest([], at(0, 1, 30))
    assert s["kind"] == "late" and len(s["chips"]) == 2


def test_utc_timestamps_are_read_in_the_users_timezone():
    now = at(0, 8)
    # 02:30 UTC is 08:00 in Kolkata
    msgs = [(at(d, 8).astimezone(ZoneInfo("UTC")), "brief me") for d in range(1, 4)]
    assert habits.suggest(msgs, now)["learned"] is True
