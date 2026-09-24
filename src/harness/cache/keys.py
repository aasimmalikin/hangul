"""The cache key. The rule: everything that can change the answer goes in the
hash, and nothing that can't (like the per-request run_id) may."""


import json
import hashlib

def answer_key(*, question: str, prompt_version: str, model: str, tool_names: list[str],
               session_id: str, history: list[dict] | None = None, docs_only: bool = False,
               effort: str | None = None, mode: str = "default", prefs_version: str = "") -> str:
    """Everything that can change the answer must be in the key: the same
    question with different prior turns, in docs-only mode, or at a different
    reasoning effort, is a different answer."""
    payload = json.dumps(
        {
            "q": question, "pv": prompt_version, "m": model, "t": sorted(tool_names), "s": session_id,
            "h": history or [], "d": docs_only, "e": effort, "mode": mode, "pref": prefs_version,
        }, sort_keys = True,
    )
    return "answer" + hashlib.sha256(payload.encode()).hexdigest()[:16]