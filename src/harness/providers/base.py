from typing import Protocol
from pydantic import BaseModel

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict

class AssistantTurn(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = []
    input_tokens: int = 0
    output_tokens: int = 0
    # the part of input_tokens OpenAI served from its prompt cache (billed at the cached rate)
    cached_input_tokens: int = 0

class ModelUnavailable(Exception):
    """The model service could not answer (no credit, rate limit, timeout, outage).
    ``str()`` is the plain message for the user; ``reason`` goes in X-Reason as
    ``model_<reason>``. Raised by providers instead of their SDK's errors, so a
    route answers 503 with a sentence rather than a bare 500 or the vendor's text."""

    MESSAGES = {
        "unavailable": "Hangul's AI service isn't available right now. This is on our side, not yours -- please try again later.",
        "busy": "Hangul is very busy right now. Please try again in a minute.",
        "timeout": "The AI service took too long to answer. Please try again.",
        "unreachable": "Hangul couldn't reach its AI service. Please try again in a moment.",
    }

    def __init__(self, reason: str):
        self.reason = reason if reason in self.MESSAGES else "unavailable"
        super().__init__(self.MESSAGES[self.reason])


class Provider(Protocol):
    """Abstract class for a provider that can generate completions."""
    model: str
    reasoning_effort: str | None

    async def chat(self, messages: list[dict], tools: list[dict])->AssistantTurn: ...

