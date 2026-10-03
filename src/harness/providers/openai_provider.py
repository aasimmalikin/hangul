from openai import AsyncOpenAI
from harness.providers.base import AssistantTurn, ToolCall
import json

from harness.logging import log


# model -> what to send as reasoning_effort alongside function tools, learnt
# from OpenAI's refusal: "none" when it asks for that, None = omit the field.
# Remembered so each later call skips the refused request.
_EFFORT_WITH_TOOLS: dict[str, str | None] = {}


def _apply_effort_fallback(kwargs: dict, fallback: str | None) -> dict:
    kwargs = {k: v for k, v in kwargs.items() if k != "reasoning_effort"}
    if fallback is not None:
        kwargs["reasoning_effort"] = fallback
    return kwargs


def cached_tokens(usage) -> int:
    """Input tokens OpenAI served from its prompt cache (0 when not reported)."""
    details = getattr(usage, "prompt_tokens_details", None)
    return int(getattr(details, "cached_tokens", 0) or 0)


class OpenAIProvider:
    def __init__(self, api_key: str, model: str = "gpt-4o",
                 reasoning_effort: str | None = None,
                 client: AsyncOpenAI | None = None):
        self.client = client or AsyncOpenAI(api_key=api_key)
        self.model = model
        # Sent as `reasoning_effort` when set; leave None for non-reasoning models.
        self.reasoning_effort = reasoning_effort

    def bound(self, model: str, reasoning_effort: str | None) -> "OpenAIProvider":
        """A per-request provider for another model/effort, sharing this HTTP client."""
        return OpenAIProvider(api_key="", model=model,
                              reasoning_effort=reasoning_effort, client=self.client)

    def _base_kwargs(self, messages: list[dict], tools: list[dict],
                     tool_choice: str | None) -> dict:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "tools": tools or None,
        }
        if tool_choice is not None and tools:
            kwargs["tool_choice"] = tool_choice
        if self.reasoning_effort is not None:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs

    async def _create(self, kwargs: dict):
        """chat.completions.create, retried once when the API refuses
        ``reasoning_effort`` together with function tools (OpenAI does this for
        some models on /v1/chat/completions; the Responses API would be the
        full fix). Some models want the field dropped (they then use their
        default effort); others, like gpt-5.6-luna, refuse their default too and
        ask for ``reasoning_effort="none"``. What worked is remembered per
        model, so only the first call pays for the refused request."""
        from openai import BadRequestError
        model = kwargs.get("model", "")
        if kwargs.get("tools") and model in _EFFORT_WITH_TOOLS:
            kwargs = _apply_effort_fallback(kwargs, _EFFORT_WITH_TOOLS[model])
        try:
            return await self.client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            msg = str(e)
            asks_none = "'none'" in msg and kwargs.get("reasoning_effort") != "none"
            # (an omitted field is refused too when the model's own default is not "none")
            if "reasoning_effort" in msg and ("reasoning_effort" in kwargs or asks_none):
                fallback = "none" if asks_none else None
                log.warning("reasoning_effort not accepted with tools; retrying",
                            model=model, effort=kwargs.get("reasoning_effort"), fallback=fallback or "omitted")
                response = await self.client.chat.completions.create(**_apply_effort_fallback(kwargs, fallback))
                if kwargs.get("tools"):
                    _EFFORT_WITH_TOOLS[model] = fallback
                return response
            raise

    async def chat(self, messages: list[dict], tools: list[dict],
                   tool_choice: str | None = None) -> AssistantTurn:
        """Generate a completion using the OpenAI API.

        tool_choice: pass "required" to force the model to call a tool this turn
        (used by docs-only mode so it MUST call search_docs, not narrate)."""
        kwargs = self._base_kwargs(messages, tools, tool_choice)

        response = await self._create(kwargs)
        msg = response.choices[0].message
        calls = [ToolCall(id=tc.id, name=tc.function.name,
                          arguments=json.loads(tc.function.arguments or "{}"))
                 for tc in (msg.tool_calls or [])]
        usage = response.usage
        return AssistantTurn(
            text=msg.content,
            tool_calls=calls,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
            cached_input_tokens=cached_tokens(usage),
        )

    async def chat_stream(self, messages: list[dict], tools: list[dict],
                          tool_choice: str | None = None):
        """Like chat(), but yields progress as it arrives.

        Yields, in order of arrival:
          ("token", str)                       a text delta
          ("tool_start", {"id", "name"})       the model began a tool call
          ("tool_args", {"id", "delta"})       a fragment of that call's JSON arguments
          ("final", AssistantTurn)             once complete
        The caller streams tokens and tool progress live (so the user can
        watch, say, a file's content being drafted) and uses the final
        AssistantTurn for the parsed tool calls and token accounting.
        """
        kwargs = self._base_kwargs(messages, tools, tool_choice)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        stream = await self._create(kwargs)

        text_parts: list[str] = []
        tool_fragments: dict[int, dict] = {}
        input_tokens = output_tokens = cached_input = 0

        async for chunk in stream:
            if chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0)
                output_tokens = getattr(chunk.usage, "completion_tokens", 0)
                cached_input = cached_tokens(chunk.usage)

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                text_parts.append(delta.content)
                yield ("token", delta.content)

            for tc in (delta.tool_calls or []):
                slot = tool_fragments.setdefault(
                    tc.index, {"id": "", "name": "", "args": "", "announced": False})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if slot["id"] and slot["name"] and not slot["announced"]:
                    slot["announced"] = True
                    yield ("tool_start", {"id": slot["id"], "name": slot["name"]})
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
                    if slot["announced"]:
                        yield ("tool_args", {"id": slot["id"], "delta": tc.function.arguments})

        calls = [
            ToolCall(id=f["id"], name=f["name"],
                     arguments=json.loads(f["args"] or "{}"))
            for f in tool_fragments.values() if f["name"]
        ]
        yield ("final", AssistantTurn(
            text="".join(text_parts) or None,
            tool_calls=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input,
        ))
