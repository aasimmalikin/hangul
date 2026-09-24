import json
import time
from pathlib import Path

from harness.vault.redact import redactor


class AuditLog:
    """Append-only JSONL. Every entry is scrubbed with the vault redactor
    first so a credential or grant that lands in a tool argument is never
    written to disk."""

    def __init__(self, path:str = "data/audit.jsonl"):
        self._path = Path(path)
        self._path.parent.mkdir(parents = True, exist_ok = True)

    def _write(self, entry: dict) -> None:
        with self._path.open("a") as f:
            f.write(redactor.scrub_json(entry) + "\n")

    def record(self, *, tool:str, args: dict, decision:str, tier: str)->None:
        self._write({
            "ts": time.time(),
            "tool": tool,
            "args": args,
            "decision": decision,
            "tier": tier
        })

    def record_vault(self, **fields) -> None:
        """One proxied call: subject, provider, method, path, status, ms --
        never a body or a header."""
        self._write({"ts": time.time(), "kind": "vault", **fields})

    def record_admin(self, **fields) -> None:
        """One admin-console request: email, user id, ip, method, path."""
        self._write({"ts": time.time(), "kind": "admin", **fields})

    def record_security(self, **fields) -> None:
        """One prompt-injection event: layer, severity, source, action, reasons, run."""
        self._write({"ts": time.time(), "kind": "security", **fields})

    def entries(self, kind: str, limit: int = 100) -> list[dict]:
        """Newest-first rows of one kind."""
        if not self._path.exists():
            return []
        out: list[dict] = []
        for line in reversed(self._path.read_text().splitlines()):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") == kind:
                out.append(e)
                if len(out) >= limit:
                    break
        return out

    def vault_entries(self, subject: str, limit: int = 50) -> list[dict]:
        """Newest-first proxied calls for one subject (the /vault/audit view)."""
        if not self._path.exists():
            return []
        out: list[dict] = []
        for line in reversed(self._path.read_text().splitlines()):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") == "vault" and str(e.get("subject")) == str(subject):
                out.append(e)
                if len(out) >= limit:
                    break
        return out
