"""The slow-day mission: Hangul carries a slow day from the forecast to the result.

  1 spot      the evening alert finds tomorrow slow (sales.service.evening_alerts)
  2 prepare   pick the idea that has worked best for this business, render the
              post with its brand (Pillow, no AI) and write the message for regulars
  3 approve   one question, on WhatsApp and the owner's devices: "Go ahead?"
              (skipped once the owner has said Hangul needn't ask: earned autonomy)
  4 check_in  that evening: "How did today go?" (unless already logged)
  5 measure   the logged sales against the forecast and its range; the result is
              told to the owner and remembered, so the next pick is better

No model calls anywhere in it. Hangul doesn't post to Instagram or message
customers itself: "going ahead" records the offer (the forecast learns from
it) and hands the owner a ready post and a ready message to forward.
"""

import asyncio
from datetime import date, timedelta

from harness.config import get_settings
from harness.db import missions as db
from harness.db import sales as sales_db
from harness.logging import log
from harness.missions import engine, learning
from harness.missions.engine import Ctx, ask, done, skip, stop, wait
from harness.missions.tell import tell

KIND = "slow_day"
TRUST_AFTER = 3            # go-aheads in a row before Hangul offers to stop asking
GRACE_DAYS = 2             # how long after the day to wait for its sales
LAST_CALL_HOUR = 14        # on the day itself, an unanswered go-ahead expires at 2 pm


def scope(business_id: int) -> str:
    return f"{KIND}:{business_id}"


def _local(user_id: str) -> tuple[date, int]:
    from harness.sales import service
    return service.local_today(user_id), service._local_hour(user_id)


def _app(path: str) -> str:
    return get_settings().app_url.rstrip("/") + path


def _rs(x: float | None) -> str:
    return f"₹{round(x or 0):,}"


def page(m: dict) -> str:
    return f"/missions/{m['id']}"


# ------------------------------------------------------------ starting one

async def consider(user_id: str, business: dict, ov: dict) -> bool:
    """Start the mission for a slow tomorrow (the evening alert calls this).
    True when a mission handles the day (started now or already running), so the
    plain alert isn't sent as well; False when missions aren't on the plan or
    there's no idea to try."""
    from harness.missions import allowed
    if not ov.get("ideas") or not await asyncio.to_thread(allowed, user_id):
        return False
    tomorrow = date.fromisoformat(ov["tomorrow"])
    if await asyncio.to_thread(db.exists, user_id, KIND, tomorrow, business["id"]):
        return True
    f = ov["forecast"]
    data = {
        "business_name": business["name"], "weekday": tomorrow.strftime("%A"),
        "forecast": {k: f.get(k) for k in ("value", "low", "high", "typical", "accuracy")},
        "breakeven": (ov.get("slow") or {}).get("breakeven"), "why": (ov.get("slow") or {}).get("why"),
        "ideas": ov["ideas"], "avg_bill": ov.get("avg_bill"), "brand_id": business.get("brand_id"),
    }
    return await engine.begin(user_id, KIND, tomorrow, data, business_id=business["id"]) is not None


# ------------------------------------------------------------ the steps

async def _spot(ctx: Ctx) -> engine.Outcome:
    f, be = ctx.data["forecast"], ctx.data.get("breakeven")
    note = f"About {_rs(f['value'])} expected"
    if be and f["value"] < be:
        note += f", under your break-even of {_rs(be)}"
    elif f.get("typical"):
        note += f"; a usual {ctx.data['weekday']} is {_rs(f['typical'])}"
    return done(note + ".")


def _sample_photo(folder, brand) -> str:
    """A photo-free background in the brand's colours, made once per brand."""
    from harness.brands import finish as finisher
    name = f"mission-sample-brand-{brand.id}.jpg"
    if not (folder / name).is_file():
        finisher.sample_photo(brand, 1600, 1600).save(folder / name, "JPEG", quality=90)
    return name


