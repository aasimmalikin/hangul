"""The user's conversations: list, open, rename, hide.

This is what the Chats rail reads and what makes a chat resumable. It replaces
`/episodes` as the conversation record -- `episodes` keeps only its real job,
the embedding behind `recall_episodes`.

`GET /conversations/{id}` returns the transcript the UI needs to rehydrate a
chat: user and assistant text plus the tool calls, in order. Tool *results* are
summarised to a preview rather than sent whole -- the browser needs to draw a
card, not re-read a 200KB file.

Everything is scoped to the caller: a conversation belonging to someone else is
404, indistinguishable from one that does not exist.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.db.conversations import (
    create_conversation,
    deactivate_conversation,
    get_conversation,
    list_conversations,
    load_messages,
    message_counts,
    rename_conversation,
)

router = APIRouter()

# How much of a stored tool result the UI is given per card.
TOOL_PREVIEW_CHARS = 400


class ConversationItem(BaseModel):
    id: str
    title: str
    preview: str
    model: str | None = None
    effort: str | None = None
    connectors: list[str] = []
    mode: str = "default"
    docs_only: bool = False
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class TranscriptMessage(BaseModel):
    seq: int
    role: str                       # user | assistant | tool
    content: str
    tool_calls: list[dict] = []     # assistant turns that called tools
    tool_call_id: str | None = None  # which call a tool message answers
    # GoogleCards-style payload, if the transcript has one. Not populated yet:
    # the loop sends `ui` on the tool_result event but does not put it in the
    # message list (the list goes to OpenAI verbatim, and an unknown key there
    # risks a 400), so a restored Workspace result renders as text. Persisting
    # it needs a separate channel on the checkpoint.
    ui: dict | None = None


class ConversationDetail(ConversationItem):
    messages: list[TranscriptMessage] = []


class ConversationIn(BaseModel):
    title: str = Field(default = "", max_length = 200)
    model: str | None = Field(default = None, max_length = 64)
    effort: str | None = Field(default = None, max_length = 16)
    connectors: list[str] = Field(default_factory = list, max_length = 8)
    mode: str = Field(default = "default", max_length = 16)
    docs_only: bool = False


class ConversationPatch(BaseModel):
    title: str = Field(min_length = 1, max_length = 200)


def _item(row, count: int = 0) -> ConversationItem:
    return ConversationItem(
        id = row.id, title = row.title, preview = row.summary_text[:200],
        model = row.model, effort = row.effort, connectors = list(row.connectors or []),
        mode = row.mode, docs_only = row.docs_only, message_count = count,
        created_at = row.created_at, updated_at = row.updated_at,
    )


@router.get("/conversations", response_model = list[ConversationItem])
async def get_conversations(user: dict = Depends(get_current_user)) -> list[ConversationItem]:
    """The caller's conversations, most recently touched first."""
    rows = await asyncio.to_thread(list_conversations, user["user_id"])
    counts = await asyncio.to_thread(message_counts, [r.id for r in rows])
    return [_item(r, counts.get(r.id, 0)) for r in rows]


@router.post("/conversations", status_code = status.HTTP_201_CREATED)
async def post_conversation(body: ConversationIn,
                            user: dict = Depends(get_current_user)) -> dict:
    """Start an empty conversation. /ask also creates one implicitly when it is
    given no conversation_id, so this is only for "New chat" up front."""
    conv_id = await asyncio.to_thread(
        create_conversation, user["user_id"], title = body.title, model = body.model,
        effort = body.effort, connectors = body.connectors, mode = body.mode,
        docs_only = body.docs_only,
    )
    return {"id": conv_id}


@router.get("/conversations/{conversation_id}", response_model = ConversationDetail)
async def get_one(conversation_id: str,
                  user: dict = Depends(get_current_user)) -> ConversationDetail:
    """One conversation with its transcript, for rehydrating the chat page."""
    conv = await asyncio.to_thread(get_conversation, conversation_id, user["user_id"])
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    rows = await asyncio.to_thread(load_messages, conversation_id)
    messages = []
    for r in rows:
        extra = r.extra or {}
        content = r.content
        if r.role == "tool" and len(content) > TOOL_PREVIEW_CHARS:
            # the card needs a preview, not the whole payload
            content = content[:TOOL_PREVIEW_CHARS] + "…"
        messages.append(TranscriptMessage(
            seq = r.seq, role = r.role, content = content,
            tool_calls = extra.get("tool_calls") or [],
            tool_call_id = extra.get("tool_call_id"),
            ui = extra.get("ui"),
        ))
    base = _item(conv, len(rows))
    return ConversationDetail(**base.model_dump(), messages = messages)


@router.patch("/conversations/{conversation_id}")
async def patch_conversation(conversation_id: str, body: ConversationPatch,
                             user: dict = Depends(get_current_user)) -> dict:
    """Rename. 404 if unknown, hidden, or not the caller's."""
    ok = await asyncio.to_thread(rename_conversation, conversation_id,
                                 user["user_id"], body.title)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return {"id": conversation_id, "title": body.title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str,
                              user: dict = Depends(get_current_user)) -> dict:
    """Hide a conversation. The transcript stays for audit, as with episodes."""
    ok = await asyncio.to_thread(deactivate_conversation, conversation_id, user["user_id"])
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return {"deleted": conversation_id}
