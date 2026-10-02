"""Reminders, lists and notes: the agent tools.

Three tools rather than nine (one per action) because every tool costs prompt
tokens on every turn; each takes an ``action``. Times are in the user's own
timezone (their Personalisation setting) -- the model sees their local time in
the system prompt and passes local wall-clock times, never UTC.

Each returns ``ToolOutput``: text for the model plus a ``ui`` card the chat
renders (a reminder confirmation, a checklist, a notes list).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from harness.db import personal as db
from harness.tools.base import Tool, ToolOutput


def _local(dt_iso: str, tz: str) -> datetime:
    """'2026-10-02T19:00' (local, no offset) -> aware datetime in ``tz``.
    An explicit offset in the string is respected."""
    dt = datetime.fromisoformat(dt_iso.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))


def _fmt(dt_iso: str, tz: str) -> str:
    dt = datetime.fromisoformat(dt_iso).astimezone(ZoneInfo(tz))
    return dt.strftime("%a %d %b, %H:%M")


def make_reminders_tool(user_id: str, tz: str = "UTC") -> Tool:
    async def reminders(action: str, text: str = "", when: str = "", in_minutes: int | None = None,
                        reminder_id: int | None = None) -> ToolOutput | str:
        if action == "add":
            if not text.strip():
                return "Say what to remind the user about (text)."
            try:
                if in_minutes is not None:
                    due = datetime.now(UTC) + timedelta(minutes=max(1, int(in_minutes)))
                elif when:
                    due = _local(when, tz)
                else:
                    return "Give a time: `when` as local 'YYYY-MM-DDTHH:MM', or `in_minutes`. Ask the user if unclear."
            except ValueError:
                return f"Could not read the time {when!r}; use local 'YYYY-MM-DDTHH:MM'."
            if due <= datetime.now(UTC):
                return "That time has already passed. Ask the user for a future time."
            try:
                r = await asyncio.to_thread(db.add_reminder, user_id, text, due)
            except db.LimitReached as e:
                return str(e)
            when_txt = _fmt(r.due_at, tz)
            return ToolOutput(
                f"Reminder #{r.id} set for {when_txt} ({tz}): {r.text}. It will appear in the app and be emailed.",
                {"kind": "reminder", "reminder": r.as_dict(), "local": when_txt, "tz": tz})
        if action == "list":
            items = await asyncio.to_thread(db.list_reminders, user_id, ("pending",))
            if not items:
                return "The user has no upcoming reminders."
            lines = [f"#{r.id} {_fmt(r.due_at, tz)}: {r.text}" for r in items]
            return ToolOutput("Upcoming reminders:\n" + "\n".join(lines),
                              {"kind": "reminders", "tz": tz,
                               "reminders": [{**r.as_dict(), "local": _fmt(r.due_at, tz)} for r in items]})
        if action == "cancel":
            if reminder_id is None:
                return "Give reminder_id (from action=list) to cancel."
            r = await asyncio.to_thread(db.set_reminder_status, user_id, int(reminder_id), "cancelled")
            return f"Cancelled reminder #{reminder_id}: {r.text}" if r else f"No reminder #{reminder_id}."
        return "action must be add, list or cancel."

    return Tool(
        name="reminders",
        description=(
            "Set, list or cancel the user's reminders. Use for 'remind me to … at/in …'. "
            "action=add needs `text` and either `when` (the user's LOCAL time as 'YYYY-MM-DDTHH:MM' -- work it "
            "out from the current local time in the system prompt) or `in_minutes`. A reminder pops up in the "
            "app and is emailed to the user at that time. action=list shows upcoming ones; action=cancel takes "
            "`reminder_id`. If the time is ambiguous ('this evening'), ask with ask_user rather than guess."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "cancel"]},
                "text": {"type": "string", "description": "What to remind about, phrased for the user."},
                "when": {"type": "string", "description": "Local time 'YYYY-MM-DDTHH:MM'."},
                "in_minutes": {"type": "integer", "description": "Alternative to `when`: minutes from now."},
                "reminder_id": {"type": "integer"},
            },
            "required": ["action"],
        },
        handler=reminders,
    )


def make_lists_tool(user_id: str) -> Tool:
    async def lists(action: str, list: str = "", items: list[str] | None = None, item: str = "") -> ToolOutput | str:  # noqa: A002
        name = db.norm_list(list) if list else None

        async def card(note: str) -> ToolOutput:
            rows = await asyncio.to_thread(db.list_todos, user_id, name)
            lines = [f"- {r.text}" + (f" ({r.list_name})" if not name else "") for r in rows]
            body = "\n".join(lines) or "(empty)"
            return ToolOutput(f"{note}\n{name or 'All lists'}:\n{body}",
                              {"kind": "todo_list", "list": name, "items": [r.as_dict() for r in rows]})

        if action == "add":
            new = [i for i in (items or ([item] if item else [])) if i.strip()]
            if not new:
                return "Give the item(s) to add."
            try:
                await asyncio.to_thread(db.add_todos, user_id, name or "To-do", new)
            except db.LimitReached as e:
                return str(e)
            name = name or "To-do"
            return await card(f"Added {len(new)} item(s) to {name}.")
        if action == "show":
            if name is None:
                names = await asyncio.to_thread(db.list_names, user_id)
                if not names:
                    return "The user has no lists yet."
            return await card("Current items:")
        if action in ("done", "remove"):
            if not item.strip():
                return "Give `item` (some words from the item's text)."
            matches = await asyncio.to_thread(db.find_todos, user_id, item, name)
            if not matches:
                return f"No open item matching {item!r}" + (f" on {name}." if name else ".")
            if len(matches) > 1:
                return "Several items match: " + "; ".join(f"{m.text} ({m.list_name})" for m in matches) + \
                       ". Ask which one, or use more words."
            m = matches[0]
            if action == "done":
                await asyncio.to_thread(db.set_todo_done, user_id, m.id, True)
            else:
                await asyncio.to_thread(db.delete_todo, user_id, m.id)
            name = name or m.list_name
            return await card(f"{'Ticked off' if action == 'done' else 'Removed'}: {m.text}.")
        return "action must be add, show, done or remove."

    return Tool(
        name="lists",
        description=(
            "The user's to-do and shopping lists. action=add with `items` (and optional `list`, e.g. 'Shopping'; "
            "default 'To-do'); action=show (optional `list`; omit for every list); action=done / remove with "
            "`item` = words from the item. Use for 'add milk to my shopping list', 'what's on my to-do list', "
            "'I bought the eggs'. The user can also tick items in the card."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "show", "done", "remove"]},
                "list": {"type": "string", "description": "List name, e.g. 'Shopping'. Default 'To-do'."},
                "items": {"type": "array", "items": {"type": "string"}},
                "item": {"type": "string"},
            },
            "required": ["action"],
        },
        handler=lists,
    )


def make_notes_tool(user_id: str) -> Tool:
    async def notes(action: str, text: str = "", query: str = "", note_id: int | None = None) -> ToolOutput | str:
        if action == "add":
            if not text.strip():
                return "Give the note's text."
            try:
                n = await asyncio.to_thread(db.add_note, user_id, text)
            except db.LimitReached as e:
                return str(e)
            return ToolOutput(f"Saved note #{n.id}.", {"kind": "notes", "notes": [n.as_dict()], "saved": True})
        if action == "search":
            found = await asyncio.to_thread(db.search_notes, user_id, query)
            if not found:
                return "No notes found" + (f" for {query!r}." if query else ".")
            body = "\n".join(f"#{n.id} ({n.created_at[:10]}): {n.text}" for n in found)
            return ToolOutput(body, {"kind": "notes", "notes": [n.as_dict() for n in found]})
        if action == "delete":
            if note_id is None:
                return "Give note_id (from action=search)."
            ok = await asyncio.to_thread(db.delete_note, user_id, int(note_id))
            return f"Deleted note #{note_id}." if ok else f"No note #{note_id}."
        return "action must be add, search or delete."

    return Tool(
        name="notes",
        description=(
            "Quick notes the user asks you to keep ('note: car service is due in March', 'save this recipe'). "
            "action=add with `text`; action=search with `query` (words to look for; empty = newest notes); "
            "action=delete with `note_id`. Different from `remember`, which is for facts ABOUT the user; "
            "notes are things the user wants to write down and look up later."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "search", "delete"]},
                "text": {"type": "string"},
                "query": {"type": "string"},
                "note_id": {"type": "integer"},
            },
            "required": ["action"],
        },
        handler=notes,
    )
