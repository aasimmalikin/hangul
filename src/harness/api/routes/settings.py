"""Personalisation (GET/PUT /settings) and scheduled tasks (/tasks)."""

import asyncio
from datetime import datetime

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


@router.get("/settings")
async def read_settings(user: dict = Depends(get_current_user)) -> dict:
    return {**(await asyncio.to_thread(get_settings, user["user_id"])).as_dict(), "tones": list(TONES)}


@router.put("/settings")
async def write_settings(req: SettingsIn, user: dict = Depends(get_current_user)) -> dict:
    try:
        saved = await asyncio.to_thread(save_settings, user["user_id"], Settings(**req.model_dump()))
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return saved.as_dict()


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=4000)
    every_minutes: int | None = Field(default=None, ge=15, le=7 * 24 * 60)
    daily_at: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    connectors: list[str] = Field(default_factory=list, max_length=8)
    mode: str = Field(default="default", pattern=r"^(default|research)$")


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


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(user: dict = Depends(get_current_user)) -> list[TaskOut]:
    return [TaskOut(**t.public()) for t in await asyncio.to_thread(tasks_db.list_tasks, user["user_id"])]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(req: TaskIn, user: dict = Depends(get_current_user)) -> TaskOut:
    try:
        validate_keys(req.connectors)
        tz = (await asyncio.to_thread(get_settings, user["user_id"])).timezone
        t = await asyncio.to_thread(tasks_db.create_task, user["user_id"], title=req.title, question=req.question,
                                    every_minutes=req.every_minutes, daily_at=req.daily_at,
                                    connectors=req.connectors, mode=req.mode, tz=tz)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return TaskOut(**t.public())


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(tasks_db.delete_task, user["user_id"], task_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return {"deleted": task_id}


@router.post("/tasks/{task_id}/enabled", response_model=TaskOut)
async def set_task_enabled(task_id: int, enabled: bool, user: dict = Depends(get_current_user)) -> TaskOut:
    tz = (await asyncio.to_thread(get_settings, user["user_id"])).timezone
    t = await asyncio.to_thread(tasks_db.set_enabled, user["user_id"], task_id, enabled, tz)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return TaskOut(**t.public())


@router.post("/tasks/{task_id}/run", response_model=TaskOut)
async def run_task_now(task_id: int, user: dict = Depends(get_current_user)) -> TaskOut:
    """Run immediately (in the request; costs a model run)."""
    t = await asyncio.to_thread(tasks_db.get_task, user["user_id"], task_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    tz = (await asyncio.to_thread(get_settings, user["user_id"])).timezone
    await run_task(t, tz=tz)
    return TaskOut(**(await asyncio.to_thread(tasks_db.get_task, user["user_id"], task_id)).public())
