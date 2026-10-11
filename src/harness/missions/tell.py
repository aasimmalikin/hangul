"""How a mission reaches the owner: their devices (push, every plan) and
WhatsApp (Plus and up, like missions themselves). Buttons go out only
inside Meta's 24-hour window; outside it the brief template asks the owner to
reply, and ``send_waiting`` adds the buttons when they do. The /missions page
always has the same choices, so nothing depends on WhatsApp."""

import asyncio

from harness.logging import log


async def tell(user_id: str, text: str, *, url: str, tag: str,
               buttons: list[tuple[str, str]] | None = None, title: str = "Hangul") -> list[str]:
    """Send ``text`` (and optional reply buttons ``(id, label)``). Returns the channels used."""
    from harness import push
    used = []
    try:
        if await push.send(user_id, title, text, url=url, tag=tag):
            used.append("push")
    except Exception as e:  # noqa: BLE001
        log.warning("mission push failed", error=str(e)[:200])
    if await _whatsapp(user_id, text, buttons, title):
        used.append("whatsapp")
    return used


async def _whatsapp(user_id: str, text: str, buttons, title: str) -> bool:
    from harness.db import whatsapp as wa_db
    from harness.whatsapp import client, enabled
    from harness.whatsapp import service as wa
    if not enabled():
        return False
    try:
        link = await asyncio.to_thread(wa_db.by_user, user_id)
        if link is None or not link.linked or not link.phone or not await asyncio.to_thread(wa._chat_allowed, user_id):
            return False
        if link.window_open():
            if buttons:
                await client.send_buttons(link.phone, text, buttons[:3])
                await wa._charge(user_id, 1)
            else:
                await wa.say(link.phone, text, user_id, markdown=False)
            return True
        # outside the window: the template, and the message waits for their reply
        return await wa.notify(user_id, "task", text, title=title)
    except Exception as e:  # noqa: BLE001 - push and the page still have it
        log.warning("mission whatsapp failed", user_id=user_id, error=str(e)[:200])
        return False


async def send_waiting(phone: str, user_id: str, limit: int = 2) -> int:
    """Buttons for missions still waiting on this owner (their notice went out as
    a template, which can't carry buttons). Called when the owner next writes."""
    from harness.db import missions as db
    from harness.missions import slow_day
    from harness.whatsapp import client
    from harness.whatsapp import service as wa
    sent = 0
    for m in await asyncio.to_thread(db.list_for, user_id, limit=10):
        if m["status"] != "waiting" or sent >= limit:
            continue
        body, buttons = slow_day.question(m)
        await client.send_buttons(phone, body, buttons)
        await wa._charge(user_id, 1)
        sent += 1
    return sent
