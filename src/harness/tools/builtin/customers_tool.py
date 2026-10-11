"""customers: the shop's own customer list from chat and WhatsApp (db/customers.py).

Every plan. The model only turns the owner's words into fields ("add Riya,
98765 43210, birthday 12 March"); matching, de-duplicating and the birthday
and "haven't been in" lists are code. Nothing here messages a customer.
"""

import asyncio
from datetime import date

from harness.db import customers as db
from harness.sales.service import local_today
from harness.tools.base import Tool, ToolOutput


def _line(c: dict) -> str:
    bits = [c["name"]]
    if c.get("phone"):
        bits.append(c["phone"])
    if c.get("birthday"):
        bits.append(f"birthday {c['birthday']}")
    if c.get("visits"):
        bits.append(f"{c['visits']} visit(s), last {c['last_visit']}")
    if c.get("note"):
        bits.append(c["note"])
    return " · ".join(bits)


def _card(title: str, items: list[dict]) -> dict:
    return {"kind": "customers", "title": title, "items": items[:20], "url": "/customers"}


def make_customers_tool(user_id: str) -> Tool:
    async def customers(action: str = "find", name: str = "", phone: str = "", birthday: str = "", note: str = "",
                        query: str = "") -> ToolOutput | str:
        if action == "add":
            try:
                row, created = await asyncio.to_thread(db.add, user_id, name, phone, birthday, note)
            except ValueError as e:
                return {"name": "Ask the customer's name.", "phone": "That phone number doesn't look right; ask again.",
                        "birthday": "That birthday isn't a real date; ask again (e.g. 12 March)."}.get(str(e), "Check the details.")
            except db.TooMany:
                return f"The customer list is full ({db.MAX_PER_USER:,}). Tell the user."
            verb = "Added" if created else "Updated"
            return ToolOutput(f"{verb} {_line(row)}. Read it back so the user can correct it.",
                              _card(f"{verb} a customer", [row]))

        if action in ("find", "list"):
            rows = await asyncio.to_thread(db.find, user_id, query or name, 20)
            if not rows:
                return "No customers match." if (query or name) else "The customer list is empty. Offer to add someone."
            return ToolOutput(f"{len(rows)} customer(s): " + "; ".join(_line(c) for c in rows),
                              _card("Customers", rows))

        if action == "birthdays":
            today = await asyncio.to_thread(local_today, user_id)
            rows = await asyncio.to_thread(db.upcoming_birthdays, user_id, today, 7)
            if not rows:
                return "No customer birthdays in the next 7 days."
            text = "; ".join(f"{b['name']} on {date.fromisoformat(b['date']):%a %d %b}"
                             + (f" (turns {b['turns']})" if b.get("turns") else "") for b in rows)
            return ToolOutput("Customer birthdays this week: " + text + ". Offer to draft a wish they can send.",
                              _card("Birthdays this week", rows))

        if action == "lapsed":
            today = await asyncio.to_thread(local_today, user_id)
            rows = await asyncio.to_thread(db.lapsed, user_id, today)
            if not rows:
                return "No regulars have been away for more than 30 days."
            return ToolOutput("Regulars who haven't been in for a while: "
                              + "; ".join(f"{c['name']} ({c['days_away']} days)" for c in rows)
                              + ". Offer a short 'we miss you' message the owner can send themselves.",
                              _card("Haven't been in for a while", rows))

        # visit / update / remove act on one customer, found by name or phone
        who = (query or name or (phone if action != "update" else "")).strip()
        if not who:
            return "Ask which customer they mean."
        rows = await asyncio.to_thread(db.find, user_id, who, 5)
        if not rows:
            return "No customer matches; ask who they mean, or add them."
        exact = next((c for c in rows if c["name"].lower() == who.lower()), None)
        if len(rows) > 1 and exact is None:
            return "Several customers match: " + "; ".join(_line(c) for c in rows) + ". Ask which one."
        c = exact or rows[0]
        if action == "visit":
            today = await asyncio.to_thread(local_today, user_id)
            row = await asyncio.to_thread(db.visit, user_id, c["id"], today)
            return ToolOutput(f"Noted a visit from {row['name']} today ({row['visits']} so far).", _card("Visit noted", [row]))
        if action == "update":
            fields = {k: v for k, v in (("phone", phone), ("birthday", birthday), ("note", note)) if v}
            if not fields:
                return "Say what to change (phone, birthday or note)."
            try:
                row = await asyncio.to_thread(lambda: db.update(user_id, c["id"], **fields))
            except ValueError:
                return "That phone number or birthday doesn't look right; ask again."
            return ToolOutput(f"Updated {_line(row)}.", _card("Updated a customer", [row]))
        if action == "remove":
            await asyncio.to_thread(db.remove, user_id, c["id"])
            return f"Removed {c['name']} from the customer list."
        return "Unknown action; use add, find, list, visit, update, remove, birthdays or lapsed."

    return Tool(
        name="customers",
        description=(
            "The user's own customer list for their shop or business. action='add' with name and, if given, phone, "
            "birthday ('12 March', '12/03', or with the year) and a short note; adding someone already there updates "
            "them. 'find' (query = part of a name or number) or 'list'; 'visit' notes they came in today; 'update' or "
            "'remove' one (query = their name or number); 'birthdays' = the next 7 days; 'lapsed' = regulars who "
            "haven't been in for over 30 days. Never invent details; never message customers yourself."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "find", "list", "visit", "update", "remove", "birthdays", "lapsed"]},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "birthday": {"type": "string"},
                "note": {"type": "string", "description": "e.g. 'likes masala chai', 'orders on Fridays'"},
                "query": {"type": "string", "description": "Who, for find / visit / update / remove"},
            },
            "required": ["action"],
        },
        handler=customers,
    )
