"""What a scheduled task may do without asking, which tasks must ask first, and where.

A scheduled task runs while the user is away, so it shouldn't stop for the things
they set it up to do. The rule is fixed rather than a per-task setting:

- Anything not DESTRUCTIVE runs (reading mail, finding free time, reminders...).
- Calendar actions (``calendar__*``) and saving an email draft run without asking:
  they stay inside the user's own account.
- Sending email, and other DESTRUCTIVE actions (GitHub, Slack, Notion, Docs, Sheets
  writes), wait for an Approve tap. A task that will do one runs ``LEAD_MINUTES``
  early, so the approval reaches the user before the time they picked -- on WhatsApp
  on Plus and Pro, by email on Free (or when WhatsApp isn't linked) -- and the action
  happens as soon as they approve.

A run that has read suspicious content still asks for everything: the loop checks
taint before it consults this (see agent.loop's ``pre_approved``).
"""

import re

# a scheduled run may make these calls without the user's tap
AUTO_PREFIXES: tuple[str, ...] = ("calendar__",)
AUTO_TOOLS: tuple[str, ...] = ("gmail__create_draft",)

# connectors whose writes always wait for an Approve tap in a scheduled run
ASKS_FIRST_APPS: tuple[str, ...] = ("github", "slack", "notion", "docs", "sheets")

# how early such a task runs, so the approval arrives before its time
LEAD_MINUTES = 5

# "send / reply / forward …", "email Priya …" -- but not "email me", "emails from today"
_SENDS = re.compile(r"\b(send|reply|respond|forward)\b"
                    r"|\be-?mail\s+(?!me\b|my\b|from\b|about\b|the\b|that\b|this\b|and\b|in\b|for\b|i\b)\w",
                    re.IGNORECASE)


def allows(tool: str, args: dict | None = None) -> bool:
    """True when a scheduled run may make this call without the user's tap."""
    return tool.startswith(AUTO_PREFIXES) or tool in AUTO_TOOLS


def sends_email(question: str) -> bool:
    return bool(_SENDS.search(question or ""))


def asks_first(connectors: list[str] | tuple[str, ...], question: str = "") -> list[str]:
    """The task's apps whose actions will wait for the user's OK: the always-ask apps,
    and Gmail when the question means sending something."""
    out = [c for c in connectors if c in ASKS_FIRST_APPS]
    if "gmail" in connectors and sends_email(question):
        out.insert(0, "gmail")
    return out
