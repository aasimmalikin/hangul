from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from pydantic import BaseModel

class ToolResult(BaseModel):
    ok: bool
    content: str
    # optional structured payload for the UI (never shown to the model); e.g. a
    # Gmail message list the chat renders as a Google-styled card
    ui: dict | None = None


@dataclass
class ToolOutput:
    """What a handler may return instead of a plain string: the text the model
    reads plus a structured ``ui`` block for the chat to render."""
    text: str
    ui: dict | None = None

    def __str__(self) -> str:
        return self.text

@dataclass
class Tool:
    name: str
    description: str
    parameter: dict[str, Any]
    handler: Callable[..., Awaitable[str]]
