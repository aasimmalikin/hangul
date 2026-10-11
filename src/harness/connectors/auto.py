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
    "gmail": ("email", "emails", "e-mail", "mail", "inbox", "gmail", "unread", "reply", "replies", "replied", "send",
              "owe", "waiting on me", "get back to", "respond", "respond to",
              "draft", "message from", "newsletter", "my day", "brief", "briefing"),
    "calendar": ("calendar", "meeting", "meetings", "schedule", "scheduled", "free", "busy", "appointment",
                 "event", "events", "reschedule", "move my", "cancel my", "tomorrow at", "today at", "my day",
                 "agenda", "brief", "briefing", "standup", "call with", "video call", "google meet", "meet link"),
    "contacts": ("contact", "contacts", "phone number", "email address", "number of", "email priya",
                 "send to", "email to", "mail to"),
    "drive": ("drive", "google drive", "my files in drive", "shared folder"),
    "docs": ("google doc", "google docs", "gdoc"),
    "sheets": ("sheet", "sheets", "spreadsheet", "budget sheet", "google sheet", "tracker"),
    "meet": ("google meet", "meet link", "meeting link", "video call", "video meeting", "instant meeting",
             "transcript", "transcripts", "the call", "last call", "on the call", "who joined", "meeting notes"),
    # not plain "issue", "review" or "commit": "an issue with my laptop" isn't GitHub (see _GITHUB below)
    "github": ("github", "pull request", "pull requests", "pr", "prs", "repo", "repos", "repository",
               "repositories", "code review", "review request", "review requests", "open issues", "commits"),
    "notion": ("notion", "wiki", "notion page"),
    "slack": ("slack", "channel", "dm", "#general", "workspace message"),
}

# GitHub without the word: "issue #12", "PR 5", "owner/name#3", "open an issue", or an
# owner/name next to a GitHub word ("comment on acme/app's issue", "README of acme/app")
_GITHUB = re.compile(
    r"\b(issue|issues|pr|pull)\s*#?\d+\b"
    r"|\b[\w.-]+/[\w.-]+#\d+\b"
    r"|#\d+\b.{0,40}\b(issue|pr|review|merge)"
    r"|\b(open|create|file)\s+(an?\s+|the\s+|a\s+new\s+|new\s+)?(github\s+)?(issue|bug\s+report)\b",
    re.IGNORECASE)
_REPO_SLUG = re.compile(r"(?<![\w/.:])[A-Za-z][\w.-]*/[A-Za-z][\w.-]+(?![\w/])")
_REPO_WORDS = re.compile(r"\b(issues?|comment|comments|readme|ci|checks?|branch(es)?|commits?|merged?|labels?|"
                         r"pull|prs?|files?|code|bugs?)\b", re.IGNORECASE)


# "email Priya" style: sending mail to a named person also needs the address book
_SEND_TO_PERSON = re.compile(r"\b(email|mail|message|text|send)\s+(?!me\b|my\b|the\b|a\b|an\b|it\b)[A-Z][a-z]+")


def route(question: str, connected: list[str]) -> list[str]:
    q = f" {question.lower()} "
    picked = []
    for app in connected:
        words = KEYWORDS.get(app, ())
        if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", q) for w in words):
            picked.append(app)
    if "github" in connected and "github" not in picked and (
            _GITHUB.search(question) or (_REPO_SLUG.search(question) and _REPO_WORDS.search(question))):
        picked.append("github")
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
        from harness.connectors.registry import BUILTIN
        keys += [a for a, ok in (await apps_status(user_id)).items() if ok and not BUILTIN[a].hidden]
    except Exception:  # noqa: BLE001
        pass
    return keys
