"""OpenAIProvider._create: when OpenAI refuses reasoning_effort with function
tools, retry the way the error asks (drop it, or send "none") and remember it."""
import asyncio

import httpx
import pytest
from openai import BadRequestError

from harness.providers import openai_provider as op


def refusal(msg: str) -> BadRequestError:
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return BadRequestError(msg, response=httpx.Response(400, request=req), body=None)


class FakeCompletions:
    def __init__(self, refuse):
        self.refuse, self.calls = refuse, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.refuse(kwargs):
            raise refusal(self.message)
        return "ok"


def provider(refuse, message):
    comp = FakeCompletions(refuse)
    comp.message = message
    client = type("C", (), {"chat": type("Ch", (), {"completions": comp})()})()
    return op.OpenAIProvider(api_key="", model="m", reasoning_effort="medium", client=client), comp


@pytest.fixture(autouse=True)
def clean():
    op._EFFORT_WITH_TOOLS.clear()
    yield
    op._EFFORT_WITH_TOOLS.clear()


TOOLS = [{"type": "function", "function": {"name": "t", "parameters": {}}}]


def test_luna_style_refusal_retries_with_none_and_remembers():
    msg = ("Function tools with reasoning_effort are not supported for m in /v1/chat/completions. "
           "To use function tools, use /v1/responses or set reasoning_effort to 'none'.")
    p, comp = provider(lambda kw: kw.get("reasoning_effort") != "none", msg)
    kw = p._base_kwargs([], TOOLS, None)
    assert asyncio.run(p._create(kw)) == "ok"
    assert [c.get("reasoning_effort") for c in comp.calls] == ["medium", "none"]
    # the next call goes straight to "none": no second refused request
    asyncio.run(p._create(p._base_kwargs([], TOOLS, None)))
    assert [c.get("reasoning_effort") for c in comp.calls] == ["medium", "none", "none"]


def test_luna_style_refusal_with_no_effort_set_still_sends_none():
    msg = "Function tools with reasoning_effort are not supported for m. set reasoning_effort to 'none'."
    p, comp = provider(lambda kw: kw.get("reasoning_effort") != "none", msg)
    p.reasoning_effort = None
    assert asyncio.run(p._create(p._base_kwargs([], TOOLS, None))) == "ok"
    assert [c.get("reasoning_effort") for c in comp.calls] == [None, "none"]


def test_older_style_refusal_drops_the_field():
    p, comp = provider(lambda kw: "reasoning_effort" in kw, "reasoning_effort is not supported with function tools")
    assert asyncio.run(p._create(p._base_kwargs([], TOOLS, None))) == "ok"
    assert "reasoning_effort" not in comp.calls[-1]
    assert op._EFFORT_WITH_TOOLS["m"] is None


def test_without_tools_the_effort_is_kept():
    op._EFFORT_WITH_TOOLS["m"] = "none"
    p, comp = provider(lambda kw: False, "")
    asyncio.run(p._create(p._base_kwargs([], [], None)))
    assert comp.calls[-1]["reasoning_effort"] == "medium"


def test_other_errors_are_raised():
    p, _ = provider(lambda kw: True, "context length exceeded")
    with pytest.raises(BadRequestError):
        asyncio.run(p._create(p._base_kwargs([], TOOLS, None)))
