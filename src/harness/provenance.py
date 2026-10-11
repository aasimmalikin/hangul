"""Where an instruction came from: the chat and the user's own words.

The Kept tab shows every lasting thing the user asked for ("remind me to call
mum at 6") next to what Hangul did about it, and opens the chat it came from.
For that, the rows a run creates -- reminders, list items, notes, memories,
and the actions logged in ``kept_actions`` -- carry the conversation id and
the question that caused them.

Like the run meter (billing/meter.py) this is a ContextVar, so it follows the
run into ``asyncio.to_thread`` and every nested call without changing a tool
or db signature. ``source(...)`` opens it around a run; the db writers read
``current()``. With none open (the REST routes, tests) rows just have no source.
"""

import fnmatch
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

SAID_MAX = 500


@dataclass(frozen=True)
class Source:
    user_id: str
    conversation_id: str | None
    said: str

    def stamp(self) -> dict:
        """The columns a created row takes from its source."""
        return {"conversation_id": self.conversation_id, "said": self.said or None}


_current: ContextVar[Source | None] = ContextVar("hangul_source", default=None)


def current() -> Source | None:
    return _current.get()


def stamp() -> dict:
    s = _current.get()
    return s.stamp() if s else {}


def begin(user_id: str, conversation_id: str | None, said: str) -> None:
    """Open a source for the rest of this task (a request handler whose
    context ends with it, like /approve's meter)."""
    _current.set(Source(user_id, conversation_id, " ".join((said or "").split())[:SAID_MAX]))


@contextmanager
def source(user_id: str, conversation_id: str | None, said: str):
    token = _current.set(Source(user_id, conversation_id, " ".join((said or "").split())[:SAID_MAX]))
    try:
        yield
    finally:
        _current.reset(token)


# ------------------------------------------------- actions worth recording
# Tools whose effect lasts outside the chat and has no row of its own.
# Reminders, lists, notes and memories are not here: their own rows are the
# record. Reads are never here.

ACTIONS: dict[str, str] = {
    "gmail__send_*": "Email",
    "gmail__create_draft": "Email",
    "calendar__create_event": "Calendar",
    "calendar__update_event": "Calendar",
    "calendar__delete_event": "Calendar",
    "sheets__append_rows": "Sheets",
    "sheets__create_spreadsheet": "Sheets",
    "docs__append_text": "Docs",
    "meet__create_meeting": "Meet",
    "create_file": "File",
    "generate_image": "Image",
    "edit_image": "Image",
    "finish_image": "Image",
    "github__create_issue": "GitHub",
    "github__comment": "GitHub",
    "notion__create_page": "Notion",
    "notion__append_to_page": "Notion",
    "slack__send_message": "Slack",
}


def app_for(tool: str) -> str | None:
    return ACTIONS.get(tool) or next(
        (v for k, v in ACTIONS.items() if "*" in k and fnmatch.fnmatch(tool, k)), None)


def _short(v: object, n: int = 80) -> str:
    s = " ".join(str(v or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(tool: str, args: dict, *, done: bool) -> str:
    """One plain line for a row: what was done, or what is waiting to be done."""
    a = args or {}
    to, subject = _short(a.get("to"), 60), _short(a.get("subject"))
    lines = {
        "gmail__send_message": (f"Sent an email to {to}: {subject}", f"Send an email to {to}: {subject}"),
        "gmail__send_draft": ("Sent a draft email", "Send a draft email"),
        "gmail__create_draft": (f"Drafted an email to {to}: {subject}", f"Draft an email to {to}: {subject}"),
        "calendar__create_event": (f"Added “{_short(a.get('summary'))}” to your calendar",
                                   f"Add “{_short(a.get('summary'))}” to your calendar"),
        "calendar__update_event": ("Changed a calendar event", "Change a calendar event"),
        "calendar__delete_event": ("Deleted a calendar event", "Delete a calendar event"),
        "sheets__append_rows": (f"Added {len(a.get('rows') or [])} row(s) to a sheet",
                                f"Add {len(a.get('rows') or [])} row(s) to a sheet"),
        "sheets__create_spreadsheet": (f"Made the sheet “{_short(a.get('title'))}”",
                                       f"Make the sheet “{_short(a.get('title'))}”"),
        "docs__append_text": ("Added text to a Google Doc", "Add text to a Google Doc"),
        "meet__create_meeting": ("Made a Google Meet link", "Make a Google Meet link"),
        "create_file": (f"Made “{_short(a.get('title'))}” ({_short(a.get('format'), 8).upper()})",
                        f"Make “{_short(a.get('title'))}”"),
        "generate_image": (f"Made an image: {_short(a.get('prompt'))}", f"Make an image: {_short(a.get('prompt'))}"),
        "edit_image": (f"Edited {_short(a.get('image'), 40)}: {_short(a.get('instruction'))}",
                       f"Edit {_short(a.get('image'), 40)}: {_short(a.get('instruction'))}"),
        "finish_image": (f"Made a post: “{_short(a.get('headline') or a.get('image'))}”",
                         f"Make a post: “{_short(a.get('headline') or a.get('image'))}”"),
        "github__create_issue": (f"Opened the issue “{_short(a.get('title'))}” in {_short(a.get('repo'), 40)}",
                                 f"Open the issue “{_short(a.get('title'))}” in {_short(a.get('repo'), 40)}"),
        "github__comment": (f"Commented on {_short(a.get('repo'), 40)}#{a.get('number')}",
                            f"Comment on {_short(a.get('repo'), 40)}#{a.get('number')}"),
        "notion__create_page": (f"Made the Notion page “{_short(a.get('title'))}”",
                                f"Make the Notion page “{_short(a.get('title'))}”"),
        "notion__append_to_page": ("Added to a Notion page", "Add to a Notion page"),
        "slack__send_message": ("Sent a Slack message", "Send a Slack message"),
    }
    if tool in lines:
        return lines[tool][0 if done else 1]
    app = app_for(tool) or tool.split("__")[0].capitalize()
    verb = tool.split("__")[-1].replace("_", " ")
    return f"{app}: {verb}" if done else f"{app}: {verb} (waiting for you)"
