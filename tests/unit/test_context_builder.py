"""Building a run's messages from a stored conversation.

The property that matters most: whatever the budget, the result is a message
list OpenAI will accept. An assistant message carrying `tool_calls` and its
`tool` replies are indivisible, so the window boundary can never land inside
one. Everything here runs on fakes -- no DB, no model call.
"""
import asyncio
from types import SimpleNamespace

import pytest

from harness.agent import context as ctx


def _m(seq, role, content, **extra):
    return SimpleNamespace(seq=seq, role=role, content=content, extra=extra or {})


def _tool_turn(seq, call_id, args_text, result):
    """An assistant message with one tool call plus its reply: 2 rows."""
    return [
        _m(seq, "assistant", args_text,
           tool_calls=[{"id": call_id, "type": "function",
                        "function": {"name": "search_docs", "arguments": "{}"}}]),
        _m(seq + 1, "tool", result, tool_call_id=call_id),
    ]


def _conversation(turns: int) -> list:
    """turns × (user, assistant+tool_call, tool, assistant answer)."""
    rows, seq = [], 0
    for t in range(turns):
        rows.append(_m(seq, "user", f"question {t} " + "x" * 200)); seq += 1
        rows += _tool_turn(seq, f"call_{t}", "looking that up", "RESULT " + "y" * 800); seq += 2
        rows.append(_m(seq, "assistant", f"answer {t} " + "z" * 300)); seq += 1
    return rows


def _build(history, budget):
    return ctx.build_messages(prompt_text="SYS", question="new question",
                              summary="", history=history, token_budget=budget)


# ---------------------------------------------------------------- the trap

@pytest.mark.parametrize("budget", [50, 100, 200, 400, 800, 1600, 3200, 6400, 20_000])
def test_window_never_orphans_a_tool_call(budget):
    """At every budget the list is valid: no tool reply without its call, no
    call without its reply. This is the one that would 400 in production."""
    messages, _ = _build(_conversation(6), budget)
    assert ctx.validate(messages) is None, (budget, ctx.validate(messages))


def test_window_starts_on_a_user_message():
    messages, dropped = _build(_conversation(6), 600)
    assert dropped, "a tight budget should drop something"
    # first message after the system prompt is a user turn
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_everything_fits_drops_nothing():
    history = _conversation(2)
    messages, dropped = _build(history, 100_000)
    assert dropped == []
    assert len(messages) == len(history) + 2      # + system + new question


def test_new_question_is_last_and_system_is_first():
    messages, _ = _build(_conversation(3), 2000)
    assert messages[0] == {"role": "system", "content": "SYS"}
    assert messages[-1] == {"role": "user", "content": "new question"}


def test_summary_rides_as_a_second_system_message():
    messages, _ = ctx.build_messages(
        prompt_text="SYS", question="q", summary="they discussed budgets",
        history=_conversation(2), token_budget=100_000)
    assert messages[1]["role"] == "system"
    assert ctx.SUMMARY_HEADER in messages[1]["content"]
    assert "they discussed budgets" in messages[1]["content"]


def test_no_summary_means_no_extra_system_message():
    messages, _ = _build(_conversation(1), 100_000)
    assert sum(1 for m in messages if m["role"] == "system") == 1


# ------------------------------------------------------- replayed tool results

def test_replayed_tool_result_is_truncated():
    big = "A" * (ctx.MAX_REPLAYED_TOOL_CHARS * 3)
    wire = ctx.to_wire(_m(1, "tool", big, tool_call_id="c1"))
    assert len(wire["content"]) < len(big)
    assert "truncated" in wire["content"]
    assert wire["tool_call_id"] == "c1"


def test_assistant_tool_calls_survive_the_round_trip():
    calls = [{"id": "c1", "type": "function",
              "function": {"name": "search_docs", "arguments": '{"query":"x"}'}}]
    wire = ctx.to_wire(_m(1, "assistant", "", tool_calls=calls))
    assert wire["tool_calls"] == calls


def test_user_message_has_no_tool_keys():
    wire = ctx.to_wire(_m(0, "user", "hello"))
    assert wire == {"role": "user", "content": "hello"}


# ------------------------------------------------------------------ validate

def test_validate_catches_an_orphan_tool_reply():
    bad = [{"role": "tool", "tool_call_id": "ghost", "content": "x"}]
    assert "unknown call" in ctx.validate(bad)


def test_validate_catches_a_call_with_no_reply():
    bad = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]}]
    assert "no reply" in ctx.validate(bad)


def test_validate_accepts_a_matched_pair():
    good = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
    ]
    assert ctx.validate(good) is None


# ------------------------------------------------------------------ edge cases

def test_empty_history():
    messages, dropped = _build([], 1000)
    assert dropped == []
    assert messages == [{"role": "system", "content": "SYS"},
                        {"role": "user", "content": "new question"}]


def test_conversation_ending_mid_tool_run_still_valid():
    """A run that paused for approval leaves a trailing tool group. A tiny
    budget must not cut into it."""
    history = [_m(0, "user", "do the thing")] + _tool_turn(1, "c1", "on it", "R" * 5000)
    messages, _ = _build(history, 20)
    assert ctx.validate(messages) is None


def test_single_huge_user_message_is_kept():
    history = [_m(0, "user", "Q" * 40_000)]
    messages, _ = _build(history, 50)
    assert any(m["role"] == "user" and m["content"].startswith("Q") for m in messages)


# ---------------------------------------------------------------- compaction

def test_compaction_failure_keeps_the_previous_summary(monkeypatch):
    """A failed summary must never fail the user's question."""
    class Boom:
        async def chat(self, messages, tools):
            raise RuntimeError("provider down")

    monkeypatch.setattr("harness.providers.get_provider", lambda: Boom())
    out = asyncio.run(ctx.compact(prior_summary="what we had before",
                                  dropped=[_m(0, "user", "hello")]))
    assert out == "what we had before"


def test_compaction_returns_the_model_text(monkeypatch):
    class Fake:
        async def chat(self, messages, tools):
            assert "Previous summary" in messages[1]["content"]
            return SimpleNamespace(text="  they agreed on the schema  ")

    monkeypatch.setattr("harness.providers.get_provider", lambda: Fake())
    out = asyncio.run(ctx.compact(prior_summary="earlier", dropped=[_m(0, "user", "hi")]))
    assert out == "they agreed on the schema"


def test_empty_model_reply_falls_back(monkeypatch):
    class Blank:
        async def chat(self, messages, tools):
            return SimpleNamespace(text="")

    monkeypatch.setattr("harness.providers.get_provider", lambda: Blank())
    assert asyncio.run(ctx.compact(prior_summary="kept", dropped=[])) == "kept"
