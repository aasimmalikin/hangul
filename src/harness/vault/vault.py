"""The vault facade: everything the routes, tools and MCP manager call."""

import asyncio
from datetime import datetime, timedelta

import httpx

from harness.logging import log
from harness.vault.crypto import Cipher, fingerprint
from harness.vault.grants import Grant, GrantError, GrantStore
from harness.vault.policy import GrantScope, VaultPolicy
from harness.vault.providers import ProviderSpec, generic_spec, get_spec
from harness.vault.proxy import ProxyError, ProxyResponse, proxy_request
from harness.vault.redact import Redactor
from harness.vault.redact import redactor as default_redactor
from harness.vault.store import ConsentRecord, ConsentStore, CredentialRecord, CredentialStore

SYSTEM = "system"
# providers whose operator (system) credential the agent may use for any signed-in
# user without an explicit consent row -- this keeps web_search working as before
AUTO_CONSENT_PROVIDERS: frozenset[str] = frozenset({"tavily"})


class VaultError(Exception):
    """A policy / consent / grant problem the caller should show as text."""


class VaultUnavailable(VaultError):
    """Vault is disabled (no master key) or its store is down."""


class Vault:
    def __init__(
        self,
        *,
        cipher: Cipher,
        credentials: CredentialStore,
        consents: ConsentStore,
        grants: GrantStore,
        policy: VaultPolicy | None = None,
        redactor: Redactor | None = None,
        http: httpx.AsyncClient | None = None,
        grant_ttl_s: int = 300,
        proxy_timeout_s: float = 30.0,
        max_body_bytes: int = 1_000_000,
        public_url: str = "http://127.0.0.1:8000",
        audit=None,
    ) -> None:
        self.cipher = cipher
        self.credentials = credentials
        self.consents = consents
        self.grants = grants
        self.policy = policy or VaultPolicy(max_body_bytes=max_body_bytes)
        self.redactor = redactor or default_redactor
        self.http = http or httpx.AsyncClient(timeout=proxy_timeout_s, follow_redirects=False)
        self.grant_ttl_s = grant_ttl_s
        self.max_body_bytes = max_body_bytes
        self.public_url = public_url.rstrip("/")
        self.audit = audit
        # provider name -> spec for generic credentials added with a base url
        self._custom_specs: dict[str, ProviderSpec] = {}

    async def aclose(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------ providers

    def spec(self, provider: str) -> ProviderSpec:
        s = self._custom_specs.get(provider) or get_spec(provider)
        if s is None:
            raise VaultError(f"unknown provider {provider!r}")
        return s

    def providers(self) -> list[ProviderSpec]:
        from harness.vault.providers import BUILTIN
        return list(BUILTIN.values()) + list(self._custom_specs.values())

    # ---------------------------------------------------------- credentials

    async def add_credential(self, *, user_id: str | None, provider: str, secret: str, label: str = "",
                             kind: str = "api_key", base_url: str | None = None,
                             expires_at: datetime | None = None) -> CredentialRecord:
        if not secret or len(secret) < 8:
            raise VaultError("secret is too short")
        if base_url:
            spec = generic_spec(base_url)
            provider = spec.name
            self._custom_specs[provider] = spec
        else:
            self.spec(provider)  # validates
        fp = fingerprint(secret)
        existing = await asyncio.to_thread(self.credentials.find_by_fingerprint, user_id, provider, fp)
        if existing is not None and existing.usable:
            return existing
        rec = await asyncio.to_thread(
            self.credentials.add, user_id=user_id, provider=provider, label=label, kind=kind,
            ciphertext=self.cipher.encrypt(secret), fingerprint=fp, expires_at=expires_at,
        )
        self.redactor.register(secret, provider)
        log.info("vault credential added", provider=provider, user_id=user_id, fingerprint=fp)
        return rec

    async def import_system_credential(self, provider: str, secret: str | None, label: str = "from .env") -> None:
        """Idempotently vault an operator key from settings at startup."""
        if not secret:
            return
        try:
            existing = await asyncio.to_thread(self.credentials.find, None, provider)
            if existing is not None:
                try:
                    self.cipher.decrypt(existing.ciphertext)
                except ValueError:
                    # encrypted under a previous master key: it can never be used again
                    log.warning("vault system credential re-encrypted under the current master key",
                                provider=provider, credential=existing.id)
                    await asyncio.to_thread(self.credentials.revoke, None, existing.id)
            await self.add_credential(user_id=None, provider=provider, secret=secret, label=label)
        except Exception as e:  # noqa: BLE001 - a DB hiccup must not block boot
            log.warning("vault system credential import failed", provider=provider, error=str(e))

    async def list_credentials(self, user_id: str) -> list[CredentialRecord]:
        return await asyncio.to_thread(self.credentials.list_for_user, user_id, True)

    async def revoke_credential(self, user_id: str, credential_id: int) -> bool:
        ok = await asyncio.to_thread(self.credentials.revoke, user_id, credential_id)
        if ok:
            await self.grants.revoke_credential(credential_id)
            await asyncio.to_thread(self.consents.revoke_for_credential, credential_id)
        return ok

    def has_system_credential(self, provider: str) -> bool:
        return self.credentials.find(None, provider) is not None

    # -------------------------------------------------------------- consent

    async def grant_consent(self, *, user_id: str, provider: str, ttl: timedelta,
                            allow_write: bool = False) -> ConsentRecord:
        self.spec(provider)
        cred = await asyncio.to_thread(self._pick_credential, user_id, provider)
        if cred is None:
            raise VaultError(f"no credential for {provider!r}: add one first")
        return await asyncio.to_thread(self.consents.grant, user_id=user_id, provider=provider,
                                       credential_id=cred.id, ttl=ttl, allow_write=allow_write)

    async def list_consents(self, user_id: str) -> list[ConsentRecord]:
        return await asyncio.to_thread(self.consents.list_for_user, user_id, True)

    async def revoke_consent(self, user_id: str, consent_id: int) -> bool:
        return await asyncio.to_thread(self.consents.revoke, user_id, consent_id)

    async def consented_providers(self, user_id: str) -> dict[str, bool]:
        """provider -> allow_write, for every provider the user may use now."""
        out: dict[str, bool] = {}
        for c in await asyncio.to_thread(self.consents.list_for_user, user_id):
            out.setdefault(c.provider, False)
            out[c.provider] = out[c.provider] or c.allow_write
        for p in AUTO_CONSENT_PROVIDERS:
            if p not in out and await asyncio.to_thread(self.credentials.find, None, p):
                out[p] = False
        return out

    # --------------------------------------------------------------- grants

    def _pick_credential(self, subject: str, provider: str) -> CredentialRecord | None:
        """The user's own credential wins; system is the fallback. The system
        subject can only use system credentials."""
        if subject != SYSTEM:
            own = self.credentials.find(subject, provider)
            if own is not None:
                return own
        return self.credentials.find(None, provider)

    async def mint_grant(self, *, subject: str, provider: str, thread_id: str | None = None,
                         write: bool = False, ttl_s: int | None = None) -> tuple[str, Grant]:
        spec = self.spec(provider)
        cred = await asyncio.to_thread(self._pick_credential, subject, provider)
        if cred is None:
            if subject == SYSTEM:
                raise VaultError(f"no credential available for {provider!r}")
            raise VaultError(f"VAULT_CONSENT_REQUIRED: no credential for '{provider}'. "
                             f"Ask the user to connect it at /vault.")

        if subject != SYSTEM:
            consent = await asyncio.to_thread(self.consents.active, subject, provider)
            if consent is None:
                if not (provider in AUTO_CONSENT_PROVIDERS and cred.is_system):
                    raise VaultError(f"VAULT_CONSENT_REQUIRED: the user has not allowed access to "
                                     f"'{provider}'. Ask them to connect it at /vault.")
            elif write and not consent.allow_write:
                raise VaultError(f"VAULT_CONSENT_REQUIRED: consent for '{provider}' is read-only. "
                                 f"Ask the user to allow writes at /vault.")
            if consent is not None and consent.credential_id not in (None, cred.id):
                # consent was given for a specific credential that has since been replaced
                c2 = await asyncio.to_thread(self.credentials.get, consent.credential_id)
                if c2 is not None and c2.usable:
                    cred = c2

        scope = GrantScope(provider=provider, access="write" if write else "read",
                           subject=subject, thread_id=thread_id)
        try:
            token, grant = await self.grants.mint(cred.id, scope, ttl_s=ttl_s or self.grant_ttl_s,
                                                 max_calls=spec.max_calls_per_grant)
        except GrantError as e:
            raise VaultUnavailable(str(e)) from e
        self.redactor.register(token, "grant")
        log.info("vault grant minted", subject=subject, provider=provider, thread_id=thread_id,
                 write=write, credential=cred.id)
        return token, grant

    async def revoke_grant(self, token: str) -> None:
        await self.grants.revoke(token)
        self.redactor.forget(token)

    # ---------------------------------------------------------------- proxy

    async def proxy(self, token: str, *, method: str, path: str, headers: dict | None = None,
                    query: dict | None = None, body: bytes | str | None = None) -> ProxyResponse:
        try:
            grant = await self.grants.lookup(token)
        except GrantError as e:
            raise ProxyError(401, str(e)) from e
        spec = self.spec(grant.scope.provider)
        cred = await asyncio.to_thread(self.credentials.get, grant.credential_id)
        if cred is None:
            raise ProxyError(403, "credential no longer exists")
        return await proxy_request(
            grant=grant, credential=cred, spec=spec, cipher=self.cipher, grants=self.grants,
            policy=self.policy, redactor=self.redactor, http=self.http, method=method, path=path,
            headers=headers, query=query, body=body, max_body_bytes=self.max_body_bytes,
            audit=self.audit,
        )

    async def call(self, *, subject: str, provider: str, method: str, path: str, thread_id: str | None = None,
                   headers: dict | None = None, query: dict | None = None,
                   body: bytes | str | None = None) -> ProxyResponse:
        """Mint a one-off grant and proxy through it (in-process callers)."""
        spec = self.spec(provider)
        write = spec.classify(method, path) == "write"
        token, _ = await self.mint_grant(subject=subject, provider=provider, thread_id=thread_id, write=write)
        try:
            return await self.proxy(token, method=method, path=path, headers=headers, query=query, body=body)
        finally:
            await self.revoke_grant(token)

    # ------------------------------------------------------------------ MCP

    def proxy_url(self, provider: str) -> str:
        return f"{self.public_url}/vault/proxy/{provider}/"

    async def resolve_refs(self, values: dict[str, str] | None, *, subject: str = SYSTEM,
                           write: bool = True) -> tuple[dict[str, str] | None, list[str]]:
        """Replace ``vault:<provider>`` with a fresh grant token and
        ``vault-proxy:<provider>`` with this API's proxy URL, anywhere inside
        the string. Returns the new mapping and the tokens minted (so the
        caller can revoke them on disconnect)."""
        if not values:
            return values, []
        out: dict[str, str] = {}
        minted: list[str] = []
        for k, v in values.items():
            if "vault-proxy:" in v:
                v = _sub(v, "vault-proxy:", self.proxy_url)
            if "vault:" in v:
                async def mint(p: str) -> str:
                    token, _ = await self.mint_grant(subject=subject, provider=p, write=write)
                    minted.append(token)
                    return token
                v = await _asub(v, "vault:", mint)
            out[k] = v
        return out, minted


def _split_ref(value: str, marker: str) -> tuple[str, str, str]:
    i = value.index(marker)
    j = i + len(marker)
    k = j
    while k < len(value) and (value[k].isalnum() or value[k] in "_-.:"):
        k += 1
    return value[:i], value[j:k], value[k:]


def _sub(value: str, marker: str, fn) -> str:
    while marker in value:
        pre, name, post = _split_ref(value, marker)
        value = pre + fn(name) + post
    return value


async def _asub(value: str, marker: str, fn) -> str:
    while marker in value:
        pre, name, post = _split_ref(value, marker)
        value = pre + await fn(name) + post
    return value


__all__ = ["ProxyError", "ProxyResponse", "Vault", "VaultError", "VaultUnavailable"]