def _render(user_id: str, brand_id: int | None, idea: dict) -> dict | None:
    """The idea as a Brand Studio post (post + story), saved in the brand's posts."""
    from harness.brands import finish as finisher
    from harness.db import brands as brands_db
    from harness.tools.builtin.files import user_folder
    brand = brands_db.usable(user_id, brand_id) if brand_id else None
    if brand is None:
        return None
    folder = user_folder(user_id)
    photos = [a for a in brands_db.list_assets(user_id, brand.id) if (folder / a.name).is_file()]
    photo = photos[0].name if photos else _sample_photo(folder, brand)
    words = {k: idea.get(k) or "" for k in ("headline", "subline", "price", "cta")}
    layout = idea.get("layout") if idea.get("layout") in finisher.LAYOUTS else "band"
    files = finisher.finish(folder / photo, folder, brand, headline=words["headline"], subline=words["subline"],
                            price=words["price"], cta=words["cta"] or brand.cta or "", sizes=["post", "story"],
                            logo_path=folder / brand.logo if brand.logo else None, layout=layout)
    post = brands_db.add_post(user_id, brand.id, kind="single", layout=layout, words={k: v for k, v in words.items() if v},
                              slides=[], sizes=["post", "story"], files=files)
    return {"post_id": post.id, "files": [f["name"] for f in files], "brand_name": brand.name,
            "handle": getattr(brand, "handle", "") or "", "photo": "library" if photos else "sample"}


def share_text(data: dict) -> str:
    """The message for the owner to forward to regulars (or use as a status)."""
    i = data["idea"]
    head = i.get("headline", "")
    if i.get("price"):
        head += f" ({i['price']})"
    lines = [f"*{head}*", i.get("subline", "")]
    if i.get("cta"):
        lines.append(f"{i['cta']} - {data.get('brand_name') or data['business_name']}")
    if data.get("handle"):
        lines.append(data["handle"])
    return "\n".join(x for x in lines if x)


async def _prepare(ctx: Ctx) -> engine.Outcome:
    ranked = await asyncio.to_thread(learning.rank, ctx.mission["business_id"], ctx.data["ideas"])
    idea = ranked[0]
    got = await asyncio.to_thread(_render, ctx.user_id, ctx.data.get("brand_id"), idea)
    data = {"idea": idea, "ideas": ranked, **(got or {}), "post_id": (got or {}).get("post_id")}
    data["share_text"] = share_text({**ctx.data, **data})
    note = idea["title"] + (": the post is ready in 2 sizes." if got else ". (Link a brand to get the post made too.)")
    return done(note, **data)


def expired(m: dict, today: date, hour: int) -> bool:
    day = date.fromisoformat(m["target_day"])
    return today > day or (today == day and hour >= LAST_CALL_HOUR)


async def _expire(ctx: Ctx) -> engine.Outcome:
    today, hour = await asyncio.to_thread(_local, ctx.user_id)
    if expired(ctx.mission, today, hour):
        return stop("expired", "No answer in time, so I let this one go.")
    return wait()


async def _approve(ctx: Ctx) -> engine.Outcome:
    m = ctx.mission
    today, hour = await asyncio.to_thread(_local, ctx.user_id)
    if expired(m, today, hour):
        return stop("expired", "Too late for this one.")
    tr = await asyncio.to_thread(db.trust, ctx.user_id, scope(m["business_id"]))
    if tr["auto"]:
        await asyncio.to_thread(apply_offer, m)
        await tell(ctx.user_id, f"*{ctx.data['business_name']}*: {ctx.data['weekday']} looks slow, so I've gone ahead "
                                f"with *{ctx.data['idea']['title']}* (you said I needn't ask).\n\n" + kit(m)
                                + f"\n\nChanged your mind? Undo it here: {_app(page(m))}",
                   url=page(m), tag=f"mission-{m['id']}")
        return done("Went ahead on its own: you said I needn't ask.", approved=True, auto=True)
    body, buttons = question(m)
    channels = await tell(ctx.user_id, body, url=page(m), tag=f"mission-{m['id']}", buttons=buttons)
    return ask("Waiting for your go-ahead.", asked_on=channels)


