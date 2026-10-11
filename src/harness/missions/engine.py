"""The mission engine: one loop shared by every template.

``advance`` runs the first unfinished step, and keeps going while steps finish
in the same tick. A step returns an ``Outcome``:

  done   finished (with a short note shown on the checklist)
  skip   not needed this time
  wait   not yet: try again next tick (time has to pass, or numbers arrive)
  ask    waiting for the owner: the mission is ``waiting`` until they decide
  stop   the mission ends here with ``status`` (expired, cancelled, done)

Steps are idempotent per mission: a step is only re-run while it hasn't
finished, and anything it sends is guarded by the stored state, so a tick that
dies half-way never sends twice once the step is saved.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from harness.db import missions as db
from harness.logging import log


@dataclass
class Outcome:
    state: str                       # done | skip | wait | ask | stop
    note: str = ""
    data: dict = field(default_factory=dict)
    status: str = ""                 # for stop


def done(note: str = "", **data) -> Outcome:
    return Outcome("done", note, data)


def skip(note: str = "", **data) -> Outcome:
    return Outcome("skip", note, data)


def wait(**data) -> Outcome:
    return Outcome("wait", "", data)


def ask(note: str = "", **data) -> Outcome:
    return Outcome("ask", note, data)


def stop(status: str, note: str = "", **data) -> Outcome:
    return Outcome("stop", note, data, status)


@dataclass
class Ctx:
    user_id: str
    mission: dict

    @property
    def data(self) -> dict:
        return self.mission["data"]


StepFn = Callable[[Ctx], Awaitable[Outcome]]


@dataclass
class Template:
    kind: str
    steps: list[tuple[str, str]]               # (key, label); a label may use {fields} from data
    run: dict[str, StepFn]

    def fresh_steps(self, data: dict) -> list[dict]:
        return [{"key": k, "label": label.format_map(_Blank(data)), "state": "todo", "note": "", "at": None}
                for k, label in self.steps]


class _Blank(dict):
    def __missing__(self, key):
        return ""


TEMPLATES: dict[str, Template] = {}


def load() -> dict[str, Template]:
    """Every template, registered by importing its module."""
    from harness.missions import report, slow_day  # noqa: F401 - registers
    return TEMPLATES


def register(t: Template) -> Template:
    TEMPLATES[t.kind] = t
    return t


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def advance(user_id: str, mission: dict) -> dict:
    """Move one mission as far as it can go right now."""
    t = load().get(mission["kind"])
    if t is None or mission["status"] not in db.OPEN:
        return mission
    steps = [dict(s) for s in mission["steps"]]
    progressed = False
    for i, s in enumerate(steps):
        if s["state"] in ("done", "skipped", "failed"):
            continue
        fn = t.run.get(s["key"])
        if fn is None:
            s.update(state="skipped", at=_now())
            continue
        try:
            out = await fn(Ctx(user_id, mission))
        except Exception as e:  # noqa: BLE001 - one broken step must not stall the scheduler
            log.warning("mission step failed", mission=mission["id"], step=s["key"], error=f"{type(e).__name__}: {e}"[:300])
            s.update(state="failed", note="Something went wrong here; I've stopped this one.", at=_now())
            for rest in steps[i + 1:]:
                rest["state"] = "skipped"
            return await asyncio.to_thread(db.save, mission["id"], status="done", steps=steps,
                                           data={**mission["data"], "failed_step": s["key"]}) or mission
        mission["data"] = {**mission["data"], **out.data}
        if out.state in ("done", "skip"):
            s.update(state="done" if out.state == "done" else "skipped", note=out.note or s["note"], at=_now())
            progressed = True
            continue
        if out.state == "wait":
            if progressed or out.data:     # steps finished earlier in this pass, or new data
                mission = await asyncio.to_thread(db.save, mission["id"], steps=steps, data=mission["data"]) or mission
            return mission
        if out.state == "ask":
            s.update(state="waiting", note=out.note or s["note"], at=s["at"] or _now())
            return await asyncio.to_thread(db.save, mission["id"], status="waiting", steps=steps, data=mission["data"]) or mission
        # stop
        s.update(state="done" if out.status == "done" else "skipped", note=out.note, at=_now())
        for rest in steps[i + 1:]:
            if rest["state"] == "todo":
                rest["state"] = "skipped"
        return await asyncio.to_thread(db.save, mission["id"], status=out.status, steps=steps, data=mission["data"]) or mission
    return await asyncio.to_thread(db.save, mission["id"], status="done", steps=steps, data=mission["data"]) or mission


async def begin(user_id: str, kind: str, target_day, data: dict, *, business_id: int = 0) -> dict | None:
    """Start a mission (None when that job already exists) and run it as far as it goes."""
    t = TEMPLATES[kind]
    m = await asyncio.to_thread(db.start, user_id, kind, target_day, t.fresh_steps(data),
                                business_id=business_id, data=data)
    if m is None:
        return None
    return await advance(user_id, m)


def finish_waiting_step(mission: dict, note: str, *, state: str = "done") -> list[dict]:
    """The steps with the step waiting for the owner marked decided."""
    steps = [dict(s) for s in mission["steps"]]
    for s in steps:
        if s["state"] == "waiting":
            s.update(state=state, note=note, at=_now())
            break
    return steps


async def tick() -> int:
    """Every open mission, one step further where it can go. Returns how many changed."""
    changed = 0
    load()
    for user_id, m in await asyncio.to_thread(db.open_missions):
        t = TEMPLATES.get(m["kind"])
        if t is None:
            continue
        try:
            before = (m["status"], [s["state"] for s in m["steps"]])
            if m["status"] == "waiting":
                # still waiting for the owner; only the template's expiry check runs
                check = t.run.get("_expire")
                if check:
                    out = await check(Ctx(user_id, m))
                    if out.state == "stop":
                        steps = finish_waiting_step(m, out.note, state="skipped")
                        for s in steps:
                            if s["state"] == "todo":
                                s["state"] = "skipped"
                        await asyncio.to_thread(db.save, m["id"], status=out.status, steps=steps, data=out.data,
                                                expect="waiting")
                        changed += 1
                continue
            after = await advance(user_id, m)
            if (after["status"], [s["state"] for s in after["steps"]]) != before:
                changed += 1
        except Exception as e:  # noqa: BLE001 - one mission must not stop the others
            log.warning("mission tick failed", mission=m["id"], error=f"{type(e).__name__}: {e}"[:300])
    return changed
