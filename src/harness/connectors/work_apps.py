"""GitHub, Notion and Slack connectors (Pro plan), all through the token vault.

The user pastes a token once (``POST /integrations/{github,notion,slack}``);
it is stored encrypted and every call goes through ``vault.call`` -- the only
place it is decrypted -- so the model, the tools and the logs never see it.
Reads run freely; anything that posts, creates or comments is tier
DESTRUCTIVE (an approval card) and in ``guard.OUTBOUND``-style step-up via the
side-effect prefixes. Each tool returns text the model can act on, including
"connect it at /vault" when there is no token.
"""

import json
from collections.abc import Awaitable, Callable

from harness.tools.base import Tool, ToolOutput

NOTION_VERSION = "2022-06-28"
MAX_TEXT = 12_000


class AppError(Exception):
    pass


async def _call(user_id: str, provider: str, method: str, path: str, *, query: dict | None = None,
                body: dict | None = None, headers: dict | None = None) -> dict:
    from harness.vault import current as current_vault
    from harness.vault.proxy import ProxyError
    from harness.vault.vault import VaultError
    vault = current_vault()
    if vault is None:
        raise AppError("VAULT_UNAVAILABLE: the token vault is not configured on this server.")
    try:
        resp = await vault.call(subject=user_id, provider=provider, method=method, path=path, query=query,
                                headers=headers, body=json.dumps(body) if body is not None else None)
    except VaultError as e:
        msg = str(e)
        if "no credential" in msg or "CONSENT" in msg:
            raise AppError(f"{provider.upper()}_NOT_CONNECTED: ask the user to connect {provider.capitalize()} at /vault.")
        raise AppError(f"{provider}: {msg}")
    except ProxyError as e:
        raise AppError(f"{provider} could not be reached ({e.status}). Do not retry now.")
    try:
        data = json.loads(resp.body) if resp.body else {}
    except ValueError:
        data = {}
    if resp.status in (401, 403):
        raise AppError(f"{provider.upper()}_AUTH: the saved {provider} token was refused ({resp.status}); "
                       f"ask the user to reconnect it at /vault.")
    if resp.status >= 400:
        detail = data.get("message") if isinstance(data, dict) else None
        raise AppError(f"{provider} error {resp.status}: {detail or resp.body[:200]}")
    if provider == "slack" and isinstance(data, dict) and data.get("ok") is False:
        raise AppError(f"slack: {data.get('error', 'request failed')}"
                       + (" (the token is missing a permission; reconnect Slack with the scopes listed at /vault)"
                          if data.get("error") in ("missing_scope", "not_allowed_token_type") else ""))
    return data


def _safe(fn: Callable[..., Awaitable[str | ToolOutput]]) -> Callable[..., Awaitable[str | ToolOutput]]:
    async def run(**kw):
        try:
            return await fn(**kw)
        except AppError as e:
            return str(e)
    return run


def _repo(repo: str) -> str:
    repo = repo.strip().removeprefix("https://github.com/").strip("/")
    if repo.count("/") != 1 or not all(repo.split("/")):
        raise AppError("Give the repository as owner/name, e.g. 'octocat/hello-world'.")
    return repo


# ------------------------------------------------------------------ github