async def _check_in(ctx: Ctx) -> engine.Outcome:
    m = ctx.mission
    day = date.fromisoformat(m["target_day"])
    today, hour = await asyncio.to_thread(_local, ctx.user_id)
    if today < day or (today == day and hour < get_settings().sales_nudge_hour):
        return wait()
    if _day(m) is not None:
        return skip("You'd already logged the day.")
    if today > day + timedelta(days=GRACE_DAYS):
        return skip("Too late to ask.")
    name = ctx.data["business_name"]
    when = "today" if today == day else f"on {ctx.data['weekday']}"
    await tell(ctx.user_id, f"How did {name} do {when}? Reply with the sales, like \"sold 14,500\", "
                            f"and I'll tell you whether *{ctx.data['idea']['title']}* worked.",
               url="/business", tag=f"mission-{m['id']}-checkin")
    return done("Asked you how it went.")


def _day(m: dict) -> dict | None:
    day = m["target_day"]
    rows = sales_db.days_for(m["business_id"], date.fromisoformat(day))
    return next((d for d in rows if d["day"] == day and not d["partial"]), None)


def judge(actual: float, f: dict) -> dict:
    """The day against the forecast made before the offer. ``worked`` only when
    above the forecast's own range: inside it, the offer may simply be noise."""
    exp = float(f["value"])
    lift = actual - exp
    verdict = "worked" if f.get("high") is not None and actual > f["high"] else "helped" if lift > 0 else "no_effect"
    return {"actual": round(actual), "expected": round(exp), "lift": round(lift),
            "lift_pct": round(lift / exp, 3) if exp else 0.0, "verdict": verdict}


def result_text(data: dict, o: dict) -> str:
    i, name, wd = data["idea"], data["business_name"], data["weekday"]
    if o["verdict"] == "worked":
        msg = (f"🎉 *{i['title']}* worked. {name} sold {_rs(o['actual'])} on {wd}: {_rs(o['lift'])} more than the "
               f"{_rs(o['expected'])} I expected, and above even my best guess. I'll suggest it again.")
    elif o["verdict"] == "helped":
        msg = (f"*{i['title']}* may have helped: {name} sold {_rs(o['actual'])} on {wd}, {_rs(o['lift'])} more than the "
               f"{_rs(o['expected'])} I expected. That's within my usual error, so I'll keep watching.")
    else:
        msg = (f"{name} sold {_rs(o['actual'])} on {wd}, against the {_rs(o['expected'])} I expected, so "
               f"*{i['title']}* didn't move it this time. I'll try something different next time.")
    return msg


async def _measure(ctx: Ctx) -> engine.Outcome:
    m = ctx.mission
    d = await asyncio.to_thread(_day, m)
    if d is None:
        today, _ = await asyncio.to_thread(_local, ctx.user_id)
        if today > date.fromisoformat(m["target_day"]) + timedelta(days=GRACE_DAYS):
            return skip("No sales were logged, so I couldn't tell.")
        return wait()
    if d["closed"]:
        return skip("You were closed that day.")
    o = judge(d["sales"], ctx.data["forecast"])
    await tell(ctx.user_id, result_text(ctx.data, o), url=page(m), tag=f"mission-{m['id']}-result")
    verdict = {"worked": "It worked", "helped": "It may have helped", "no_effect": "No clear effect"}[o["verdict"]]
    sign = "+" if o["lift"] >= 0 else "-"
    return done(f"{verdict}: {_rs(o['actual'])} vs {_rs(o['expected'])} expected ({sign}{_rs(abs(o['lift']))}).",
                outcome=o)


