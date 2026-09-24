"""Runs scheduled tasks: every POLL_S, pick tasks whose next_run_at has
passed and run each through the same path as /ask (per-user tools,
connectors, security, cost ledger, episode in the Chats rail)."""

import asyncio
import contextlib

from harness.logging import log

POLL_S = 60


async def run_task(task, *, tz: str) -> None:
    from harness.api.concurrency import run_slot
    from harness.api.routes.ask import AskRequest, _build_and_run
    from harness.db import tasks as tasks_db
    from harness.db.episodes import store_episode

    user_id = str(task.user_id)
    tasks_db.mark_started(task.id, tz)
    try:
        req = AskRequest(question=task.question, connectors=list(task.connectors), mode=task.mode)
        async with run_slot(user_id):
            outcome = await _build_and_run(req, user_id)
        r = outcome.result
        status = "needs_approval" if r.pending_tool else "done"
        tasks_db.mark_finished(task.id, status=status, run_id=outcome.run.run_id, answer=r.answer)
        with contextlib.suppress(Exception):
            # the result shows up in the Chats rail like any conversation
            await store_episode(user_id, outcome.run.run_id, r.answer[:1500], title=f"⏰ {task.title}")
        log.info("scheduled task ran", task=task.id, user_id=user_id, status=status)
    except Exception as e:  # noqa: BLE001 - one bad task must not stop the scheduler
        tasks_db.mark_finished(task.id, status="failed", run_id=None, answer=f"{type(e).__name__}: {e}")
        log.warning("scheduled task failed", task=task.id, error=str(e))


async def tick() -> int:
    from harness.db import tasks as tasks_db
    from harness.db.settings import get_settings as user_settings

    due = await asyncio.to_thread(tasks_db.due_tasks)
    for task in due:
        tz = (await asyncio.to_thread(user_settings, str(task.user_id))).timezone
        await run_task(task, tz=tz)
    return len(due)


async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as e:  # noqa: BLE001
            log.warning("scheduler tick failed", error=str(e))
        await asyncio.sleep(POLL_S)


def start() -> asyncio.Task:
    return asyncio.create_task(loop(), name="scheduler")
