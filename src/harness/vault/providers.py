"""What the vault knows about each third-party API: where it lives and how a
credential is injected. Specs are code, not user input, so a prompt-injected
model cannot point the proxy at a new host."""

import fnmatch
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

Inject = Literal["bearer", "header", "query", "basic"]

READ_METHODS: tuple[str, ...] = ("GET", "HEAD")
WRITE_METHODS: tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE")

GENERIC_PREFIX = "http:"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str                              # scheme+host(+prefix); proxy refuses any other host
    inject: Inject = "bearer"
    inject_name: str = "Authorization"         # header name, or query param name
    allow_paths: tuple[str, ...] = ("*",)      # fnmatch on the request path
    read_paths: tuple[str, ...] = ()           # paths where POST is still a "read" (search endpoints)
    max_calls_per_grant: int = 50
    description: str = ""

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).netloc.lower()

    def path_allowed(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pat) for pat in self.allow_paths)

    def classify(self, method: str, path: str) -> Literal["read", "write"]:
        m = method.upper()
        if m in READ_METHODS:
            return "read"
        if m == "POST" and any(fnmatch.fnmatch(path, p) for p in self.read_paths):
            return "read"
        return "write"


BUILTIN: dict[str, ProviderSpec] = {
    "tavily": ProviderSpec(
        name="tavily", base_url="https://api.tavily.com", inject="bearer",
        allow_paths=("/search", "/extract"), read_paths=("/search", "/extract"),
        description="Tavily web search",
    ),
    "github": ProviderSpec(
        name="github", base_url="https://api.github.com", inject="bearer",
        description="GitHub REST API",
    ),
}


def generic_spec(host_or_url: str) -> ProviderSpec:
    """A per-host spec for credentials added with a custom base URL. The
    provider name is ``http:<host>`` so it cannot collide with a built-in."""
    url = host_or_url if "://" in host_or_url else f"https://{host_or_url}"
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise ValueError(f"invalid base url {host_or_url!r}")
    base = f"{parts.scheme}://{parts.netloc}"
    return ProviderSpec(name=f"{GENERIC_PREFIX}{parts.netloc.lower()}", base_url=base,
                        description=f"Generic HTTP API at {parts.netloc}")


def get_spec(name: str) -> ProviderSpec | None:
    if name in BUILTIN:
        return BUILTIN[name]
    if name.startswith(GENERIC_PREFIX):
        try:
            return generic_spec(name[len(GENERIC_PREFIX):])
        except ValueError:
            return None
    return None
