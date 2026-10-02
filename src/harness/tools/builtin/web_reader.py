"""read_webpage: fetch one public web page and return its readable text.

``web_search`` returns snippets; this reads the whole article / docs page /
job post behind a link the user pasted. It needs no credential, so it does not
go through the vault -- but it is an outbound call, so:

* only http(s) to PUBLIC addresses: every hop of a redirect is re-resolved and
  refused if it lands on a private, loopback, link-local or reserved address
  (otherwise the agent could be steered into probing the server's own network);
* bounded: 2 MB read, 15 s, 5 redirects, text capped for the model;
* the page reaches the model spotlighted as untrusted, like every tool result,
  and the tool is in ``guard.OUTBOUND`` so a tainted run must ask first.
"""

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from harness.tools.base import Tool, ToolOutput

MAX_BYTES = 2 * 1024 * 1024
MAX_CHARS = 15_000
MAX_REDIRECTS = 5
TIMEOUT_S = 15.0
_UA = "Mozilla/5.0 (compatible; HangulAssistant/1.0; +https://hangul.app)"

_SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe", "aside", "template"}
_BLOCK = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre",
          "blockquote", "table", "ul", "ol"}


class _Text(HTMLParser):
    """Tiny readability: drop chrome (nav/footer/scripts), keep text and headings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self.parts.append("\n")
            if tag in ("h1", "h2", "h3"):
                self.parts.append("## ")
            elif tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        out, blank = [], False
        for line in lines:
            if line and line not in ("##", "-"):
                out.append(line)
                blank = False
            elif not blank and out:
                out.append("")
                blank = True
        return "\n".join(out).strip()


def html_to_text(html: str) -> tuple[str, str]:
    p = _Text()
    p.feed(html)
    return " ".join(p.title.split()), p.text()


class BlockedURL(ValueError):
    pass


def _is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise BlockedURL(f"Could not find the site {host!r}.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


async def check_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedURL("Only http(s) links can be read.")
    if parsed.username or parsed.password:
        raise BlockedURL("Links with credentials in them are not read.")
    if not await asyncio.to_thread(_is_public, parsed.hostname):
        raise BlockedURL("That address is not a public website.")
    return parsed.geturl()


async def fetch(url: str) -> tuple[str, str, str]:
    """(final url, content type, body text) with every hop checked."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False,
                                 headers={"User-Agent": _UA, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"}) as c:
        for _ in range(MAX_REDIRECTS + 1):
            url = await check_url(url)
            async with c.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                if r.status_code >= 400:
                    raise BlockedURL(f"The site answered {r.status_code}.")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and not (ctype.startswith("text/") or ctype in ("application/xhtml+xml", "application/json")):
                    raise BlockedURL(f"That link is a {ctype} file, not a web page.")
                body = b""
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                return url, ctype, body.decode(r.encoding or "utf-8", errors="replace")
    raise BlockedURL("Too many redirects.")


async def read_webpage(url: str) -> ToolOutput | str:
    try:
        final, ctype, body = await fetch(url)
    except BlockedURL as e:
        return f"Could not read that link: {e}"
    except httpx.HTTPError as e:
        return f"Could not read that link: {type(e).__name__}."
    if ctype in ("text/html", "application/xhtml+xml", ""):
        title, text = html_to_text(body)
    else:
        title, text = "", body.strip()
    if not text:
        return "The page had no readable text (it may need JavaScript or a login)."
    truncated = len(text) > MAX_CHARS
    text = text[:MAX_CHARS]
    host = urlparse(final).hostname or ""
    header = f"Title: {title}\nURL: {final}\n\n" if title else f"URL: {final}\n\n"
    return ToolOutput(header + text + ("\n\n[page truncated]" if truncated else ""),
                      {"kind": "webpage", "url": final, "title": title or host, "host": host,
                       "excerpt": text[:280]})


WEB_READER_TOOL = Tool(
    name="read_webpage",
    description=(
        "Open a public web page and read its full text. Use when the user gives a link ('summarise this "
        "article', 'what does this page say about pricing'), or to read a promising result from web_search "
        "in full. Pass the exact URL. Does not work for pages that need a login."),
    parameter={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "The full http(s) URL."}},
        "required": ["url"],
    },
    handler=read_webpage,
)