def make_github_tools(user_id: str) -> list[Tool]:
    async def gh(method, path, **kw):
        return await _call(user_id, "github", method, path,
                           headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, **kw)

    def issue_rows(items):
        return [{"repo": i.get("repository_url", "").split("/repos/")[-1], "number": i.get("number"),
                 "title": i.get("title"), "state": i.get("state"), "url": i.get("html_url"),
                 "pr": "pull_request" in i, "updated": (i.get("updated_at") or "")[:10]} for i in items]

    async def search(query: str, max_results: int = 10):
        d = await gh("GET", "/search/issues", query={"q": query, "per_page": str(max(1, min(int(max_results or 10), 30)))})
        rows = issue_rows(d.get("items", []))
        if not rows:
            return f"No issues or pull requests match {query!r}."
        return ToolOutput("\n".join(f"{r['repo']}#{r['number']} [{r['state']}{' PR' if r['pr'] else ''}] {r['title']} — {r['url']}" for r in rows),
                          {"kind": "issues", "items": rows})

    async def my_work(kind: str = "assigned"):
        q = {"assigned": "is:open assignee:@me", "review_requests": "is:open is:pr review-requested:@me",
             "created": "is:open author:@me", "mentioned": "is:open mentions:@me"}.get(kind, "is:open assignee:@me")
        return await search(q, 20)

    async def get_issue(repo: str, number: int):
        r = _repo(repo)
        i = await gh("GET", f"/repos/{r}/issues/{int(number)}")
        comments = await gh("GET", f"/repos/{r}/issues/{int(number)}/comments", query={"per_page": "10"})
        lines = [f"{r}#{number} [{i.get('state')}] {i.get('title')}", f"by {i.get('user', {}).get('login')} · {i.get('html_url')}",
                 (i.get("body") or "")[:4000]]
        for c in comments if isinstance(comments, list) else []:
            lines.append(f"--- {c.get('user', {}).get('login')}: {(c.get('body') or '')[:1500]}")
        return "\n".join(lines)[:MAX_TEXT]

    async def create_issue(repo: str, title: str, body: str = ""):
        i = await gh("POST", f"/repos/{_repo(repo)}/issues", body={"title": title, "body": body})
        return f"Created {_repo(repo)}#{i.get('number')}: {i.get('html_url')}"

    async def comment(repo: str, number: int, body: str):
        c = await gh("POST", f"/repos/{_repo(repo)}/issues/{int(number)}/comments", body={"body": body})
        return f"Commented: {c.get('html_url')}"

    o = {"type": "object"}
    return [
        Tool("github__search", "Search GitHub issues and pull requests with GitHub search syntax, e.g. "
             "'repo:owner/name is:open label:bug' or 'is:pr author:@me'.",
             {**o, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
             _safe(search)),
        Tool("github__my_work", "The user's own open GitHub work: kind = assigned (default), review_requests, created or mentioned.",
             {**o, "properties": {"kind": {"type": "string", "enum": ["assigned", "review_requests", "created", "mentioned"]}}},
             _safe(my_work)),
        Tool("github__get_issue", "Read an issue or pull request with its latest comments. repo = owner/name.",
             {**o, "properties": {"repo": {"type": "string"}, "number": {"type": "integer"}}, "required": ["repo", "number"]},
             _safe(get_issue)),
        Tool("github__create_issue", "Open a new issue in a repository. Requires the user's approval.",
             {**o, "properties": {"repo": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}},
              "required": ["repo", "title"]}, _safe(create_issue)),
        Tool("github__comment", "Comment on an issue or pull request. Requires the user's approval.",
             {**o, "properties": {"repo": {"type": "string"}, "number": {"type": "integer"}, "body": {"type": "string"}},
              "required": ["repo", "number", "body"]}, _safe(comment)),
    ]


# ------------------------------------------------------------------ notion

def _rich(text_items) -> str:
    return "".join(t.get("plain_text", "") for t in text_items or [])


def notion_block_text(b: dict) -> str:
    t = b.get("type", "")
    val = b.get(t, {}) if isinstance(b.get(t), dict) else {}
    text = _rich(val.get("rich_text"))
    prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ",
              "numbered_list_item": "1. ", "to_do": "[x] " if val.get("checked") else "[ ] ", "quote": "> "}.get(t, "")
    return (prefix + text) if text else ""


