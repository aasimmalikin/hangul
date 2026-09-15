import asyncio

from harness.db.memory import remember
from harness.tools.base import Tool


def make_remember_tool(user_id: str) -> Tool:
    """Create a remember tool for a specific user."""
    async def remember_tool(content: str, kind: str = "preference") -> str:
        """Store a new memory for the user."""
        # Sync DB write against a remote Postgres: keep it off the event loop.
        await asyncio.to_thread(remember, user_id, content, kind)
        return f"Noted: {content}"
    
    return Tool(
        name = "remember",
        description = ("Store a durable fact or preference about the user, so you recall "
            "it in future conversations. Use ONLY when the user states a lasting "
            "preference ('I prefer metric units'), a durable fact about themselves "
            "('I work at Nimbus'), or corrects something you believed. Do NOT "
            "store transient or task-specific details."),
        parameter = {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "kind": {"type": "string"}
            },
            "required": ["content"]
        },
        handler = remember_tool,
    )