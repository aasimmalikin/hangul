"""GitHub, Notion and Slack connectors (Pro plan), all through the token vault.

The user pastes a token once (``POST /integrations/{github,notion,slack}``);
it is stored encrypted and every call goes through ``vault.call`` -- the only
place it is decrypted -- so the model, the tools and the logs never see it.
Reads run freely; anything that posts, creates or comments is tier
DESTRUCTIVE (an approval card) and in ``guard.OUTBOUND``-style step-up via the
side-effect prefixes. Each tool returns text the model can act on, including
"connect it at /vault" when there is no token.
"""

import asyncio
import base64
import json
import re
from collections.abc import Awaitable, Callable
from urllib.parse import quote

from harness.tools.base import Tool, ToolOutput

NOTION_VERSION = "2022-06-28"
MAX_TEXT = 12_000
TYPED_QUERY = re.compile(r"(?<!\S)(is|type):(issue|pr|pull-request)\b", re.IGNORECASE)


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
    if provider == "github" and resp.status in (403, 404, 422):
        plain = _github_error(resp.status, resp.body or "")   # the reason can sit in errors[], not message
        if plain:
            raise AppError(plain)
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
    """owner/name, also from a github.com link ("https://github.com/o/r/issues/5" -> "o/r")."""
    repo = re.sub(r"^(https?://)?(www\.)?github\.com/", "", repo.strip(), flags=re.IGNORECASE).split("#")[0]
    parts = [p for p in repo.split("/") if p]
    if len(parts) < 2 or (len(parts) > 2 and "://" in repo):
        raise AppError("Give the repository as owner/name, e.g. 'octocat/hello-world'.")
    if len(parts) > 2 and parts[2] not in ("issues", "pull", "pulls", "blob", "tree", "actions", "commit"):
        raise AppError("Give the repository as owner/name, e.g. 'octocat/hello-world'.")
    return f"{parts[0]}/{parts[1]}"


def _github_error(status: int, body: str) -> str | None:
    """A plain reason for GitHub's commonest refusals, so the model can tell the user what to change."""
    m = body.lower()
    if status == 422 and "cannot be searched" in m:
        return ("GITHUB_NO_ACCESS: GitHub won't search that repository with the user's token -- it doesn't exist, "
                "or the token doesn't cover it (fine-grained tokens only see the repositories picked when the "
                "token was made). Tell the user; a new token with that repository fixes it.")
    if status == 404:
        return ("github: not found (404) -- it doesn't exist, or the user's token can't see it (fine-grained "
                "tokens only see the repositories picked when the token was made).")
    if status == 403 and "rate limit" in m:
        return "github: GitHub's rate limit was hit. Do not retry now; tell the user to try again in a few minutes."
    if status == 403 and "not accessible" in m:
        return ("github: the token doesn't have permission for that (403). Tell the user which permission it needs "
                "on their fine-grained token: Issues / Pull requests to read or write those, Contents to read files "
                "and PR changes, Commit statuses / Checks for CI.")
    return None


# ------------------------------------------------------------------ github

MY_WORK = {"assigned": ("Assigned to you", "is:open assignee:@me"),
           "review_requests": ("Waiting for your review", "is:open is:pr review-requested:@me"),
           "created": ("Opened by you", "is:open author:@me"),
           "mentioned": ("Mentioning you", "is:open mentions:@me")}
WAITING_ON_ME = ("review_requests", "assigned", "mentioned")
MAX_PATCH = 3_000          # per file, in pr_changes
FAILED = ("failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale")


