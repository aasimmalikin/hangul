"""Connected apps that "just work": pick which of the user's connected apps a
message needs, from its words, so nobody has to switch Gmail on before asking
about their email.

Deliberately a keyword router, not "load every connected app": each app adds
its tools to every turn's prompt (~30 tools with everything connected), which
costs tokens and slows the model. A match on the question (or an app the
conversation already used, inherited from its stored connectors) is enough.
"""

import re

# app -> words that mean the user wants it (matched case-insensitively, whole words)
KEYWORDS: dict[str, tuple[str, ...]] = {
    "gmail": ("email", "emails", "e-mail", "mail", "inbox", "gmail", "unread", "reply", "replied", "send",
              "draft", "message from", "newsletter", "my day", "brief", "briefing"),
    "calendar": ("calendar", "meeting", "meetings", "schedule", "scheduled", "free", "busy", "appointment",
                 "event", "events", "reschedule", "move my", "cancel my", "tomorrow at", "today at", "my day",
                 "agenda", "brief", "briefing", "standup", "call with"),
    "contacts": ("contact", "contacts", "phone number", "email address", "number of", "email priya",
                 "send to", "email to", "mail to"),
    "drive": ("drive", "google drive", "my files in drive", "shared folder"),
    "docs": ("google doc", "google docs", "gdoc"),
    "sheets": ("sheet", "sheets", "spreadsheet", "budget sheet", "google sheet", "tracker"),
    "github": ("github", "pull request", "pull requests", "pr", "prs", "issue", "issues", "repo", "repository",
               "review", "commit"),
    "notion": ("notion", "wiki", "notion page"),
    "slack": ("slack", "channel", "dm", "#general", "workspace message"),
}

# "email Priya" style: sending mail to a named person also needs the address book
_SEND_TO_PERSON = re.compile(r"\b(email|mail|message|text|send)\s+(?!me\b|my\b|the\b|a\b|an\b|it\b)[A-Z][a-z]+")


def route(question: str, connected: list[str]) -> list[str]:
    q = f" {question.lower()} "
    picked = []
    for app in connected:
        words = KEYWORDS.get(app, ())
        if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", q) for w in words):
            picked.append(app)
    if "contacts" in connected and "contacts" not in picked and _SEND_TO_PERSON.search(question):
        picked.append("contacts")
        if "gmail" in connected and "gmail" not in picked:
            picked.append("gmail")
    return picked


async def connected_apps(user_id: str) -> list[str]:
    """Connector keys this user has actually connected (Google products with
    granted scopes, work apps with a saved token)."""
    from harness.api.routes.integrations import apps_status
    from harness.connectors.registry import GOOGLE_PRODUCTS
    from harness.integrations.google_oauth import google_tokens
    keys: list[str] = []
    try:
        st = await google_tokens().status(user_id)
        keys += [p for p in st.get("products", []) if p in GOOGLE_PRODUCTS]
    except Exception:  # noqa: BLE001 - no Google, no Google apps
        pass
    try:
        keys += [a for a, ok in (await apps_status(user_id)).items() if ok]
    except Exception:  # noqa: BLE001
        pass
    return keys
