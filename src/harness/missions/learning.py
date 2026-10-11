"""Which slow-day idea to try: the ones that worked for *this* business first.

Each finished, measured slow-day mission is one result for its idea: the day's
sales against the forecast made before the offer (``lift_pct``). An idea's
score is the sum of its results over (tries + 1), i.e. its average pulled
towards zero by one imaginary "no effect" try, so:

  worked before   > 0   suggested first
  never tried     = 0   next, in the playbook's own order (so new ideas get tried)
  didn't work     < 0   last

One lucky day can't lock an idea in, and one bad day doesn't bury it.
"""

from harness.db import missions as db


def stats(business_id: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in db.measured(business_id):
        key = ((m["data"].get("idea") or {}).get("key"))
        o = m["data"].get("outcome") or {}
        if not key or "lift_pct" not in o:
            continue
        s = out.setdefault(key, {"tries": 0, "sum": 0.0, "worked": 0})
        s["tries"] += 1
        s["sum"] += float(o["lift_pct"])
        s["worked"] += o.get("verdict") == "worked"
    for s in out.values():
        s["score"] = s["sum"] / (s["tries"] + 1)
        s["avg_pct"] = s["sum"] / s["tries"]
    return out


def note(s: dict | None) -> str:
    if not s:
        return ""
    times = "once" if s["tries"] == 1 else f"{s['tries']} times"
    pct = round(s["avg_pct"] * 100)
    if pct > 0:
        return f"Tried {times} here: on average {pct}% above my forecast."
    return f"Tried {times} here without a clear lift, so it's lower on my list."


def rank(business_id: int, ideas: list[dict]) -> list[dict]:
    st = stats(business_id)
    order = {i["key"]: n for n, i in enumerate(ideas)}
    ranked = sorted(ideas, key=lambda i: (-(st.get(i["key"], {}).get("score", 0.0)), order[i["key"]]))
    return [{**i, "track": st.get(i["key"]), "track_note": note(st.get(i["key"]))} for i in ranked]