def _title_of(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _rich(prop.get("title")) or "Untitled"
    return _rich(page.get("title")) or "Untitled"


def make_notion_tools(user_id: str) -> list[Tool]:
    async def nt(method, path, **kw):
        return await _call(user_id, "notion", method, path, headers={"Notion-Version": NOTION_VERSION}, **kw)

    async def search(query: str = "", max_results: int = 10):
        d = await nt("POST", "/v1/search", body={"query": query, "page_size": max(1, min(int(max_results or 10), 25)),
                                                 "sort": {"direction": "descending", "timestamp": "last_edited_time"}})
        rows = [{"id": r.get("id"), "title": _title_of(r), "type": r.get("object"), "url": r.get("url"),
                 "edited": (r.get("last_edited_time") or "")[:10]} for r in d.get("results", [])]
        if not rows:
            return "Nothing found in Notion" + (f" for {query!r}" if query else "") + \
                   " (pages must be shared with the Hangul integration in Notion)."
        return ToolOutput("\n".join(f"[{r['id']}] {r['title']} ({r['type']}, edited {r['edited']})" for r in rows),
                          {"kind": "notion_results", "items": rows})

    async def read_page(page_id: str):
        page = await nt("GET", f"/v1/pages/{page_id}")
        blocks = await nt("GET", f"/v1/blocks/{page_id}/children", query={"page_size": "100"})
        body = "\n".join(x for x in (notion_block_text(b) for b in blocks.get("results", [])) if x)
        return f"{_title_of(page)} — {page.get('url', '')}\n\n{body}"[:MAX_TEXT]

    def paragraphs(text: str) -> list[dict]:
        out = []
        for line in [x for x in text.splitlines() if x.strip()][:100]:
            kind, s = "paragraph", line.strip()
            if s.startswith(("- ", "* ")):
                kind, s = "bulleted_list_item", s[2:]
            elif s.startswith("# "):
                kind, s = "heading_2", s[2:]
            out.append({"object": "block", "type": kind, kind: {"rich_text": [{"type": "text", "text": {"content": s[:2000]}}]}})
        return out

    async def append(page_id: str, text: str):
        await nt("PATCH", f"/v1/blocks/{page_id}/children", body={"children": paragraphs(text)})
        return f"Added {len(paragraphs(text))} block(s) to the page."

    async def create_page(parent_page_id: str, title: str, content: str = ""):
        p = await nt("POST", "/v1/pages", body={"parent": {"page_id": parent_page_id},
                                               "properties": {"title": {"title": [{"text": {"content": title[:200]}}]}},
                                               "children": paragraphs(content)})
        return f"Created Notion page '{title}': {p.get('url')}"

    o = {"type": "object"}
    return [
        Tool("notion__search", "Search the user's Notion pages and databases by title (only pages shared with the integration).",
             {**o, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}}, _safe(search)),
        Tool("notion__read_page", "Read a Notion page's text by page id (from notion__search).",
             {**o, "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}, _safe(read_page)),
        Tool("notion__append_to_page", "Add text to the end of a Notion page (lines; '- ' bullets, '# ' headings). Requires the user's approval.",
             {**o, "properties": {"page_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["page_id", "text"]},
             _safe(append)),
        Tool("notion__create_page", "Create a Notion page under a parent page. Requires the user's approval.",
             {**o, "properties": {"parent_page_id": {"type": "string"}, "title": {"type": "string"}, "content": {"type": "string"}},
              "required": ["parent_page_id", "title"]}, _safe(create_page)),
    ]


# ------------------------------------------------------------------- slack

def make_slack_tools(user_id: str) -> list[Tool]:
    async def sl(method, path, **kw):
        return await _call(user_id, "slack", method, path, **kw)

    async def search(query: str, max_results: int = 10):
        d = await sl("GET", "/api/search.messages", query={"query": query, "count": str(max(1, min(int(max_results or 10), 30))),
                                                           "sort": "timestamp"})
        hits = d.get("messages", {}).get("matches", [])
        if not hits:
            return f"No Slack messages match {query!r}."
        rows = [{"channel": m.get("channel", {}).get("name"), "user": m.get("username") or m.get("user"),
                 "text": (m.get("text") or "")[:400], "link": m.get("permalink")} for m in hits]
        return ToolOutput("\n".join(f"#{r['channel']} · {r['user']}: {r['text']}" for r in rows),
                          {"kind": "slack_messages", "items": rows})

    async def channels():
        d = await sl("GET", "/api/conversations.list", query={"types": "public_channel,private_channel",
                                                              "exclude_archived": "true", "limit": "200"})
        chans = [f"{c.get('id')} #{c.get('name')}" for c in d.get("channels", []) if c.get("is_member")]
        return "Channels you're in:\n" + "\n".join(chans[:100]) if chans else "You aren't in any channels."

    async def read_channel(channel_id: str, limit: int = 20):
        d = await sl("GET", "/api/conversations.history", query={"channel": channel_id, "limit": str(max(1, min(int(limit or 20), 50)))})
        msgs = list(reversed(d.get("messages", [])))
        return "\n".join(f"{m.get('user', m.get('username', '?'))}: {(m.get('text') or '')[:500]}" for m in msgs)[:MAX_TEXT] or "No messages."

    async def send(channel_id: str, text: str):
        d = await sl("POST", "/api/chat.postMessage", body={"channel": channel_id, "text": text[:3500]})
        return f"Sent to {d.get('channel', channel_id)}."

    o = {"type": "object"}
    return [
        Tool("slack__search_messages", "Search the user's Slack messages (Slack search syntax: 'in:#general from:@ana budget').",
             {**o, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
             _safe(search)),
        Tool("slack__list_channels", "List the Slack channels the user is in, with their ids.", {**o, "properties": {}}, _safe(channels)),
        Tool("slack__read_channel", "Read the latest messages in a Slack channel by id (from slack__list_channels).",
             {**o, "properties": {"channel_id": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["channel_id"]},
             _safe(read_channel)),
        Tool("slack__send_message", "Post a message to a Slack channel by id, as the user. Requires the user's approval.",
             {**o, "properties": {"channel_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel_id", "text"]},
             _safe(send)),
    ]


APP_FACTORIES = {"github": make_github_tools, "notion": make_notion_tools, "slack": make_slack_tools}
