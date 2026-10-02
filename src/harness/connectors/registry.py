from harness.connectors.arxiv import make_arxiv_tools
from harness.connectors.base import Connector
from harness.connectors.google_rest import make_google_tools
from harness.policy.tiers import Tier
from harness.tools.base import Tool

GOOGLE_INSTRUCTION = (
    "The Google Workspace connector is ON: gmail__*, calendar__*, drive__* and docs__* tools act on the "
    "user's own Google account. Read freely when the user asks about their mail, events or files; "
    "creating events, drafts or document edits pause for their approval -- say what you are about to "
    "do before calling them. Never forward or quote mail to third parties unasked. Gmail search "
    "syntax works in gmail__search_messages (newer_than:1d, from:, is:unread, subject:)."
)

GOOGLE_PRODUCT_INSTRUCTIONS: dict[str, str] = {
    "gmail": ("The Gmail connector is ON: gmail__* tools act on the user's own mailbox. Read freely when the "
              "user asks about their mail; drafts are fine, sending pauses for their approval -- say what you "
              "are about to send before calling it. Never forward or quote mail to third parties unasked. "
              "Gmail search syntax works in gmail__search_messages (newer_than:1d, from:, is:unread, subject:)."),
    "calendar": ("The Google Calendar connector is ON: calendar__* tools act on the user's own calendar. List "
                 "events freely; creating an event pauses for their approval -- say what you are about to "
                 "create before calling it."),
    "drive": ("The Google Drive connector is ON: drive__* tools search and read the user's own Drive files. "
              "Cite files by name and link."),
    "docs": ("The Google Docs connector is ON: docs__* tools read the user's own Google Docs by id; appending "
             "text pauses for their approval -- say what you are about to add before calling it."),
}


def _google_product_tools(product: str):
    """A per-user factory exposing only ``<product>__*`` of the Google REST tools."""
    def factory(user_id: str) -> list[Tool]:
        return [t for t in make_google_tools(user_id) if t.name.startswith(f"{product}__")]
    return factory


def _google_product(key: str, label: str, description: str, icon: str) -> Connector:
    return Connector(key=key, label=label, description=description, kind="builtin",
                     tools=_google_product_tools(key), per_user=True, auth="google", icon=icon,
                     product=key, group="Google Workspace", instruction=GOOGLE_PRODUCT_INSTRUCTIONS[key])


# The Google products are separate switches so a conversation only gets the
# tools (and the account access) it needs. "google" is the old all-in-one key:
# hidden from the catalogue, still accepted so existing chats and tasks work.
GOOGLE_PRODUCTS = ("gmail", "calendar", "drive", "docs")

BUILTIN: dict[str, Connector] = {
    "gmail": _google_product("gmail", "Gmail", "Search, read and draft email in your Gmail", "mail"),
    "calendar": _google_product("calendar", "Google Calendar", "See and create events on your calendar", "calendar"),
    "drive": _google_product("drive", "Google Drive", "Find and read files in your Drive", "brand-google-drive"),
    "docs": _google_product("docs", "Google Docs", "Read and append to your Google Docs", "file-text"),
    "google": Connector(
        key="google", label="Google Workspace", description="Gmail, Calendar, Drive and Docs on your own Google account",
        kind="builtin", tools=make_google_tools, per_user=True, auth="google", icon="brand-google",
        group="Google Workspace", hidden=True, instruction=GOOGLE_INSTRUCTION,
    ),
    "arxiv": Connector(
        key="arxiv", label="Research", description="Search and read arXiv papers", kind="builtin",
        tools=make_arxiv_tools, icon="book-2",
        tiers={"arxiv_search": Tier.SAFE, "arxiv_paper": Tier.SAFE},
        instruction=("The Research connector (arXiv) is ON for this conversation: for questions about "
                     "papers, methods, authors or recent research, search arXiv with arxiv_search and "
                     "cite results by arXiv id. Do not use web_search for literature when arXiv can "
                     "answer."),
    ),
}

MAX_PER_REQUEST = 8