TEMPLATE = engine.register(engine.Template(
    KIND,
    [("spot", "Spotted {weekday} looks slow"), ("prepare", "Make the offer post"), ("approve", "Your go-ahead"),
     ("check_in", "Ask how {weekday} went"), ("measure", "See if it worked")],
    {"spot": _spot, "prepare": _prepare, "approve": _approve, "check_in": _check_in, "measure": _measure,
     "_expire": _expire},
))


# ------------------------------------------------------------ what the owner sees and decides

def kit(m: dict) -> str:
    data, parts = m["data"], []
    if data.get("post_id") and data.get("brand_id"):
        link = _app(f"/brands/{data['brand_id']}?tab=posts&post={data['post_id']}")
        parts.append(f"1. Post this in the morning (Instagram, WhatsApp status): {link}")
    parts.append(f"{len(parts) + 1}. Forward this to your regulars:\n\n{data.get('share_text', '')}")
    return "\n".join(parts)


def question(m: dict) -> tuple[str, list[tuple[str, str]]]:
    """The go-ahead message and its buttons (WhatsApp ids ``mis:<verb>:<id>``)."""
    d = m["data"]
    f, i = d["forecast"], d["idea"]
    lines = [f"*{d['business_name']}*: {d['weekday']} looks slow, about {_rs(f['value'])}"
             + (f" (a usual {d['weekday']} is {_rs(f['typical'])})" if f.get("typical") else "") + "."]
    lines.append(f"\nIdea: *{i['title']}*. {i.get('idea', '')}")
    if i.get("margin_note"):
        lines.append(i["margin_note"])
    if i.get("track_note"):
        lines.append(i["track_note"])
    if d.get("post_id"):
        lines.append(f"The post is ready: {_app(page(m))}")
    lines.append("\nShall I go ahead?")
    return "\n".join(lines), [(f"mis:ok:{m['id']}", "Go ahead"), (f"mis:no:{m['id']}", "Not this time")]


def apply_offer(m: dict) -> None:
    """Going ahead: the idea counts as used and the day as an offer day (the forecast learns from it)."""
    day, bid, idea = date.fromisoformat(m["target_day"]), m["business_id"], m["data"]["idea"]
    if not any(e["detail"].get("key") == idea["key"] for e in sales_db.events(bid, "idea_used", day) if e["day"] == m["target_day"]):
        sales_db.add_event(bid, day, "idea_used", {"key": idea["key"], "title": idea["title"], "mission": m["id"]})
        if idea.get("discount"):
            sales_db.add_event(bid, day, "offer", {"key": idea["key"], "discount": idea["discount"], "mission": m["id"]})


class AlreadyDecided(Exception):
    pass


async def decide(user_id: str, mission_id: int, approve: bool) -> tuple[dict, str]:
    """The owner's go-ahead (or not). Returns the mission and what to tell them.
    Raises LookupError (not theirs / missing) or AlreadyDecided."""
    m = await asyncio.to_thread(db.get, user_id, mission_id)
    if m is None or m["kind"] != KIND:
        raise LookupError("mission")
    if m["status"] != "waiting":
        raise AlreadyDecided(m["status"])
    sc = scope(m["business_id"])
    if not approve:
        steps = engine.finish_waiting_step(m, "You said not this time.", state="skipped")
        for s in steps:
            if s["state"] == "todo":
                s["state"] = "skipped"
        saved = await asyncio.to_thread(db.save, m["id"], status="cancelled", steps=steps,
                                        data={"approved": False}, expect="waiting")
        if saved is None:
            raise AlreadyDecided("decided")
        await asyncio.to_thread(db.set_trust, user_id, sc, streak=0)
        return saved, "Okay, not this time. I'll keep an eye on the next slow day."
    saved = await asyncio.to_thread(db.save, m["id"], status="active",
                                    steps=engine.finish_waiting_step(m, "You said go ahead."),
                                    data={"approved": True}, expect="waiting")
    if saved is None:
        raise AlreadyDecided("decided")
    await asyncio.to_thread(apply_offer, saved)
    tr = await asyncio.to_thread(db.set_trust, user_id, sc, streak_add=1)
    reply = f"Done. For {saved['data']['weekday']}:\n" + kit(saved) + f"\n\nI'll check in on {saved['data']['weekday']} evening."
    if tr["streak"] >= TRUST_AFTER and not tr["auto"] and not tr["offered"]:
        await asyncio.to_thread(db.set_trust, user_id, sc, offered=True)
        saved = await asyncio.to_thread(db.save, saved["id"], data={"trust_offer": True}) or saved
    saved = await engine.advance(user_id, saved)
    return saved, reply


