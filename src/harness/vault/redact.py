"""Scrub live secrets out of anything that gets logged or persisted.

One process-wide ``Redactor`` learns every credential decrypted and every
grant minted in this process. ``scrub`` is a plain substring replace over a
small set, so it is cheap enough to run on every tool result and audit row."""

import json
from typing import Any

from harness.vault.crypto import fingerprint

MIN_LEN = 8  # shorter values would false-positive all over the place


class Redactor:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}   # value -> marker

    def register(self, value: str | None, label: str) -> None:
        if not value or len(value) < MIN_LEN:
            return
        self._secrets.setdefault(value, f"[REDACTED:{label}:{fingerprint(value, 8)}]")

    def forget(self, value: str | None) -> None:
        if value:
            self._secrets.pop(value, None)

    def __len__(self) -> int:
        return len(self._secrets)

    def scrub_text(self, text: str) -> str:
        if not text or not self._secrets:
            return text
        # longest first so a secret that contains another is replaced whole
        for value in sorted(self._secrets, key=len, reverse=True):
            if value in text:
                text = text.replace(value, self._secrets[value])
        return text

    def scrub(self, obj: Any) -> Any:
        """Deep-scrub strings inside dicts/lists/tuples; other types pass through."""
        if isinstance(obj, str):
            return self.scrub_text(obj)
        if isinstance(obj, dict):
            return {k: self.scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.scrub(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.scrub(v) for v in obj)
        return obj

    def scrub_json(self, obj: Any) -> str:
        return self.scrub_text(json.dumps(obj, default=str))


# The process-wide instance every sink (audit, loop, tracing) reads.
redactor = Redactor()
