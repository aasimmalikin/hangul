"""The recall_episodes tool: on-demand retrieval of past conversations.

Semantic memory (the recall tool) holds durable facts about the user.
Episodic memory holds summaries of PAST CONVERSATIONS -- "what did we discuss
last week". This tool lets the agent fetch relevant past episodes by meaning,
not keyword, when a question refers to earlier sessions.
"""
from harness.tools.base import Tool
from harness.db.episodes import recall_episodes


def make_recall_episodes_tool(user_id: str) -> Tool:
    async def recall_episodes_fn(query: str) -> str:
        episodes = await recall_episodes(user_id, query)
        if not episodes:
            return "No relevant past conversations found."
        return "Relevant past conversations:\n" + "\n".join(
            f"- {e}" for e in episodes
        )

    return Tool(
        name="recall_episodes",
        description=(
            "Recall summaries of past conversations with this user, retrieved by "
            "meaning. Call this when the user refers to something discussed in an "
            "earlier session ('what did we decide about X last time', 'remember "
            "when I asked about Y'). Do not use for facts about the user -- use "
            "recall for those."
        ),
        parameter={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search past conversations for.",
                },
            },
            "required": ["query"],
        },
        handler=recall_episodes_fn,
    )