"""The user's chat history ("Chats" rail): list, save, hide.

An episode is one conversation, summarised by the client from its own
transcript (no LLM call -- just the questions and the start of each answer)
and embedded here so `recall_episodes` can find it later. Saving is an
upsert keyed by the conversation id, so a chat continued after the user came
back to the landing page updates its entry instead of adding a second one.

Everything is scoped to the authenticated user; deleting only deactivates.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.db.episodes import deactivate_episode, list_episodes, store_episode

router = APIRouter()


class EpisodeItem(BaseModel):
    id: int
    thread_id: str
    title: str
    preview: str      # one line saying what the chat was about (first answer)
    summary: str      # the Q:/A: transcript, for the "view all" history
    created_at: datetime
    updated_at: datetime


def _preview(summary: str, limit: int = 160) -> str:
    """The first answer, else the first question, on one line."""
    lines = [ln.strip() for ln in summary.splitlines() if ln.strip()]
    pick = next((ln for ln in lines if ln.startswith("A:")), next((ln for ln in lines if ln.startswith("Q:")), ""))
    text = " ".join(pick[2:].split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class EpisodeIn(BaseModel):
    thread_id: str = Field(min_length = 1, max_length = 64)
    title: str = Field(min_length = 1, max_length = 200)
    summary: str = Field(min_length = 1, max_length = 2048)


@router.get("/episodes", response_model = list[EpisodeItem])
async def get_episodes(user: dict = Depends(get_current_user)) -> list[EpisodeItem]:
    """All visible conversations for the current user, most recent first."""
    rows = await asyncio.to_thread(list_episodes, user["user_id"])
    return [
        EpisodeItem(
            id = r.id, thread_id = r.thread_id, title = r.title, preview = _preview(r.summary), summary = r.summary,
            created_at = r.created_at, updated_at = r.updated_at,
        )
        for r in rows
    ]


@router.post("/episodes", status_code = status.HTTP_201_CREATED)
async def put_episode(body: EpisodeIn, user: dict = Depends(get_current_user)) -> dict:
    """Save or refresh one conversation."""
    episode_id = await store_episode(user["user_id"], body.thread_id, body.summary, body.title)
    return {"id": episode_id, "thread_id": body.thread_id}


@router.delete("/episodes/{episode_id}")
async def delete_episode(episode_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Hide one conversation. 404 if unknown, already hidden, or not the caller's."""
    ok = await asyncio.to_thread(deactivate_episode, user["user_id"], episode_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return {"deleted": episode_id}
