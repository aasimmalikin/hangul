"""Policy for one proxied call. Everything that can be checked without
touching the network is checked here, before the credential is decrypted."""

from dataclasses import dataclass
from typing import Literal

from harness.vault.providers import READ_METHODS, WRITE_METHODS, ProviderSpec

Access = Literal["read", "write"]


@dataclass(frozen=True)
class GrantScope:
    """What a grant is allowed to do. Stored with the grant, enforced here.
    ``access="read"`` permits whatever the provider spec classifies as a read
    (GET/HEAD, plus POST on declared search-style paths); ``"write"`` permits
    everything the spec allows."""
    provider: str
    access: Access
    subject: str                        # user id or "system"
    thread_id: str | None = None


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""

    @classmethod
    def deny(cls, reason: str) -> "Verdict":
        return cls(False, reason)

    @classmethod
    def ok(cls) -> "Verdict":
        return cls(True)


ALLOWED_METHODS = READ_METHODS + WRITE_METHODS


class VaultPolicy:
    def __init__(self, max_body_bytes: int = 1_000_000) -> None:
        self.max_body_bytes = max_body_bytes

    def check(self, scope: GrantScope, spec: ProviderSpec, method: str, path: str,
              body_len: int = 0, calls_left: int = 1) -> Verdict:
        m = method.upper()
        if scope.provider != spec.name:
            return Verdict.deny(f"grant is for {scope.provider!r}, not {spec.name!r}")
        if m not in ALLOWED_METHODS:
            return Verdict.deny(f"method {m} not supported")
        if not path.startswith("/") or ".." in path.split("/") or "://" in path:
            return Verdict.deny("path must be relative to the provider base url")
        if not spec.path_allowed(path):
            return Verdict.deny(f"path {path!r} not allowed for {spec.name}")
        if spec.classify(m, path) == "write" and scope.access != "write":
            return Verdict.deny(f"{m} {path} is a write; this grant is read-only")
        if body_len > self.max_body_bytes:
            return Verdict.deny(f"body exceeds {self.max_body_bytes} bytes")
        if calls_left <= 0:
            return Verdict.deny("grant call budget exhausted")
        return Verdict.ok()
