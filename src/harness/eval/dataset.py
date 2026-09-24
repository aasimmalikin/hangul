import json
from pathlib import Path

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    """One eval case. The QA fields (``question``/``reference``) are what the
    original evalset carries; the rest describe what a *good trajectory*
    looks like and are only read by the agent evals."""
    id: str
    question: str
    reference: str = ""
    # conversation context the question follows (OpenAI-style messages)
    history: list[dict] = Field(default_factory=list)
    # which single concern the request is about: docs | web | compute | files | external | memory | none
    concern: str = "docs"
    # tools that must be called (empty + concern "none" = no tool should be called)
    expected_tools: list[str] = Field(default_factory=list)
    # tools whose use is tolerated (e.g. checking docs first) but not required
    allowed_extra: list[str] = Field(default_factory=list)
    # tools that must never be called for this request
    forbidden_tools: list[str] = Field(default_factory=list)
    # tool -> {arg: expected value or substring}; every listed pair must match some call to that tool
    expected_args: dict[str, dict] = Field(default_factory=dict)
    # the run must pause for human approval (on one of expected_tools)
    requires_approval: bool = False
    # free text for the judge: what a correct answer must NOT claim (hallucination bait)
    must_not_claim: str = ""
    # connectors switched on for this case (as the user would from "+ → Connectors")
    connectors: list[str] = Field(default_factory=list)
    # prompt_injection suite: {"tool": <name>, "payload": <text appended to that tool's result>}
    poison: dict = Field(default_factory=dict)
    # what the injected text tries to make the agent do, for the report
    attack_goal: str = ""
    tags: list[str] = Field(default_factory=list)


def load_case(path: Path | str) -> list[EvalCase]:
    lines = Path(path).read_text().strip().splitlines()
    return [EvalCase(**json.loads(line)) for line in lines if line.strip()]


load_cases = load_case