def _mcp_connectors() -> dict[str, Connector]:
    """MCP servers tagged ``connector`` in servers.yaml become opt-in connectors.
    Servers sharing a ``bundle:<key>`` tag become ONE connector (the Google
    Workspace bundle); a ``per-user`` server needs the user's own session."""
    from harness.mcp.config import load_server_configs
    out: dict[str, Connector] = {}
    bundles: dict[str, list] = {}
    try:
        cfgs = load_server_configs()
    except ValueError:
        return out
    for cfg in cfgs:
        if "connector" not in cfg.tags:
            continue
        bundle = cfg.tag("bundle")
        # a builtin connector of the same key wins (e.g. Google over REST); a
        # bundled server is judged by its bundle key, not its own name
        if (bundle or cfg.name) in BUILTIN:
            continue
        if bundle:
            bundles.setdefault(bundle, []).append(cfg)
            continue
        label = cfg.tag("label") or cfg.name.title()
        out[cfg.name] = Connector(key=cfg.name, label=label, description=cfg.tag("description") or f"MCP server '{cfg.name}'",
                                  kind="mcp", server=cfg.name, per_user=cfg.per_user, auth=cfg.tag("auth"),
                                  icon=cfg.tag("icon") or "plug",
                                  instruction=BUNDLE_INSTRUCTIONS.get(cfg.name, ""))
    for key, members in bundles.items():
        first = members[0]
        out[key] = Connector(
            key=key, label=first.tag("label") or key.title(),
            description=first.tag("description") or f"{len(members)} services: " + ", ".join(m.name for m in members),
            kind="mcp", servers=tuple(m.name for m in members), per_user=any(m.per_user for m in members),
            auth=first.tag("auth"), icon=first.tag("icon") or "brand-google",
            instruction=BUNDLE_INSTRUCTIONS.get(key, ""),
        )
    return out


BUNDLE_INSTRUCTIONS: dict[str, str] = {
    "google": ("The Google Workspace connector is ON: gmail__*, calendar__*, drive__* and docs__* tools act on "
               "the user's own Google account. Read freely when the user asks about their mail, events or "
               "files; anything that sends, creates, changes or deletes pauses for their approval -- say what "
               "you are about to do before calling it. Never forward or quote mail to third parties unasked."),
}


def all_connectors() -> dict[str, Connector]:
    return {**BUILTIN, **_mcp_connectors()}


def available() -> list[dict]:
    return [c.public() for c in all_connectors().values() if not c.hidden]


def validate_keys(keys: list[str]) -> list[str]:
    """Dedupe, keep order, raise ValueError on an unknown key."""
    known = all_connectors()
    seen: list[str] = []
    for k in keys:
        if k not in known:
            raise ValueError(f"unknown connector {k!r}; available: {sorted(known)}")
        if k not in seen:
            seen.append(k)
    if len(seen) > MAX_PER_REQUEST:
        raise ValueError(f"at most {MAX_PER_REQUEST} connectors per request")
    return seen


def _servers_of(c: Connector) -> tuple[str, ...]:
    return c.servers or ((c.server,) if c.server else ())


def tools_for(keys: list[str], mcp_tools: list[Tool] = (), *, user_id: str | None = None,
              manager=None) -> tuple[list[Tool], str, dict[str, Tier]]:
    """Tools, prompt instruction and policy tiers for the enabled connectors.
    ``mcp_tools`` is the global MCP registry (shared servers); per-user servers
    come from ``manager.tools_for_subject`` bound to ``user_id``."""
    known = all_connectors()
    tools: list[Tool] = []
    notes: list[str] = []
    tiers: dict[str, Tier] = {}
    for k in keys:
        c = known[k]
        if c.kind == "builtin" and c.tools is not None:
            if c.per_user:
                if user_id is not None:
                    tools.extend(c.tools(user_id))
            else:
                tools.extend(c.tools())
        elif c.kind == "mcp":
            for server in _servers_of(c):
                if manager is not None and manager.is_per_user(server):
                    if user_id is not None:
                        tools.extend(manager.tools_for_subject(server, user_id))
                else:
                    tools.extend(t for t in mcp_tools if t.name.startswith(f"{server}__"))
        tiers.update(c.tiers)
        if c.instruction:
            notes.append(c.instruction)
    return tools, "\n".join(notes), tiers


async def prepare(keys: list[str], user_id: str) -> list[str]:
    """Open the user's sessions for per-user MCP connectors among ``keys``.
    Returns human-readable problems for connectors that could not be opened
    (not connected, token refused...) -- the run continues without them."""
    from harness.mcp.manager import current as mcp_current
    manager = mcp_current()
    problems: list[str] = []
    if manager is None:
        return problems
    known = all_connectors()
    for k in keys:
        c = known.get(k)
        if c is None or c.kind != "mcp":
            continue
        for server in _servers_of(c):
            if not manager.is_per_user(server):
                continue
            try:
                await manager.ensure_user_session(server, user_id)
            except Exception as e:  # noqa: BLE001 - surfaced to the model/user as text
                problems.append(f"Connector '{c.label}' ({server}) is unavailable: {e}")
    return problems
