from openai import AsyncOpenAI
from harness.providers.base import AssistantTurn, ToolCall
import json


class OpenAIProvider:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def chat(self, messages: list[dict], tools: list[dict],
                   tool_choice: str | None = None) -> AssistantTurn:
        """Generate a completion using the OpenAI API.

        tool_choice: pass "required" to force the model to call a tool this turn
        (used by docs-only mode so it MUST call search_docs, not narrate)."""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "tools": tools or None,
        }
        if tool_choice is not None and tools:
            kwargs["tool_choice"] = tool_choice

        response = await self.client.chat.completions.create(**kwargs)
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
        kwargs = {
            "model": self.model,
            "messages": messages,
            "tools": tools or None,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tool_choice is not None and tools:
            kwargs["tool_choice"] = tool_choice

        stream = await self.client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        tool_fragments: dict[int, dict] = {}
        input_tokens = output_tokens = 0

        async for chunk in stream:
            if chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0)
                output_tokens = getattr(chunk.usage, "completion_tokens", 0)

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
        ))
