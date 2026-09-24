"""Build the process-wide Vault from settings at startup (and tear it down)."""

from harness.config import Settings
from harness.logging import log
from harness.vault import current, set_current
from harness.vault.crypto import FernetCipher
from harness.vault.grants import GrantStore
from harness.vault.store import ConsentStore, CredentialStore
from harness.vault.vault import Vault


async def build_vault(settings: Settings, audit=None) -> Vault | None:
    if not settings.vault_master_key:
        log.error("vault disabled: VAULT_MASTER_KEY is not set; web_search and vault_* tools "
                  "will report VAULT_UNAVAILABLE")
        set_current(None)
        return None
    try:
        cipher = FernetCipher(settings.vault_master_key)
    except ValueError as e:
        log.error("vault disabled: bad master key", error=str(e))
        set_current(None)
        return None

    from harness.cache.redis_client import get_redis

    vault = Vault(
        cipher=cipher,
        credentials=CredentialStore(),
        consents=ConsentStore(),
        grants=GrantStore(get_redis()),
        grant_ttl_s=settings.vault_grant_ttl_s,
        proxy_timeout_s=settings.vault_proxy_timeout_s,
        max_body_bytes=settings.vault_max_body_bytes,
        public_url=settings.vault_public_url,
        audit=audit,
    )
    set_current(vault)
    # operator keys from .env become system credentials so nothing else has to hold them
    await vault.import_system_credential("tavily", settings.tavily_api_key, label="TAVILY_API_KEY from .env")
    log.info("vault ready", grant_ttl_s=settings.vault_grant_ttl_s, public_url=settings.vault_public_url)
    return vault


async def shutdown_vault() -> None:
    v = current()
    if v is not None:
        await v.aclose()
        set_current(None)
