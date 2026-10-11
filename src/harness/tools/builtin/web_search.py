"""web_search: query the live internet via Tavily. Complements search_docs —
that searches YOUR documents (closed corpus); this searches the OPEN web.

The Tavily key never enters this module: the call goes through the token
vault (system credential ``tavily``), which injects it server-side."""
import json

from harness.tools.base import Tool
from harness.vault import current as current_vault
from harness.vault.proxy import ProxyError
from harness.vault.vault import SYSTEM, VaultError

UNAVAILABLE = (
    "WEB_SEARCH_UNAVAILABLE: the web search service could not be reached "
    "({why}). Do not retry web_search; answer from available "
    "information or say you cannot access the web right now."
)


def _format(results: list[dict]) -> str:
    if not results:
        return "No web results found"
    return "\n\n".join(
        f"[{r.get('title', '')}] ({r.get('url', '')})\n{r.get('content', '')}" for r in results
    )


async def search_results(query: str, max_results: int = 3) -> list[dict] | str:
    """Tavily's results ([{title, url, content}]), or an UNAVAILABLE message.
    A search that was made is charged to the open meter."""
    vault = current_vault()
    if vault is None:
        return UNAVAILABLE.format(why="vault not configured")
    try:
        resp = await vault.call(subject=SYSTEM, provider="tavily", method="POST", path="/search",
                                body=json.dumps({"query": query, "max_results": max_results}))
    except (VaultError, ProxyError) as e:
        return UNAVAILABLE.format(why=type(e).__name__)
    if resp.status != 200:
        return UNAVAILABLE.format(why=f"HTTP {resp.status}")
    from harness.billing import meter
    from harness.config import get_settings
    meter.add(get_settings().web_search_usd, "web_search")   # the search was made: it costs a credit
    try:
        results = json.loads(resp.body).get("results", [])
    except (json.JSONDecodeError, AttributeError):
        return UNAVAILABLE.format(why="bad response")
    return [r for r in results if isinstance(r, dict)]


async def web_search(query: str, max_results: int = 3) -> str:
    results = await search_results(query, max_results)
    return results if isinstance(results, str) else _format(results)


WEB_SEARCH_TOOL = Tool(
    name="web_search",
    description="Search the live web. Use it only when the answer depends on current "
                "or external information the user's own material would not contain -- "
                "recent events, news, prices, public facts. Check search_docs first for "
                "anything about the user's documents. Cite the source URL of every "
                "result you use.",
    parameter={
        "type": "object",
        "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
        "required": ["query"],
    },
    handler=web_search,
)