def make_github_tools(user_id: str) -> list[Tool]:
    login: list[str] = []          # the token's GitHub username, looked up once per run

    async def gh(method, path, **kw):
        return await _call(user_id, "github", method, path,
                           headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, **kw)

    async def whoami() -> str:
        if not login:
            login.append((await gh("GET", "/user")).get("login") or "")
        return login[0]

    def issue_rows(items):
        return [{"repo": i.get("repository_url", "").split("/repos/")[-1], "number": i.get("number"),
                 "title": i.get("title"), "state": i.get("state"), "url": i.get("html_url"),
                 "pr": "pull_request" in i, "updated": (i.get("updated_at") or "")[:10]} for i in items]

    def line(r):
        return f"{r['repo']}#{r['number']} [{r['state']}{' PR' if r['pr'] else ''}] {r['title']} — {r['url']}"

    async def find(query: str, n: int) -> list[dict]:
        # GitHub's search API now answers 422 unless the query says is:issue or is:pull-request
        # (authenticated calls); when it names neither, search both and merge, newest first.
        if TYPED_QUERY.search(query):
            items = (await gh("GET", "/search/issues", query={"q": query, "per_page": str(n)})).get("items", [])
        else:
            issues, prs = await asyncio.gather(
                gh("GET", "/search/issues", query={"q": f"{query} is:issue", "per_page": str(n)}),
                gh("GET", "/search/issues", query={"q": f"{query} is:pull-request", "per_page": str(n)}))
            items = sorted(issues.get("items", []) + prs.get("items", []),
                           key=lambda i: i.get("updated_at") or "", reverse=True)[:n]
        return issue_rows(items)

    async def search(query: str, max_results: int = 10):
        rows = await find(query, max(1, min(int(max_results or 10), 30)))
        if not rows:
            return f"No issues or pull requests match {query!r}."
        return ToolOutput("\n".join(line(r) for r in rows), {"kind": "issues", "items": rows})

    async def my_work(kind: str = "all"):
        if kind == "repos":
            me = await whoami()
            rows = await find(f"user:{me} is:open", 20)
            if not rows:
                return f"Nothing is open in the repositories {me} owns."
            return ToolOutput(f"Open in repositories {me} owns:\n" + "\n".join(line(r) for r in rows),
                              {"kind": "issues", "items": rows})
        kinds = WAITING_ON_ME if kind not in MY_WORK else (kind,)
        found = await asyncio.gather(*(find(MY_WORK[k][1], 20) for k in kinds), return_exceptions=True)
        sections, rows, seen, failed = [], [], set(), []
        for k, got in zip(kinds, found):
            label, q = MY_WORK[k]
            if isinstance(got, BaseException):
                failed.append(f"{label.lower()}: {got}")
                continue
            fresh = [r for r in got if r["url"] not in seen]
            seen.update(r["url"] for r in fresh)
            rows += fresh
            sections.append(f"{label} ({q}): " + ("none" if not got else
                            "\n" + "\n".join(line(r) for r in got)))
        text = "\n".join(sections)
        if failed:
            text += "\nCould not check -- " + "; ".join(failed)
        if not rows:
            return text
        return ToolOutput(text, {"kind": "issues", "items": rows})

    async def get_issue(repo: str, number: int):
        r = _repo(repo)
        i = await gh("GET", f"/repos/{r}/issues/{int(number)}")
        comments = await gh("GET", f"/repos/{r}/issues/{int(number)}/comments", query={"per_page": "10"})
        lines = [f"{r}#{number} [{i.get('state')}] {i.get('title')}", f"by {i.get('user', {}).get('login')} · {i.get('html_url')}",
                 (i.get("body") or "")[:4000]]
        for c in comments if isinstance(comments, list) else []:
            lines.append(f"--- {c.get('user', {}).get('login')}: {(c.get('body') or '')[:1500]}")
        return "\n".join(lines)[:MAX_TEXT]

    async def read_file(repo: str, path: str = "", ref: str = ""):
        r = _repo(repo)
        q = {"ref": ref} if ref else None
        clean = path.strip().strip("/")
        d = await gh("GET", f"/repos/{r}/contents/{quote(clean)}" if clean else f"/repos/{r}/readme", query=q)
        if isinstance(d, list):
            entries = sorted(d, key=lambda e: (e.get("type") != "dir", e.get("name", "")))
            return f"{r}/{clean or ''} (folder):\n" + "\n".join(
                f"{e.get('name')}{'/' if e.get('type') == 'dir' else ''}" for e in entries)[:MAX_TEXT]
        name, url = d.get("path") or clean, d.get("html_url", "")
        if d.get("type") != "file" or d.get("encoding") != "base64" or not d.get("content"):
            return f"{r}/{name} can't be shown here (too large or not a regular file): {url}"
        try:
            text = base64.b64decode(d["content"]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return f"{r}/{name} is a binary file: {url}"
        more = f"\n…[truncated; full file: {url}]" if len(text) > MAX_TEXT else ""
        return f"{r}/{name} ({url})\n{text[:MAX_TEXT]}{more}"

    async def pr(r: str, number: int) -> dict:
        try:
            return await gh("GET", f"/repos/{r}/pulls/{int(number)}")
        except AppError as e:
            if "404" in str(e):
                raise AppError(f"{r}#{number} is not a pull request, or the token can't see it.") from e
            raise

    async def pr_changes(repo: str, number: int):
        r = _repo(repo)
        p = await pr(r, number)
        files = await gh("GET", f"/repos/{r}/pulls/{int(number)}/files", query={"per_page": "100"})
        state = "merged" if p.get("merged") else ("draft" if p.get("draft") else p.get("state"))
        out = [f"{r}#{number} [{state}] {p.get('title')} — {p.get('html_url')}",
               (f"{p.get('head', {}).get('ref')} → {p.get('base', {}).get('ref')} · {p.get('changed_files')} files, "
                f"+{p.get('additions')} −{p.get('deletions')}")]
        for f in files if isinstance(files, list) else []:
            out.append(f"\n=== {f.get('status')} {f.get('filename')} (+{f.get('additions')} −{f.get('deletions')})")
            patch = f.get("patch")
            out.append(patch[:MAX_PATCH] + ("\n…[patch truncated]" if len(patch) > MAX_PATCH else "")
                       if patch else "(no text diff: binary or too large)")
        text = "\n".join(out)
        return text[:MAX_TEXT] + ("\n…[more changes not shown]" if len(text) > MAX_TEXT else "")

    async def checks(repo: str, number: int):
        r = _repo(repo)
        p = await pr(r, number)
        sha = (p.get("head") or {}).get("sha", "")
        runs, status = await asyncio.gather(
            gh("GET", f"/repos/{r}/commits/{sha}/check-runs", query={"per_page": "100"}),
            gh("GET", f"/repos/{r}/commits/{sha}/status"), return_exceptions=True)
        items = []   # (name, state, link) with state = passed / failed / running / skipped
        if not isinstance(runs, BaseException):
            for c in runs.get("check_runs", []):
                concl = c.get("conclusion")
                st = ("running" if c.get("status") != "completed" else "failed" if concl in FAILED
                      else "skipped" if concl in ("skipped", "neutral") else "passed")
                items.append((c.get("name"), st, c.get("details_url") or c.get("html_url") or ""))
        if not isinstance(status, BaseException):
            for c in status.get("statuses", []):
                st = {"success": "passed", "pending": "running"}.get(c.get("state"), "failed")
                items.append((c.get("context"), st, c.get("target_url") or ""))
        if not items:
            if isinstance(runs, BaseException) and isinstance(status, BaseException):
                raise runs
            return f"{r}#{number}: no CI checks reported for the latest commit ({sha[:7]})."
        count = {s: sum(1 for _, st, _ in items if st == s) for s in ("passed", "failed", "running", "skipped")}
        verdict = "failing" if count["failed"] else "still running" if count["running"] else "passing"
        out = [f"{r}#{number} CI is {verdict} on {sha[:7]}: " + ", ".join(f"{v} {k}" for k, v in count.items() if v)]
        out += [f"- {st}: {name} {link}".rstrip() for name, st, link in items if st in ("failed", "running")]
        if isinstance(runs, BaseException):
            out.append(f"(check runs not readable: {runs})")
        return "\n".join(out)

    async def create_issue(repo: str, title: str, body: str = ""):
        i = await gh("POST", f"/repos/{_repo(repo)}/issues", body={"title": title, "body": body})
        return f"Created {_repo(repo)}#{i.get('number')}: {i.get('html_url')}"

    async def comment(repo: str, number: int, body: str):
        c = await gh("POST", f"/repos/{_repo(repo)}/issues/{int(number)}/comments", body={"body": body})
        return f"Commented: {c.get('html_url')}"

    o = {"type": "object"}
    repo_desc = ("owner/name or a github.com link. If the user hasn't said which repository, ask them "
                 "(ask_user) -- never guess one.")
    repo_num = {**o, "properties": {"repo": {"type": "string", "description": repo_desc},
                                    "number": {"type": "integer"}}, "required": ["repo", "number"]}
    return [
        Tool("github__search", "Search GitHub issues and pull requests with GitHub search syntax, e.g. "
             "'repo:owner/name is:open label:bug' or 'is:pr author:@me'.",
             {**o, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]},
             _safe(search)),
        Tool("github__my_work", "The user's own open GitHub work. kind = all (default: review requests, assigned "
             "and mentions together -- use for 'what's waiting on me'), review_requests, assigned, created, "
             "mentioned, or repos (everything open in repositories the user owns -- 'my repo').",
             {**o, "properties": {"kind": {"type": "string", "enum": ["all", *MY_WORK, "repos"]}}},
             _safe(my_work)),
        Tool("github__get_issue", "Read an issue or pull request's description and latest comments. "
             "Use this (not read_webpage) for github.com issue and PR links.", repo_num, _safe(get_issue)),
        Tool("github__pr_changes", "A pull request's changed files with their diffs (code review).", repo_num,
             _safe(pr_changes)),
        Tool("github__checks", "Whether a pull request's CI passed: check runs and statuses on its latest commit.",
             repo_num, _safe(checks)),
        Tool("github__read_file", "Read a file or list a folder in a repository; no path = the README. "
             "ref = branch, tag or commit (default branch if empty).",
             {**o, "properties": {"repo": {"type": "string", "description": repo_desc}, "path": {"type": "string"},
                                  "ref": {"type": "string"}},
              "required": ["repo"]}, _safe(read_file)),
        Tool("github__create_issue", "Open a new issue in a repository. The user approves it on a card before it runs, so call it when asked.",
             {**o, "properties": {"repo": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}},
              "required": ["repo", "title"]}, _safe(create_issue)),
        Tool("github__comment", "Comment on an issue or pull request. The user approves it on a card before it runs, so call it when asked.",
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
        Tool("notion__append_to_page", "Add text to the end of a Notion page (lines; '- ' bullets, '# ' headings). The user approves it on a card before it runs, so call it when asked.",
             {**o, "properties": {"page_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["page_id", "text"]},
             _safe(append)),
        Tool("notion__create_page", "Create a Notion page under a parent page. The user approves it on a card before it runs, so call it when asked.",
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
        Tool("slack__send_message", "Post a message to a Slack channel by id, as the user. The user approves it on a card before it runs, so call it when asked.",
             {**o, "properties": {"channel_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel_id", "text"]},
             _safe(send)),
    ]


APP_FACTORIES = {"github": make_github_tools, "notion": make_notion_tools, "slack": make_slack_tools}
