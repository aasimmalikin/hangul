"""promises: Kept your word from chat and WhatsApp (harness.promises).

The model records a promise when the user mentions one ("I told Priya I'd send
the deck by Friday", "Rahul will send the quote Monday"), including their reply
to Hangul's after-meeting question. Listing, ticking off and chasing go through
here too. Every promise is the user's own row; nothing is sent from this tool
(chasing returns instructions for a draft, and sending waits for approval).
"""

import asyncio
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from harness.db import promises as db
from harness.promises import service
from harness.tools.base import Tool, ToolOutput


def _day(d: str | None) -> str:
    if not d:
        return "no date"
    x = date.fromisoformat(d)
    return f"{x:%a} {x.day} {x:%b}"


def line(p: db.PromiseOut) -> str:
    who = p.who or p.who_email
    side = f"you → {who}" if p.direction == "mine" else f"{who or 'someone'} → you"
    extra = " (they wrote back)" if p.direction == "theirs" and p.last_contact_at else ""
    return f"#{p.id} [{side}] {p.what} · {_day(p.due_on)}{extra}"


def card(items: list[db.PromiseOut], note: str = "") -> dict:
    return {"kind": "promises", "note": note, "promises": [p.as_dict() for p in items]}


def make_promises_tool(user_id: str, tz: str = "UTC") -> Tool:
    async def promises(action: str, direction: str = "", what: str = "", who: str = "", who_email: str = "",
                       due: str = "", promise_id: int | None = None, match: str = "") -> ToolOutput | str:
        if action == "add":
            if direction not in db.DIRECTIONS or not what.strip():
                return "action=add needs direction (mine = the user promised; theirs = someone promised the user) and what."
            due_on = None
            if due:
                try:
                    due_on = date.fromisoformat(due.strip()[:10])
                except ValueError:
                    return f"Could not read the date {due!r}; use 'YYYY-MM-DD'."
            source, email = "chat", who_email.strip()
            if not email and who:
                # a reply to the after-meeting question: the person is in that meeting
                state = await asyncio.to_thread(db.scan_state, user_id)
                recent = service.recent_asked(state["asked"], datetime.now(UTC))
                email = service.match_person(who, recent)
                if email:
                    source = "meeting"
            try:
                p = await asyncio.to_thread(db.add, user_id, direction, what, who=who, who_email=email,
                                            due_on=due_on, source=source)
            except (db.LimitReached, ValueError) as e:
                return str(e)
            follow = ("I'll nudge them if it's late." if direction == "theirs"
                      else "I'll remind the user on the day." if due_on else "It has no date, so no reminder.")
            return ToolOutput(f"Kept: {line(p)}. {follow}", card([p], "Kept"))
        if action == "list":
            items = await asyncio.to_thread(db.list_for, user_id, "open")
            if direction in db.DIRECTIONS:
                items = [p for p in items if p.direction == direction]
            if match:
                m = match.lower()
                items = [p for p in items if m in f"{p.what} {p.who} {p.who_email}".lower()]
            if not items:
                return "No open promises" + (f" matching {match!r}." if match else ".")
            return ToolOutput("Open promises:\n" + "\n".join(line(p) for p in items[:30]), card(items[:30]))
        if action in ("done", "drop", "chase"):
            p = None
            if promise_id is not None:
                p = await asyncio.to_thread(db.get, user_id, int(promise_id))
            elif match.strip():
                found = await asyncio.to_thread(db.find, user_id, match)
                if len(found) > 1:
                    return "Several match: " + "; ".join(line(x) for x in found[:6]) + ". Ask which, or use promise_id."
                p = found[0] if found else None
            if p is None:
                return "No such open promise. Use action=list to find it."
            if action == "chase":
                if p.direction != "theirs":
                    return "Only a promise someone made to the user can be chased."
                if not (await asyncio.to_thread(service.access, user_id))["chase"]:
                    return ToolOutput("Chasing promises is part of Plus.",
                                      {"kind": "upgrade", "feature": "Chasing promises", "plan": "plus", "plan_label": "Plus"})
                await asyncio.to_thread(db.mark_chased, user_id, p.id)
                return ("Now draft the follow-up with gmail__create_draft (never send without the user's OK): "
                        + service.chase_prompt(p))
            p = await asyncio.to_thread(db.update, user_id, p.id, status="done" if action == "done" else "dropped")
            return ToolOutput(f"{'Marked kept' if action == 'done' else 'Dropped'}: {line(p)}",
                              card([p], "Kept" if action == "done" else "Dropped"))
        return "action must be add, list, done, drop or chase."

    today = datetime.now(ZoneInfo(tz or "UTC")).date()
    return Tool(
        name="promises",
        description=(
            "Promises the user made, and promises other people made to the user. Record one whenever the user "
            "mentions a commitment: 'I told Priya I'd send the deck by Friday' (direction=mine, who=Priya) or "
            "'Rahul will send the quote on Monday' (direction=theirs, who=Rahul), including when they answer "
            "'anything promised?' after a meeting (record each one). `what` starts with a verb, from the "
            "promiser's side ('Send the Q3 deck'). `due` is a date 'YYYY-MM-DD' worked out from today "
            f"({today.isoformat()}, {today:%A}); leave it empty if none was said. action=list (optional direction, "
            "match); done / drop with promise_id or match; chase (a promise owed to the user) gives instructions "
            "for a follow-up draft. Different from reminders: use promises when someone committed to something."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list", "done", "drop", "chase"]},
                "direction": {"type": "string", "enum": ["mine", "theirs"]},
                "what": {"type": "string"},
                "who": {"type": "string", "description": "The other person's name."},
                "who_email": {"type": "string"},
                "due": {"type": "string", "description": "YYYY-MM-DD"},
                "promise_id": {"type": "integer"},
                "match": {"type": "string", "description": "Words from the promise or the person's name."},
            },
            "required": ["action"],
        },
        handler=promises,
    )

