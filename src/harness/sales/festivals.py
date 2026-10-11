"""Indian festivals and holidays that move a small business's sales.

Written out by date because most follow lunar calendars (a Diwali a week
earlier moves the whole season). National, widely observed days only; a
region's own festivals can be added per business later.

**Check this table every year.** Eid dates depend on the moon and can move
by a day. Dates past ``COVERED_UNTIL`` are unknown: the forecast then simply
has no festival signal, and ``covers()`` lets callers say so.
"""

from datetime import date, timedelta

COVERED_UNTIL = date(2027, 12, 31)

FESTIVALS: dict[date, str] = {
    # 2025
    date(2025, 1, 14): "Makar Sankranti / Pongal",
    date(2025, 1, 26): "Republic Day",
    date(2025, 3, 14): "Holi",
    date(2025, 3, 31): "Eid al-Fitr",
    date(2025, 6, 7): "Eid al-Adha",
    date(2025, 8, 9): "Raksha Bandhan",
    date(2025, 8, 15): "Independence Day",
    date(2025, 8, 16): "Janmashtami",
    date(2025, 8, 27): "Ganesh Chaturthi",
    date(2025, 10, 2): "Dussehra",
    date(2025, 10, 18): "Dhanteras",
    date(2025, 10, 20): "Diwali",
    date(2025, 12, 25): "Christmas",
    date(2025, 12, 31): "New Year's Eve",
    # 2026
    date(2026, 1, 14): "Makar Sankranti / Pongal",
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 4): "Holi",
    date(2026, 3, 20): "Eid al-Fitr",
    date(2026, 5, 27): "Eid al-Adha",
    date(2026, 8, 15): "Independence Day",
    date(2026, 8, 28): "Raksha Bandhan",
    date(2026, 9, 4): "Janmashtami",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 6): "Dhanteras",
    date(2026, 11, 8): "Diwali",
    date(2026, 12, 25): "Christmas",
    date(2026, 12, 31): "New Year's Eve",
    # 2027: DoPT's gazetted and restricted holiday lists (O.M. 12/2/2023-JCA, 16 Jul 2026);
    # Dhanteras isn't on them (Drik Panchang). Eid dates move with the moon: recheck in the year.
    date(2027, 1, 14): "Makar Sankranti / Pongal",
    date(2027, 1, 26): "Republic Day",
    date(2027, 3, 10): "Eid al-Fitr",
    date(2027, 3, 23): "Holi",
    date(2027, 5, 17): "Eid al-Adha",
    date(2027, 8, 15): "Independence Day",
    date(2027, 8, 17): "Raksha Bandhan",
    date(2027, 8, 25): "Janmashtami",
    date(2027, 9, 4): "Ganesh Chaturthi",
    date(2027, 10, 9): "Dussehra",
    date(2027, 10, 27): "Dhanteras",
    date(2027, 10, 29): "Diwali",
    date(2027, 12, 25): "Christmas",
    date(2027, 12, 31): "New Year's Eve",
}


def covers(d: date) -> bool:
    return d <= COVERED_UNTIL


def festival_on(d: date) -> str | None:
    return FESTIVALS.get(d)


def eve_of(d: date) -> str | None:
    """The festival tomorrow, if any (the day before is often busy for shops)."""
    return FESTIVALS.get(d + timedelta(days=1))


def just_after(d: date, days: int = 3) -> str | None:
    """The festival 1-3 days ago, if any (sales usually dip after one)."""
    return next((FESTIVALS[d - timedelta(days=k)] for k in range(1, days + 1) if d - timedelta(days=k) in FESTIVALS), None)
