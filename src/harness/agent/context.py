"""Building a run's message list from a server-owned conversation.

The loop used to be seeded with the system prompt, whatever ``history`` the
browser uploaded, and the new question. That history was user/assistant text
only, so every tool result from an earlier turn was lost. Here the seed comes
from ``conversation_messages`` instead, which keeps all three roles -- so a
follow-up can refer to a file the agent read two turns ago.

A transcript grows without bound and a context window does not, so the window
is budgeted: recent messages verbatim, everything older folded once into a
rolling summary on the conversation row.

THE TRAP: an assistant message carrying ``tool_calls`` and its ``tool`` replies
are one indivisible unit. OpenAI rejects the whole request when a ``tool``
message has no preceding call, or a call has no reply. So the window boundary
is never "the last N messages" -- it is snapped back to a ``user`` message,
which is the only role that is always a safe cut point.

This module does the assembly; the loop stays unaware of the database.
"""

from harness.db.models import ConversationMessage
from harness.logging import log

# Fraction of the token budget the replayed transcript may occupy. The rest is
# for the system prompt, the new question, and everything this run will add.
HISTORY_SHARE = 0.60

# A replayed tool result is context, not the artefact: the full text is still in
# conversation_messages (and in the run's retrieved_context). Capping it stops
# one 200KB file read from evicting a whole conversation.
MAX_REPLAYED_TOOL_CHARS = 2_000

SUMMARY_HEADER = "=== EARLIER IN THIS CONVERSATION ==="

_SUMMARY_PROMPT = (
    "Summarise the earlier part of this conversation between a user and an "
    "assistant, for the assistant's own future reference. Keep: what the user "
    "asked for, decisions and conclusions reached, facts discovered from tools "
    "(file contents, search results, figures), and anything still outstanding. "
    "Drop pleasantries and narration. Write compact prose under 400 words, in "
    "the third person. If a previous summary is given, fold it in rather than "
    "repeating it."
)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate. See db.conversations._estimate_tokens on
    why this is not tiktoken."""
    return max(1, len(text or "") // 4)


def to_wire(row: ConversationMessage) -> dict:
    """One stored row as an OpenAI message."""
    msg: dict = {"role": row.role, "content": row.content}
    extra = row.extra or {}
    if row.role == "assistant" and extra.get("tool_calls"):
        msg["tool_calls"] = extra["tool_calls"]
    if row.role == "tool":
        if extra.get("tool_call_id"):
            msg["tool_call_id"] = extra["tool_call_id"]
        # a replayed result is reference, not the artefact
        if len(msg["content"]) > MAX_REPLAYED_TOOL_CHARS:
            msg["content"] = (msg["content"][:MAX_REPLAYED_TOOL_CHARS]
                              + "\n[... truncated; ask again to re-read in full]")
    return msg


def pick_window(history: list[ConversationMessage], token_budget: int) -> int:
    """Index into ``history`` where the verbatim window starts.

    Walks backwards accumulating tokens, then snaps forward to the next ``user``
    message so the window never begins mid tool-call group. Returns 0 when
    everything fits.
    """
    if not history:
        return 0

    used = 0
    start = 0
    for i in range(len(history) - 1, -1, -1):
        cost = estimate_tokens(to_wire(history[i])["content"])
        if used + cost > token_budget and i < len(history) - 1:
            start = i + 1
            break
        used += cost
    else:
        return 0

    # Snap forward to a user message: an assistant/tool message could be the
    # tail of a tool-call group whose opening call is now below the cut.
    while start < len(history) and history[start].role != "user":
        start += 1
    # No user message in the remainder (a conversation that ends mid-tool-run):
    # keep the last user message and everything after it, budget or not -- an
    # over-budget request the provider truncates beats an invalid one it refuses.
    if start >= len(history):
        last_user = max((i for i, m in enumerate(history) if m.role == "user"), default=0)
        return last_user
    return start


def build_messages(
    *,
    prompt_text: str,
    question: str,
    summary: str,
    history: list[ConversationMessage],
    token_budget: int,
) -> tuple[list[dict], list[ConversationMessage]]:
    """The seed message list for a fresh run over an existing conversation.

    Returns the messages and the rows that fell outside the window, which the
    caller folds into the conversation's rolling summary.
    """
    share = max(1, int(token_budget * HISTORY_SHARE))
    start = pick_window(history, share)
    dropped = history[:start]
    kept = history[start:]

    messages: list[dict] = [{"role": "system", "content": prompt_text}]
    if summary:
        messages.append({"role": "system", "content": f"{SUMMARY_HEADER}\n{summary}"})
    messages.extend(to_wire(m) for m in kept)
    messages.append({"role": "user", "content": question})
    return messages, dropped


def validate(messages: list[dict]) -> str | None:
    """Why this list would be rejected, or None. Cheap insurance against the
    trap above; called before the first provider turn so a bug here surfaces as
    a log line and a wider window rather than a 400 mid-conversation."""
    open_calls: set[str] = set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                open_calls.add(tc.get("id"))
        elif m.get("role") == "tool":
            cid = m.get("tool_call_id")
            if cid not in open_calls:
                return f"tool message replies to unknown call {cid!r}"
            open_calls.discard(cid)
    if open_calls:
        return f"tool calls with no reply: {sorted(open_calls)}"
    return None


async def compact(*, prior_summary: str, dropped: list[ConversationMessage]) -> str:
    """Fold the messages leaving the window into one summary.

    Uses the configured default model rather than the run's: this is
    bookkeeping, and a reasoning model with a high effort would cost more than
    the turn it is making room for. A failure returns the previous summary --
    losing the older context is bad, failing the user's question is worse.
    """
    from harness.providers import get_provider

    lines: list[str] = []
    for m in dropped:
        if m.role == "tool":
            lines.append(f"[tool result] {m.content[:600]}")
        else:
            lines.append(f"{m.role}: {m.content[:1200]}")
    body = "\n".join(lines)
    if prior_summary:
        body = f"Previous summary:\n{prior_summary}\n\nNewly dropped:\n{body}"

    try:
        turn = await get_provider().chat(
            [{"role": "system", "content": _SUMMARY_PROMPT},
             {"role": "user", "content": body}],
            [],
        )
        text = (turn.text or "").strip()
        return text or prior_summary
    except Exception as e:  # noqa: BLE001
        log.warning("conversation compaction failed", error=str(e), dropped=len(dropped))
        return prior_summary
