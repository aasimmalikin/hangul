"""Layered prompt-injection defence.

Layers, in the order a request meets them (see docs/notes on the design):

1. hardened system prompt        prompts/templates/system_agent.txt (untrusted_content_policy)
2. input screen                  detector on the user's message; repeat offenders are throttled
3. spotlighting of tool results  every tool result goes to the model JSON-encoded with its
                                 provenance, inside a per-run random delimiter, with a reminder
4. tool-result screen            detector (+ optional LLM classifier) on what tools return;
                                 a hit taints the run and is reported to the user
5. action guard                  deterministic checks on tool *arguments* (secrets, canary,
                                 encoded blobs leaving through search/API/file writes) and a
                                 taint-driven step-up: once the context is tainted, external
                                 actions need human approval
6. output guard                  answer scrubbed for secrets, the prompt canary, markdown
                                 image / suspicious-URL exfiltration
7. oversight                     security events streamed to the UI, audited, on the admin page,
                                 and a red-team eval suite (prompt_injection)
"""

from harness.security.guard import RunSecurity, SecurityEvent, SecurityGuard, get_guard, set_guard

__all__ = ["RunSecurity", "SecurityEvent", "SecurityGuard", "get_guard", "set_guard"]