def trust_question(m: dict) -> tuple[str, list[tuple[str, str]]]:
    d = m["data"]
    return ((f"You've said yes to my last {TRUST_AFTER} slow-day offers for {d['business_name']}. "
             "Want me to go ahead on my own next time? I'll still tell you each time, and you can undo it."),
            [(f"mis:auto:{m['id']}", "Yes, go ahead"), (f"mis:keep:{m['id']}", "Keep asking")])


async def set_auto(user_id: str, business_id: int, auto: bool) -> dict:
    return await asyncio.to_thread(db.set_trust, user_id, scope(business_id), auto=auto, offered=True)


async def undo(user_id: str, mission_id: int) -> dict:
    """Take back a go-ahead before the day is over: the offer is removed, and if
    Hangul acted on its own, it goes back to asking first."""
    m = await asyncio.to_thread(db.get, user_id, mission_id)
    if m is None or m["kind"] != KIND:
        raise LookupError("mission")
    today, _ = await asyncio.to_thread(_local, user_id)
    if not m["data"].get("approved") or m["status"] not in db.OPEN or today > date.fromisoformat(m["target_day"]):
        raise AlreadyDecided(m["status"])
    day, bid, key = date.fromisoformat(m["target_day"]), m["business_id"], m["data"]["idea"]["key"]
    for kind in ("idea_used", "offer"):
        await asyncio.to_thread(sales_db.remove_events, bid, day, kind, key)
    steps = [dict(s) for s in m["steps"]]
    for s in steps:
        if s["key"] == "approve":
            s.update(state="skipped", note="You undid this.")
        elif s["state"] in ("todo", "waiting"):
            s["state"] = "skipped"
    if m["data"].get("auto"):
        await asyncio.to_thread(db.set_trust, user_id, scope(bid), auto=False, streak=0)
    saved = await asyncio.to_thread(db.save, m["id"], status="cancelled", steps=steps, data={"undone": True})
    return saved or m


async def on_button(user_id: str, payload: str) -> tuple[str, list[tuple[str, str]] | None]:
    """A WhatsApp button ``<verb>:<id>``: what to reply, and any follow-up buttons."""
    verb, _, sid = payload.partition(":")
    if not sid.isdigit():
        return "I didn't catch that.", None
    mid = int(sid)
    try:
        if verb in ("ok", "no"):
            m, reply = await decide(user_id, mid, verb == "ok")
            if verb == "ok" and m["data"].get("trust_offer") and not m["data"].get("trust_answered"):
                body, buttons = trust_question(m)
                return reply + "\n\n" + body, buttons
            return reply, None
        if verb in ("auto", "keep"):
            m = await asyncio.to_thread(db.get, user_id, mid)
            if m is None:
                raise LookupError("mission")
            await set_auto(user_id, m["business_id"], verb == "auto")
            await asyncio.to_thread(db.save, mid, data={"trust_answered": True})
            if verb == "auto":
                return (f"Okay. On slow days for {m['data']['business_name']} I'll go ahead and tell you after. "
                        f"You can turn this off any time: {_app('/missions')}"), None
            return "Okay, I'll keep asking first.", None
    except LookupError:
        return "I couldn't find that one.", None
    except AlreadyDecided as e:
        return ("That one has expired." if str(e) == "expired" else "That was already decided."), None
    log.info("unknown mission button", payload=payload[:40])
    return "I didn't catch that.", None
