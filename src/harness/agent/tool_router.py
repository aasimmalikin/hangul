"""Which tools a run starts with: the shop's core set, plus the groups the message needs.

Every tool's description is sent on every model call, and the full everyday set
was ~4,700 tokens before the user said a word. A shop owner's messages are mostly
about sales, customers, reminders and promises, so those are always loaded; posts,
files, launch plans, places, the web, weather and conversions are added when the
words call for them (whole-word keywords, English and common Hinglish, like
connectors/auto.py), or when the conversation used one of them recently.

If the guess misses, the model calls ``more_tools(group)`` and the group is added to
the run's registry (the loop re-reads it each turn), so a misrouted request costs
one extra step, never a refusal. No model call is made to route.
"""

import re

from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry

# Optional groups: tool names (only those present in the run are loaded) and a one-line label for more_tools.
GROUPS: dict[str, tuple[tuple[str, ...], str]] = {
    "posts": (("finish_image", "brands", "generate_image", "edit_image"), "brand posts, posters, stories and images"),
    "files": (("create_file", "analyze_data"), "making PDF / Word / Excel / slides, and charts or analysis of a spreadsheet"),
    "launch": (("launch_plan",), "a plan and costs for starting a new business"),
    "places": (("maps_search", "travel_time"), "places nearby, directions and travel time"),
    "web": (("web_search", "read_webpage"), "searching the web and reading a web page"),
    "weather": (("weather",), "the weather"),
    "convert": (("convert",), "unit and currency conversion"),
    "photos": (("view_image",), "questions about a photo or image in their files"),
}

_W = r"(?<![\w])(?:{})(?![\w])"
KEYWORDS: dict[str, re.Pattern] = {k: re.compile(_W.format(v), re.IGNORECASE) for k, v in {
    "posts": r"post|posts|poster|posters|banner|flyer|flyers|story|stories|reel|reels|carousel|insta|instagram|"
             r"facebook post|logo|brand|branding|design|creative|image|images|picture|status|offer post|ad|advert",
    "files": r"pdf|excel|xlsx|csv|spreadsheet|report|chart|charts|graph|graphs|document|docx|word file|slides|ppt|"
             r"powerpoint|invoice|quotation|menu card|price list|analy[sz]e|analysis",
    "launch": r"start a|open a|opening a|launch|new (?:shop|cafe|café|business|outlet|kitchen|salon)|"
              r"cost to (?:start|open)|setup cost|business plan|kholna|shuru",
    "places": r"near|nearby|near me|paas|directions|route|distance|how far|kitna door|map|maps|location|travel time|"
              r"reach|commute|drive to",
    "web": r"search|google|internet|website|web|latest|news|link|http|https|www|url",
    "weather": r"weather|rain|raining|barish|baarish|mausam|temperature|garmi|thand|humid|sunny",
    "convert": r"convert|conversion|exchange rate|currency|usd|dollar|dollars|euro|euros|kg to|grams to|lbs?|"
               r"litres? to|ml to",
    "photos": r"photo|photos|pic|pics|screenshot|picture|image|file i just sent|i just sent",
}.items()}

OPTIONAL: frozenset[str] = frozenset(n for names, _ in GROUPS.values() for n in names)


def groups_for(question: str, recent_tools: set[str] | frozenset[str] = frozenset(), mode: str = "default") -> set[str]:
    """The optional groups this message needs: keyword hits, plus any group whose tool the
    conversation used recently (so "make it red" after a post still has finish_image)."""
    q = question or ""
    picked = {g for g, rx in KEYWORDS.items() if rx.search(q)}
    picked |= {g for g, (names, _) in GROUPS.items() if set(names) & set(recent_tools)}
    if mode == "research":
        picked.add("web")
    return picked


def recent_tool_names(rows: list, last: int = 12) -> set[str]:
    """Tool names called in the last ``last`` transcript rows (conversation_messages, OpenAI shape)."""
    names: set[str] = set()
    for r in rows[-last:]:
        extra = getattr(r, "extra", None) or (r.get("extra") if isinstance(r, dict) else None) or {}
        for tc in extra.get("tool_calls") or []:
            name = (tc.get("function") or {}).get("name") or tc.get("name")
            if name:
                names.add(name)
    return names


def make_more_tools_tool(run: ToolRegistry, held: dict[str, Tool]) -> Tool:
    """``held``: the optional tools left out of the run, by name (already plan-gated)."""
    available = {g: label for g, (names, label) in GROUPS.items() if any(n in held for n in names)}

    async def more_tools(group: str) -> str:
        names = [n for n in GROUPS.get(group, ((), ""))[0] if n in held]
        if not names:
            return f"No such group here. Groups: {', '.join(available) or 'none'}."
        for n in names:
            run.registry(held.pop(n))
        return f"Loaded {', '.join(names)}. Call the one you need now."

    return Tool(
        name="more_tools",
        description=("Load more tools when the user wants something your current tools can't do. Groups: "
                     + "; ".join(f"{g} = {label}" for g, label in available.items()) + "."),
        parameter={"type": "object", "properties": {"group": {"type": "string", "enum": list(available)}},
                   "required": ["group"]},
        handler=more_tools,
    )


def narrow(registry: ToolRegistry, question: str, recent_tools: set[str] | frozenset[str] = frozenset(),
           mode: str = "default") -> ToolRegistry:
    """A registry with the core tools, the groups this message needs, and ``more_tools``
    holding the rest. Tools outside OPTIONAL (connectors, search_docs, ask_user, ...) are
    always kept. Returns ``registry`` itself when nothing would be left out."""
    keep = {n for g in groups_for(question, recent_tools, mode) for n in GROUPS[g][0]}
    run, held = ToolRegistry(), {}
    for t in registry.list():
        if t.name in OPTIONAL and t.name not in keep:
            held[t.name] = t
        else:
            run.registry(t)
    if not held:
        return registry
    run.registry(make_more_tools_tool(run, held))
    return run
