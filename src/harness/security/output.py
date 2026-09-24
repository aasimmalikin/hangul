"""Output guard: what leaves the model must not leak or exfiltrate.

- secrets / grants: the vault redactor
- the system-prompt canary: a random token planted in the prompt; its
  appearance anywhere in output or tool arguments means the prompt leaked
- markdown image exfiltration: an image whose URL carries data to a host we
  do not know is the classic zero-click channel -- it is rendered as text
- suspicious URLs: long encoded query strings to unknown hosts are defanged
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from harness.vault.redact import redactor

MD_IMAGE = re.compile(r"!\[([^\]]*)\]\((\S+?)(?:\s+\"[^\"]*\")?\)")
URL = re.compile(r"https?://[^\s<>()\"'\]]+")
LONG_PARAM = re.compile(r"[?&#][^=&#]{1,32}=[A-Za-z0-9+/%_=-]{40,}")

# hosts whose links are ordinary in this product
ALLOWED_LINK_HOSTS = ("arxiv.org", "www.arxiv.org", "export.arxiv.org", "github.com", "api.github.com",
                      "wikipedia.org", "en.wikipedia.org", "doi.org")


def _host_ok(url: str) -> bool:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_LINK_HOSTS)


@dataclass
class OutputVerdict:
    text: str
    findings: list[str] = field(default_factory=list)
    canary_leak: bool = False
    images_removed: int = 0
    urls_defanged: int = 0

    @property
    def flagged(self) -> bool:
        return bool(self.findings)


def guard_output(text: str, *, canary: str | None = None) -> OutputVerdict:
    v = OutputVerdict(text=text or "")
    if not v.text:
        return v
    scrubbed = redactor.scrub_text(v.text)
    if scrubbed != v.text:
        v.findings.append("secret redacted from answer")
        v.text = scrubbed
    if canary and canary in v.text:
        v.text = v.text.replace(canary, "[REDACTED]")
        v.canary_leak = True
        v.findings.append("system prompt canary appeared in the answer")

    def _img(m: re.Match) -> str:
        url = m.group(2)
        if _host_ok(url) and not LONG_PARAM.search(url):
            return m.group(0)
        v.images_removed += 1
        return f"[image removed: {m.group(1) or 'external image'}]"
    v.text = MD_IMAGE.sub(_img, v.text)
    if v.images_removed:
        v.findings.append(f"{v.images_removed} external image link(s) removed (exfiltration channel)")

    def _url(m: re.Match) -> str:
        url = m.group(0)
        if LONG_PARAM.search(url) and not _host_ok(url):
            v.urls_defanged += 1
            return url.split("?", 1)[0].replace("://", "[:]//") + "?[encoded data removed]"
        return url
    v.text = URL.sub(_url, v.text)
    if v.urls_defanged:
        v.findings.append(f"{v.urls_defanged} URL(s) carrying encoded data defanged")
    return v


def scan_arguments(name: str, args: dict, *, canary: str | None = None) -> list[str]:
    """Exfiltration through tool *arguments*: a query, body or file content
    that carries a secret, the canary, or a large encoded blob leaving the
    system. Returns reasons; empty = clean."""
    from harness.security.detector import BASE64_BLOB
    reasons: list[str] = []
    flat = " ".join(str(v) for v in _walk(args))
    if not flat:
        return reasons
    if redactor.scrub_text(flat) != flat:
        reasons.append("a vault secret or grant in the arguments")
    if canary and canary in flat:
        reasons.append("the system prompt canary in the arguments")
    outbound = (name in ("web_search", "vault_request", "vault_mutate", "gmail__create_draft", "calendar__create_event",
                         "docs__append_text") or name.startswith("arxiv_"))
    if outbound:
        blob = BASE64_BLOB.search(flat)
        if blob:
            reasons.append(f"a {len(blob.group(0))}-char encoded blob in an outbound call")
        if len(flat) > 4000:
            reasons.append(f"{len(flat)} chars of arguments in an outbound call")
    return reasons


def _walk(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _walk(x)
    elif v is not None:
        yield v
