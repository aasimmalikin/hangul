"""Personalisation (GET/PUT /settings) and scheduled tasks (/tasks)."""

import asyncio
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.connectors import validate_keys
from harness.db import tasks as tasks_db
from harness.db.settings import TONES, Settings, get_settings, save_settings
from harness.scheduler import run_task

router = APIRouter()


class SettingsIn(BaseModel):
    display_name: str = Field(default="", max_length=80)
    instructions: str = Field(default="", max_length=2000)
    tone: str = Field(default="balanced", max_length=16)
    timezone: str = Field(default="UTC", max_length=64)
    language: str = Field(default="", max_length=16)
    timezone_auto: bool = True
    city: str = Field(default="", max_length=80)
    onboarded: bool = False
    # None = not sent: keep the stored one (older screens PUT settings without it)
    home_address: str | None = Field(default=None, max_length=200)
    persona: str | None = Field(default=None, max_length=16)     # None = keep the stored one


class DeviceTimezone(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)


@router.post("/settings/timezone")
async def device_timezone(req: DeviceTimezone, user: dict = Depends(get_current_user)) -> dict:
    """The web app reports the device's timezone on every page load; it is
    stored only while the user's timezone is automatic (see adopt_device_timezone)."""
    from harness.db.settings import adopt_device_timezone
    st = await asyncio.to_thread(adopt_device_timezone, user["user_id"], req.timezone)
    return {"timezone": st.timezone, "timezone_auto": st.timezone_auto}


@router.post("/settings/onboarded")
async def onboarded(user: dict = Depends(get_current_user)) -> dict:
    from harness.db.settings import mark_onboarded
    await asyncio.to_thread(mark_onboarded, user["user_id"])
    return {"onboarded": True}


@router.get("/settings")
async def read_settings(user: dict = Depends(get_current_user)) -> dict:
    return {**(await asyncio.to_thread(get_settings, user["user_id"])).as_dict(), "tones": list(TONES)}


@router.put("/settings")
async def write_settings(req: SettingsIn, user: dict = Depends(get_current_user)) -> dict:
    try:
        values = req.model_dump()
        if values["home_address"] is None or values["persona"] is None:
            current = await asyncio.to_thread(get_settings, user["user_id"])
            for field in ("home_address", "persona"):
                if values[field] is None:
                    values[field] = getattr(current, field)
        saved = await asyncio.to_thread(save_settings, user["user_id"], Settings(**values))
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return saved.as_dict()


class TaskIn(BaseModel):
    # optional: a short title is made from the question when it's left blank
    title: str = Field(default="", max_length=120)
    question: str = Field(min_length=1, max_length=4000)
    every_minutes: int | None = Field(default=None, ge=15, le=7 * 24 * 60)
    daily_at: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    # with daily_at: only on these weekdays (bit 0 = Monday … bit 6 = Sunday), or once on this date
    days: int | None = Field(default=None, ge=1, le=tasks_db.ALL_DAYS)
    run_on: date | None = None
    connectors: list[str] = Field(default_factory=list, max_length=8)
    mode: str = Field(default="default", pattern=r"^(default|research)$")
    deliver_email: bool = False
    # when the plan doesn't allow this often (Free: weekly), make it as frequent as the
    # plan allows instead of refusing -- the one-tap morning brief and onboarding use this
    fit_plan: bool = False


def title_from(question: str) -> str:
    """"remind me what's on tomorrow and email me." -> "Remind me what's on tomorrow"."""
    first = question.strip().splitlines()[0] if question.strip() else "Task"
    first = first.split(". ")[0].rstrip(".!? ")
    words = first.split()
    title = " ".join(words[:7]) + ("…" if len(words) > 7 else "")
    return (title[:1].upper() + title[1:])[:120] or "Task"


