from functools import lru_cache

from openai import AsyncOpenAI

from harness.config import get_settings


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._client = AsyncOpenAI(api_key = api_key)
        self.model = model

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.embeddings.create(model = self.model, input = text)
        return resp.data[0].embedding

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """One request per batch of chunks. The API preserves input order, but
        sort by ``index`` anyway rather than trust it -- a silent mis-pairing
        here would attach every chunk's text to another chunk's vector."""
        if not texts:
            return []
        resp = await self._client.embeddings.create(model = self.model, input = texts)
        return [d.embedding for d in sorted(resp.data, key = lambda d: d.index)]


@lru_cache
def get_embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder(api_key = get_settings().openai_api_key)
