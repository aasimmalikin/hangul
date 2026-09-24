from functools import lru_cache
from harness.providers.openai_provider import OpenAIProvider
from harness.config import get_settings
from harness.providers.base import Provider
from harness.providers.registry import ModelSpec, Effort

@lru_cache
def get_provider()->Provider:
    """The base provider (configured default model). Cached: it owns the HTTP client."""
    s = get_settings()
    return OpenAIProvider(api_key = s.openai_api_key, model = s.model)


def provider_for(spec: ModelSpec, effort: Effort | None) -> Provider:
    """A provider bound to the model/effort a request selected.

    Shares the cached client; a non-reasoning model never gets an effort
    (the API rejects the parameter for those)."""
    base = get_provider()
    return base.bound(spec.id, effort if spec.supports_reasoning else None)
