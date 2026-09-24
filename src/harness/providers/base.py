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

class Provider(Protocol):
    """Abstract class for a provider that can generate completions."""
    model: str
    reasoning_effort: str | None

    async def chat(self, messages: list[dict], tools: list[dict])->AssistantTurn: ...