def _fit_schedule(user_id: str, req: TaskIn) -> tuple[int | None, str | None, int | None]:
    """The schedule to store (every_minutes, daily_at, days), within the user's plan;
    402 when it doesn't fit."""
    from harness.billing import entitlements
    from harness.billing.plans import get_plan
    from harness.db import billing as billing_db
    if not entitlements.billing_enabled():
        return req.every_minutes, req.daily_at, req.days
    plan = get_plan(billing_db.get_account(user_id).plan)
    if tasks_db.interval_minutes(req.every_minutes, req.daily_at, req.days, req.run_on) >= plan.task_min_minutes:
        return req.every_minutes, req.daily_at, req.days
    if req.fit_plan:
        if req.days:                     # weekdays -> the first of them, once a week
            return None, req.daily_at, req.days & -req.days
        return plan.task_min_minutes, req.daily_at, None
    raise entitlements._deny(
        "plan_required", "Daily and more frequent tasks are part of Plus. On Free a task can run once a week "
        "(or once, on a date you pick).", plan_needed="plus")


class TaskOut(BaseModel):
    id: int
    title: str
    question: str
    every_minutes: int | None
    daily_at: str | None
    connectors: list
    mode: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str
    last_run_id: str | None
    last_answer: str
    created_at: datetime | None
    deliver_email: bool = False
    days: int | None = None
    run_on: date | None = None
    # its apps whose actions wait for an OK: such a task runs LEAD_MINUTES early (harness.preapproval)
    asks_first: list[str] = []


def _out(t) -> "TaskOut":
    from harness.preapproval import asks_first
    return TaskOut(**t.public(), asks_first=asks_first(t.connectors, t.question))


class PreviewIn(BaseModel):
    question: str = Field(default="", max_length=4000)


@router.post("/tasks/preview")
async def preview_task(req: PreviewIn, user: dict = Depends(get_current_user)) -> dict:
    """What the task form shows as you type: the apps the question will switch on (the
    same keyword router a chat uses), which of them will ask first, and a title."""
    from harness.connectors.auto import connected_apps, route
    from harness.preapproval import LEAD_MINUTES, asks_first
    connected = await connected_apps(user["user_id"])
    apps = route(req.question, connected) if req.question.strip() else []
    return {"apps": apps, "connected": connected, "asks_first": asks_first(apps, req.question),
            "lead_minutes": LEAD_MINUTES,
            "title": title_from(req.question) if req.question.strip() else ""}


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(user: dict = Depends(get_current_user)) -> list[TaskOut]:
    return [_out(t) for t in await asyncio.to_thread(tasks_db.list_tasks, user["user_id"])]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(req: TaskIn, user: dict = Depends(get_current_user)) -> TaskOut:
    try:
        validate_keys(req.connectors)
        tz = (await asyncio.to_thread(get_settings, user["user_id"])).timezone
        every_minutes, daily_at, days = await asyncio.to_thread(_fit_schedule, user["user_id"], req)
        # the apps the question needs, as a run would pick them, are saved with the task:
        # they decide whether it runs early to ask first (harness.preapproval)
        from harness.connectors.auto import connected_apps, route
        try:
            routed = route(req.question, await connected_apps(user["user_id"]))
        except Exception:  # noqa: BLE001 - routing is a convenience; the run routes again anyway
            routed = []
        connectors = list(dict.fromkeys([*req.connectors, *routed]))[:8]
        t = await asyncio.to_thread(tasks_db.create_task, user["user_id"],
                                    title=req.title.strip() or title_from(req.question), question=req.question,
                                    every_minutes=every_minutes, daily_at=daily_at, days=days, run_on=req.run_on,
                                    connectors=connectors, mode=req.mode, tz=tz, deliver_email=req.deliver_email)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return _out(t)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(tasks_db.delete_task, user["user_id"], task_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return {"deleted": task_id}


@router.post("/tasks/{task_id}/enabled", response_model=TaskOut)
async def set_task_enabled(task_id: int, enabled: bool, user: dict = Depends(get_current_user)) -> TaskOut:
    tz = (await asyncio.to_thread(get_settings, user["user_id"])).timezone
    try:
        t = await asyncio.to_thread(tasks_db.set_enabled, user["user_id"], task_id, enabled, tz)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return _out(t)


@router.post("/tasks/{task_id}/run", response_model=TaskOut)
async def run_task_now(task_id: int, user: dict = Depends(get_current_user)) -> TaskOut:
    """Run immediately (in the request; costs a model run)."""
    t = await asyncio.to_thread(tasks_db.get_task, user["user_id"], task_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    tz = (await asyncio.to_thread(get_settings, user["user_id"])).timezone
    await run_task(t, tz=tz)
    return _out(await asyncio.to_thread(tasks_db.get_task, user["user_id"], task_id))
