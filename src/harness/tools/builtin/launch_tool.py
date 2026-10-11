"""launch_plan: start a plan for a new business from chat (harness.launch).

The tool doesn't research anything itself: it saves the plan from the
answers the model collected (asking the missing ones with ask_user first),
starts the background build when the user's plan includes live prices, and
shows a card linking to the dashboard. The numbers in the reply are the
dashboard's own (launch/economics.py), never the model's.
"""

import asyncio

from harness.db import launch as db
from harness.launch import kinds, pipeline
from harness.launch import plan as planner
from harness.tools.base import Tool, ToolOutput


def _card(p: dict, acc: dict | None) -> dict:
    e = p["economics"]
    k = kinds.get(p["kind"])
    return {"kind": "launch_plan", "id": p["id"], "title": p["title"], "status": p["status"], "sourced": p["sourced"],
            "unit": k.unit if k else "sale", "startup_total": e["startup_total"], "profit": e["profit"],
            "breakeven_per_day": e["breakeven_per_day"], "payback_months": e["payback_months"],
            "items": len([i for i in p["items"] if i.get("include", True)]), "access": acc, "url": f"/launch/{p['id']}"}


def make_launch_plan_tool(user_id: str) -> Tool:
    async def launch_plan(action: str = "start", kind: str = "", city: str = "", area: str = "", size: str = "",
                          renting: str = "", budget: float | None = None, start: str = "", note: str = "") -> ToolOutput | str:
        if action == "list":
            rows = await asyncio.to_thread(db.list_for, user_id)
            if not rows:
                return "The user has no launch plans yet."
            return "The user's launch plans:\n" + "\n".join(
                f"- {r['title']} (/launch/{r['id']}): about ₹{r['startup_total']:,} to start, "
                f"break-even {r['breakeven_per_day'] or '—'} a day{', live prices' if r['sourced'] else ', estimates'}"
                for r in rows[:10])
        k = kinds.get(kind) or kinds.get(kinds.match_kind(f"{kind} {note}") or "")
        if k is None:
            return ("Launch plans cover: " + "; ".join(f"{x.key} = {x.label} ({x.blurb})" for x in kinds.KINDS.values())
                    + ". If the business fits one, call again with that kind; if not, say launch plans don't cover it "
                      "yet and help in chat instead (checklist, rough costs, licences).")
        missing = []
        if not city.strip():
            missing.append("which city (and area) it will be in")
        if size not in kinds.SIZES:
            missing.append("how big it will start: " + "; ".join(f"{s} = {lbl}" for s, lbl in zip(kinds.SIZES, k.size_labels)))
        if missing:
            return ("Before making the plan, ask the user with ask_user (one question at a time, with these as options "
                    "where given): " + " / ".join(missing) + ". Also useful if not yet known: whether they'll rent a "
                    "place (yes / own = their own or family space / no = no place needed) and their budget in rupees.")
        from harness import provenance
        src = provenance.current()
        answers = {"kind": k.key, "city": city, "area": area, "size": size,
                   "renting": renting if renting in kinds.RENTING else ("no" if size == "home" else "yes"),
                   "budget": budget if budget and budget > 0 else None, "start": start, "note": note}
        try:
            p, acc = await pipeline.create(user_id, answers, live=True,
                                           conversation_id=src.conversation_id if src else None)
        except planner.BadAnswer as e:
            return f"Couldn't make the plan: {e}."
        e = p["economics"]
        nums = (f"With Hangul's starting estimates: about ₹{e['startup_total']:,} to start (including "
                f"{e['working_capital_months']:g} months of running costs), break-even at about "
                f"{e['breakeven_per_day'] or '—'} {k.unit}s a day, monthly profit ₹{e['profit']:,} at "
                f"{e['units_per_day']:g} {k.unit}s a day.")
        if p["status"] == "sourcing":
            what = ("Live prices, sellers, industry figures and nearby suppliers are being searched now (a few minutes); "
                    "the dashboard updates by itself and the user gets a notification when it's ready.")
        else:
            what = f"Live prices weren't searched: {acc.detail} Mention it in one sentence (the card has the button)."
        return ToolOutput(
            f"Made the launch plan “{p['title']}” and showed it as a card linking to its dashboard. {nums} {what} "
            "Say the numbers are estimates to plan with, not advice, and that every number can be edited on the "
            "dashboard. Don't list the whole checklist; mention 2-3 things people often forget for this business "
            "(e.g. licences, deposits, working capital).",
            _card(p, acc.as_dict()))

    return Tool(
        name="launch_plan",
        description=(
            "Plan a new business: a checklist of what to buy and arrange (equipment, space, licences, staff, "
            "stock, software), prices and sellers searched on the web, nearby suppliers, industry figures and the "
            "unit economics (start-up cost, break-even, payback) on an editable dashboard. India only. Kinds: "
            + ", ".join(f"{x.key} ({x.label})" for x in kinds.KINDS.values())
            + ". Use it when the user wants to start or open a business, or asks what they'd need and what it would "
              "cost. Collect city and size first (ask_user). action='list' shows their plans."),
        parameter={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["start", "list"]},
                "kind": {"type": "string", "enum": list(kinds.KINDS)},
                "city": {"type": "string"},
                "area": {"type": "string", "description": "Neighbourhood or locality, if known"},
                "size": {"type": "string", "enum": list(kinds.SIZES)},
                "renting": {"type": "string", "enum": list(kinds.RENTING)},
                "budget": {"type": "number", "description": "In rupees, if the user said"},
                "start": {"type": "string", "description": "When they want to open, in their words"},
                "note": {"type": "string", "description": "Anything else they said about the business"},
            },
            "required": ["action"],
        },
        handler=launch_plan,
    )
