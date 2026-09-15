""" The recall tool: on-demand lookup of what's remembered about the user.
The always-loaded profile covers the top few facts; recall lets the agent
fetch the fuller set when a question needs it, rather than loading everything
into every prompt."""

import asyncio

from harness.db.memory import list_active
from harness.tools.base import Tool


def make_recall_tool(user_id: str)->Tool:
    """Create a recall tool for a specific user."""
    async def recall(query: str) -> str:
        """Recall memories for the user that match the query."""
        rows = await asyncio.to_thread(list_active, user_id)
        if not rows:
            return "No memories found."
        
        return "\n".join(f"- [{r.kind}] {r.content}" for r in rows)
    
    return Tool(
        name = "recall",
        description = ("Recall stored facts and preferences about the current user. "
            "Call this when the user's question depends on something they told "
            "you earlier (their preferences, projects, or details)."),
        parameter = {
            "type": "object",
            "properties": {
                "query": {"type": "string"}
            },
            "required": ["query"]
        },
        handler = recall,
    )