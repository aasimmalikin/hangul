"""The Research connector: arXiv over its public Atom API.

Built in rather than an MCP subprocess on purpose: arXiv needs no credential,
the API is a single GET, and doing it here keeps the 3-second courtesy rate
limit under our control and the papers off the server's disk."""

import asyncio
import re
import time
import xml.etree.ElementTree as ET

import httpx

from harness.logging import log
from harness.tools.base import Tool

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
MIN_INTERVAL_S = 3.0          # arXiv asks for no more than one request every 3 seconds
MAX_RESULTS = 10
ABSTRACT_CHARS = 1200
USER_AGENT = "hangul-harness/1.0 (research connector)"

_lock = asyncio.Lock()
_last_call = 0.0
_ID_RE = re.compile(r"(\d{4}\.\d{4,5}(v\d+)?|[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)")


async def _get(params: dict, http: httpx.AsyncClient | None = None) -> str:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        client = http or httpx.AsyncClient(timeout=20.0, headers={"User-Agent": USER_AGENT})
        try:
            r = await client.get(API, params=params)
        finally:
            _last_call = time.monotonic()
            if http is None:
                await client.aclose()
    r.raise_for_status()
    return r.text


def _text(el, path: str) -> str:
    n = el.find(path, NS)
    return " ".join((n.text or "").split()) if n is not None else ""


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        raw_id = _text(e, "a:id")
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1]
        pdf = next((link.get("href") for link in e.findall("a:link", NS) if link.get("title") == "pdf"), "")
        doi = _text(e, "arxiv:doi")
        out.append({
            "id": arxiv_id,
            "title": _text(e, "a:title"),
            "authors": [_text(a, "a:name") for a in e.findall("a:author", NS)],
            "published": _text(e, "a:published")[:10],
            "updated": _text(e, "a:updated")[:10],
            "summary": _text(e, "a:summary"),
            "categories": [c.get("term") for c in e.findall("a:category", NS) if c.get("term")],
            "pdf": pdf,
            "doi": doi,
            "url": raw_id,
        })
    return out


def format_results(papers: list[dict], *, full_abstract: bool = False) -> str:
    if not papers:
        return "No arXiv results."
    parts = []
    for p in papers:
        summary = p["summary"] if full_abstract else p["summary"][:ABSTRACT_CHARS] + ("…" if len(p["summary"]) > ABSTRACT_CHARS else "")
        authors = ", ".join(p["authors"][:5]) + (" et al." if len(p["authors"]) > 5 else "")
        parts.append(
            f"[{p['id']}] {p['title']}\n"
            f"  {authors} · {p['published']} · {', '.join(p['categories'][:4])}\n"
            f"  {p['url']}" + (f" · doi:{p['doi']}" if p["doi"] else "") + "\n"
            f"  {summary}"
        )
    return "\n\n".join(parts)


def make_arxiv_tools(http: httpx.AsyncClient | None = None) -> list[Tool]:
    async def arxiv_search(query: str, max_results: int = 5, sort: str = "relevance", category: str | None = None) -> str:
        q = query.strip()
        if not q:
            return "ARXIV_ERROR: empty query"
        # bare words search every field; fielded syntax (ti:, au:, ...) passes through
        if not re.search(r"\b(all|ti|au|abs|co|jr|cat|rn|id):", q):
            q = f"all:{q}"
        if category:
            q = f"({q}) AND cat:{category.strip()}"
        params = {
            "search_query": q,
            "start": 0,
            "max_results": max(1, min(int(max_results or 5), MAX_RESULTS)),
            "sortBy": "submittedDate" if sort == "date" else "relevance",
            "sortOrder": "descending",
        }
        try:
            papers = parse_feed(await _get(params, http))
        except (httpx.HTTPError, ET.ParseError) as e:
            log.warning("arxiv search failed", error=str(e))
            return f"ARXIV_UNAVAILABLE: arXiv could not be reached ({type(e).__name__}). Do not retry now."
        return format_results(papers)

    async def arxiv_paper(arxiv_id: str) -> str:
        m = _ID_RE.search(arxiv_id or "")
        if not m:
            return "ARXIV_ERROR: that does not look like an arXiv id (e.g. 2310.06825 or hep-th/9901001)"
        try:
            papers = parse_feed(await _get({"id_list": m.group(1), "max_results": 1}, http))
        except (httpx.HTTPError, ET.ParseError) as e:
            log.warning("arxiv fetch failed", error=str(e))
            return f"ARXIV_UNAVAILABLE: arXiv could not be reached ({type(e).__name__}). Do not retry now."
        if not papers:
            return f"No arXiv paper with id {m.group(1)}."
        return format_results(papers, full_abstract=True)

    return [
        Tool(
            name="arxiv_search",
            description=(
                "Search arXiv for research papers. Use for literature questions: papers on a topic, "
                "recent work in a field, who proposed a method. Returns id, title, authors, date, "
                "categories, link and abstract. Cite papers by arXiv id. Supports arXiv query syntax "
                "(ti:, au:, abs:, cat:) in `query`."
            ),
            parameter={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
                    "sort": {"type": "string", "enum": ["relevance", "date"]},
                    "category": {"type": "string", "description": "e.g. cs.CL, cs.LG, stat.ML"},
                },
                "required": ["query"],
            },
            handler=arxiv_search,
        ),
        Tool(
            name="arxiv_paper",
            description="Fetch one arXiv paper's full metadata and abstract by id (e.g. 2310.06825).",
            parameter={"type": "object", "properties": {"arxiv_id": {"type": "string"}}, "required": ["arxiv_id"]},
            handler=arxiv_paper,
        ),
    ]
