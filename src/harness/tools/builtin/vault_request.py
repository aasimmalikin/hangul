"""vault_request / vault_mutate: call a third-party API through the token
vault. The model names a provider and a path; it never sees a credential or
a grant. Built per request (closure over user + thread) like the other
session-scoped tools.

Two tools rather than one so the static policy tiers can differ: reads are
SENSITIVE (run under standing consent), writes are DESTRUCTIVE (pause for
human approval every time)."""

import json

from harness.tools.base import Tool
from harness.vault import current as current_vault
from harness.vault.providers import WRITE_METHODS
from harness.vault.proxy import ProxyError
from harness.vault.vault import VaultError

MAX_RESULT_CHARS = 20_000


def _format(resp) -> str:
    body = resp.body
    if len(body) > MAX_RESULT_CHARS:
        body = body[:MAX_RESULT_CHARS] + f"\n…[truncated, {len(resp.body)} chars total]"
    return f"HTTP {resp.status}\n{body}"


def _unavailable() -> str:
    return ("VAULT_UNAVAILABLE: the token vault is not configured on this server. "
            "Do not retry; tell the user external APIs are unavailable.")


def make_vault_tools(user_id: str, thread_id: str | None, consented: dict[str, bool] | None = None) -> list[Tool]:
    consented = consented or {}
    readable = sorted(consented)
    writable = sorted(p for p, w in consented.items() if w)
    hint_r = f" Providers you may use right now: {', '.join(readable)}." if readable else \
             " The user has not connected any provider yet."
    hint_w = f" Providers with write access: {', '.join(writable)}." if writable else \
             " No provider currently allows writes."

    async def vault_request(provider: str, path: str, query: dict | None = None) -> str:
        vault = current_vault()
        if vault is None:
            return _unavailable()
        if not path.startswith("/"):
            path = "/" + path
        try:
            resp = await vault.call(subject=user_id, provider=provider, method="GET", path=path,
                                    thread_id=thread_id, query={k: str(v) for k, v in (query or {}).items()})
        except VaultError as e:
            return str(e)
        except ProxyError as e:
            return f"VAULT_DENIED ({e.status}): {e.detail}"
        return _format(resp)

    async def vault_mutate(provider: str, method: str, path: str, body: dict | str | None = None) -> str:
        vault = current_vault()
        if vault is None:
            return _unavailable()
        method = (method or "").upper()
        if method not in WRITE_METHODS:
            return f"VAULT_DENIED: vault_mutate only accepts {', '.join(WRITE_METHODS)}; use vault_request for reads."
        if not path.startswith("/"):
            path = "/" + path
        raw = json.dumps(body) if isinstance(body, dict) else (body or None)
        try:
            resp = await vault.call(subject=user_id, provider=provider, method=method, path=path,
                                    thread_id=thread_id, body=raw)
        except VaultError as e:
            return str(e)
        except ProxyError as e:
            return f"VAULT_DENIED ({e.status}): {e.detail}"
        return _format(resp)

    return [
        Tool(
            name="vault_request",
            description=(
                "Read from a third-party API on the user's behalf (GET only). The vault "
                "injects the user's credential; you never handle tokens. Give the provider "
                "name and a path relative to that API (e.g. provider='github', "
                "path='/user/repos'). If the result says VAULT_CONSENT_REQUIRED, tell the "
                "user to connect the provider at /vault and stop." + hint_r
            ),
            parameter={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "e.g. github, tavily, http:<host>"},
                    "path": {"type": "string", "description": "Path relative to the provider's API base"},
                    "query": {"type": "object", "description": "Optional query parameters",
                              "additionalProperties": {"type": "string"}},
                },
                "required": ["provider", "path"],
            },
            handler=vault_request,
        ),
        Tool(
            name="vault_mutate",
            description=(
                "Change something in a third-party API on the user's behalf (POST/PUT/PATCH/"
                "DELETE). Every call pauses for the user's explicit approval. Use only when "
                "the user asked for the change." + hint_w
            ),
            parameter={
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "method": {"type": "string", "enum": list(WRITE_METHODS)},
                    "path": {"type": "string"},
                    "body": {"type": "object", "description": "JSON body", "additionalProperties": True},
                },
                "required": ["provider", "method", "path"],
            },
            handler=vault_mutate,
        ),
    ]


async def build_vault_tools(user_id: str, thread_id: str | None) -> list[Tool]:
    """The per-request pair, with descriptions naming the providers this user
    may use now. Vault disabled -> the tools still exist (and say so when
    called), so the model's tool list is stable."""
    vault = current_vault()
    consented: dict[str, bool] = {}
    if vault is not None:
        try:
            consented = await vault.consented_providers(user_id)
        except Exception:  # noqa: BLE001 - a store hiccup must not fail the run
            consented = {}
    return make_vault_tools(user_id, thread_id, consented)
