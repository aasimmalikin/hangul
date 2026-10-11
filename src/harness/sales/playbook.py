"""What to do about a slow day: a fixed playbook per kind of business and per
cause, never improvised by a model. Each suggestion is a ready Brand Studio
post (layout, words, sizes) plus where to share it.

**Every discount is checked against the business's margin**: a sale must still
leave at least ``MIN_MARGIN`` of the price after its variable costs (from the
launch plan, else the kind's usual shares). A discount that doesn't fit is
cut to the largest one that does (in 5% steps); when even 5% doesn't fit, the
suggestion becomes a no-discount one.
"""

from dataclasses import asdict, dataclass

from harness.launch import kinds as launch_kinds
from harness.sales import festivals

MIN_MARGIN = 0.10
SLOW_SHARE = 0.85            # below 85% of this weekday's usual is a slow day


@dataclass
class Idea:
    key: str
    title: str
    idea: str
    layout: str               # Brand Studio layout (brands/finish.py LAYOUTS)
    headline: str             # may contain {pct}
    subline: str = ""
    discount: int = 0         # % off; 0 = no discount
    cta: str = ""
    share: str = "Post it on Instagram and as your WhatsApp status in the morning."


_W = "{weekday}"
PLAYBOOK: dict[str, dict[str, list[Idea]]] = {
    "food": {   # cloud kitchens and cafés
        "weekday": [Idea("weekday_special", f"A {_W} special", f"Give quiet {_W}s a reason: one dish or drink at a special price, only on {_W}s.",
                         "offer", f"{_W} special", "Only today", 15, "Order now"),
                    Idea("combo", "A combo deal", "Pair a best-seller with a drink or dessert at one price: a bigger bill without a big discount.",
                         "showcase", "Combo of the day", "Your favourite + a drink", 10, "Order now")],
        "rain": [Idea("rain_offer", "A rainy-day offer", "People stay in when it rains: push delivery with a small rainy-day offer.",
                      "offer", "Rainy day? We deliver", "Hot and fresh to your door", 10, "Order on delivery"),
                 Idea("hot_drinks", "Hot drinks and snacks", "Rain makes chai, coffee and pakoras sell: lead with them.",
                      "showcase", "Chai + pakora weather", "Made fresh, all evening", 0, "Come in")],
        "month_end": [Idea("value_meal", "A value meal", "Money is tight at the end of the month: a fixed-price meal brings regulars in.",
                           "offer", "Value meal", "Till the 5th", 0, "Order now")],
        "after_festival": [Idea("regulars", "Thank your regulars", "Sales dip after a festival: a loyalty offer brings the regulars back.",
                                "offer", "Welcome back", "A thank-you for our regulars", 10, "Visit us")],
        "trend_down": [Idea("new_item", "Show something new", "A new or seasonal item gives people a reason to come back.",
                            "showcase", "New on the menu", "Try it this week", 0, "Order now")],
    },
    "retail": {
        "weekday": [Idea("weekday_deal", f"A {_W} deal", f"A small deal that runs only on {_W}s builds a habit.",
                         "offer", f"{_W} deal", "In store today", 10, "Visit us")],
        "rain": [Idea("whatsapp_order", "Order on WhatsApp", "On rainy days, let regulars order on WhatsApp and pick up or get it delivered.",
                      "band", "Order on WhatsApp", "We'll pack it for you", 0, "Message us",
                      "Send it to your WhatsApp list of regular customers.")],
        "month_end": [Idea("small_packs", "Small packs and combos", "Before salary day, smaller packs and combos sell better.",
                           "offer", "Small packs, smart prices", "This week only", 0, "Visit us")],
        "after_festival": [Idea("clearance", "A clearance offer", "Clear leftover festival stock before it ages.",
                                "offer", "Festival stock clearance", "While stocks last", 20, "Visit us")],
        "trend_down": [Idea("new_arrivals", "New arrivals", "Show what's new: it gives people a reason to drop in.",
                            "showcase", "New arrivals", "Just in", 0, "Visit us")],
    },
    "salon": {
        "weekday": [Idea("off_peak", "An off-peak offer", f"Fill quiet {_W} slots with an off-peak price.",
                         "offer", f"{_W} off-peak", "Book a slot today", 15, "Book now")],
        "rain": [Idea("rebook", "Move bookings, don't lose them", "Message today's bookings to keep or move their slot.",
                      "band", "Rainy day? Let's reschedule", "Message us to keep or move your slot", 0, "Message us",
                      "Send it to today's bookings on WhatsApp.")],
        "month_end": [Idea("express", "An express service", "A quick, cheaper service suits the end of the month.",
                           "offer", "Express cut", "In and out in 20 minutes", 0, "Book now")],
        "after_festival": [Idea("care", "After-festival care", "Skin and hair care after the festival rush.",
                                "showcase", "Post-festival glow", "Treatment of the week", 10, "Book now")],
        "trend_down": [Idea("bring_friend", "Bring a friend", "Regulars who bring a friend both get a little off.",
                            "offer", "Bring a friend", "Both get a treat", 10, "Book now")],
    },
    "online": {
        "weekday": [Idea("flash", "A 24-hour code", "A short-lived discount code makes people act today.",
                         "offer", "24 hours only", "Use code TODAY", 10, "Shop now")],
        "month_end": [Idea("cod", "Pay later / cash on delivery", "End of the month: remind people they can pay on delivery.",
                           "band", "Pay on delivery", "Order now, pay when it arrives", 0, "Shop now")],
        "after_festival": [Idea("restock", "Back in stock", "Show what's back after the festival rush.",
                                "showcase", "Back in stock", "Your favourites are back", 0, "Shop now")],
        "trend_down": [Idea("review", "Show a happy customer", "A real review builds trust when sales slow.",
                            "quote", "A customer's words here", "A happy customer", 0, "Shop now")],
        "rain": [],
    },
}
GROUP = {"cloud_kitchen": "food", "cafe": "food", "retail_shop": "retail", "salon": "salon", "d2c_brand": "online"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def variable_share(kind: str, plan_assumptions: dict | None) -> float:
    if plan_assumptions and plan_assumptions.get("variable"):
        return min(0.95, sum(float(v.get("pct") or 0) for v in plan_assumptions["variable"]))
    k = launch_kinds.get(kind)
    return sum(v.pct for v in k.variable) if k else 0.5


def safe_discount(wanted: int, var: float) -> int:
    room = 1 - var - MIN_MARGIN
    if wanted <= 0:
        return 0
    best = int(room * 100) // 5 * 5
    return max(0, min(wanted, best))


def causes(f: dict, target, tmax_hot: bool = False) -> list[str]:
    """Why tomorrow is slow, most likely first (from the forecast's reasons and the calendar)."""
    out = []
    for r in f.get("reasons") or []:
        if r["effect"] < -0.03 and r["key"] in ("weekday", "rain", "trend"):
            out.append({"trend": "trend_down"}.get(r["key"], r["key"]))
    if (target.rain or 0) >= 5 and "rain" not in out:
        out.append("rain")
    if festivals.just_after(target.day):
        out.append("after_festival")
    if target.day.day >= 26 or target.day.day == 1:
        out.append("month_end")
    if not out:
        out.append("weekday")
    return list(dict.fromkeys(out))


def is_slow(f: dict, breakeven: float | None) -> tuple[bool, str]:
    """(slow?, why) for a ready forecast."""
    v = f.get("value")
    if v is None or f.get("status") != "ready":
        return False, ""
    if breakeven and v < breakeven:
        return True, "below_breakeven"
    if f.get("typical") and v < SLOW_SHARE * f["typical"]:
        return True, "below_usual"
    return False, ""


def suggest(kind: str, cause_list: list[str], target_day, *, price: float | None, plan_assumptions: dict | None,
            limit: int = 3) -> list[dict]:
    """Ideas for the causes, margin-checked, as Brand Studio-ready dicts."""
    group = PLAYBOOK.get(GROUP.get(kind, "retail"), PLAYBOOK["retail"])
    var = variable_share(kind, plan_assumptions)
    weekday = WEEKDAYS[target_day.weekday()]
    out, seen = [], set()
    for c in cause_list + ["weekday", "trend_down"]:
        for idea in group.get(c, []):
            if idea.key in seen:
                continue
            seen.add(idea.key)
            d = asdict(idea)
            for k in ("title", "idea", "headline", "subline"):
                d[k] = d[k].replace(_W, weekday)
            wanted = idea.discount
            pct = safe_discount(wanted, var)
            d["cause"] = c
            d["discount"] = pct
            d["discount_cut"] = bool(wanted and pct < wanted)
            if wanted and pct == 0:
                d["idea"] += " (No discount: your margin is too thin for one, so make it about the dish or the service.)"
            d["price"] = f"{pct}% OFF" if pct else ""
            d["left_per_sale"] = round(price * (1 - pct / 100) - price * var) if price else None
            d["margin_note"] = (f"After {pct}% off, each sale still leaves about ₹{d['left_per_sale']:,}."
                                if pct and d["left_per_sale"] is not None else "")
            out.append(d)
            if len(out) >= limit:
                return out
    return out
