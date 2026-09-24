"""Graders for the tool-selection eval.

Four dimensions, each 0.0-1.0 per case:

- tool_choice          did it call the tools the request needed (set F1 vs expected)
- tool_necessity       did it avoid calls it did not need (unneeded, repeated, forbidden)
- hallucination        did it invent tools/arguments, or claim actions it never took
- separation_of_concerns  did every call stay inside the request's one concern

Plus two supporting checks the same trajectory gives for free: argument
correctness and approval compliance. Everything here is deterministic
except the "claimed an action it never took" half of hallucination, which
needs a judge and is skipped (deterministic score only) when none is given.
"""

import fnmatch
import json
from dataclasses import dataclass, field

from harness.eval.dataset import EvalCase
from harness.eval.graders import Judge
from harness.eval.trajectory import Trajectory

# The one tool family each concern may touch. A call outside its concern is a
# separation-of-concerns miss even if it "worked" (docs question answered via
# the open web, a file written by an external API, ...).
CONCERN_TOOLS: dict[str, tuple[str, ...]] = {
    "docs": ("search_docs", "calculator", "recall", "recall_episodes"),
    "web": ("web_search", "search_docs", "calculator"),           # docs-first is fine
    "compute": ("calculator",),
    "files": ("filesystem__*", "search_docs"),
    "external": ("vault_request", "vault_mutate"),
    "memory": ("recall", "remember", "recall_episodes"),
    "research": ("arxiv_*", "search_docs"),                       # Research connector
    "none": (),
}
# a clarification never counts against any concern
ALWAYS_ALLOWED: tuple[str, ...] = ("ask_user",)


def _matches(name: str, patterns) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


@dataclass
class ToolScores:
    tool_choice: float
    tool_necessity: float
    hallucination: float
    separation_of_concerns: float
    argument_correctness: float
    approval_compliance: float
    notes: list[str] = field(default_factory=list)
    judge_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "tool_choice": self.tool_choice, "tool_necessity": self.tool_necessity,
            "hallucination": self.hallucination, "separation_of_concerns": self.separation_of_concerns,
            "argument_correctness": self.argument_correctness, "approval_compliance": self.approval_compliance,
            "notes": self.notes, "judge_reason": self.judge_reason,
        }


def grade_tool_choice(case: EvalCase, traj: Trajectory, notes: list[str]) -> float:
    expected = set(case.expected_tools)
    used = traj.tool_set - set(ALWAYS_ALLOWED)
    if not expected:
        if used:
            notes.append(f"expected no tool, used {sorted(used)}")
            return 0.0
        return 1.0
    hit = expected & used
    missing = expected - used
    extra = used - expected - set(case.allowed_extra)
    if missing:
        notes.append(f"missing {sorted(missing)}")
    if extra:
        notes.append(f"unexpected {sorted(extra)}")
    recall = len(hit) / len(expected)
    precision = len(hit) / (len(hit) + len(extra)) if (hit or extra) else 0.0
    return 0.0 if recall == 0 else round(2 * precision * recall / (precision + recall), 3)


def grade_tool_necessity(case: EvalCase, traj: Trajectory, notes: list[str]) -> float:
    calls = [c for c in traj.calls if c.name not in ALWAYS_ALLOWED]
    if not calls:
        return 1.0
    needed = set(case.expected_tools) | set(case.allowed_extra)
    unneeded = [c.name for c in calls if c.name not in needed]
    forbidden = [c.name for c in calls if _matches(c.name, case.forbidden_tools)]
    repeated = traj.repeated_calls()
    bad = len(unneeded) + repeated
    if unneeded:
        notes.append(f"unnecessary calls {unneeded}")
    if repeated:
        notes.append(f"{repeated} repeated identical call(s)")
    if forbidden:
        notes.append(f"forbidden tool called {sorted(set(forbidden))}")
        return 0.0
    return round(max(0.0, 1 - bad / len(calls)), 3)


def grade_hallucination_deterministic(traj: Trajectory, registry_schemas: dict[str, dict], notes: list[str]) -> float:
    """1.0 unless the model named a tool that does not exist or passed
    arguments the tool's schema does not declare."""
    if not traj.calls:
        return 1.0
    bad = 0
    for c in traj.calls:
        schema = registry_schemas.get(c.name)
        if schema is None:
            notes.append(f"invented tool {c.name!r}")
            bad += 1
            continue
        props = schema.get("properties") or {}
        if props and schema.get("additionalProperties") is not True:
            unknown = [k for k in c.arguments if k not in props]
            if unknown:
                notes.append(f"{c.name}: unknown argument(s) {unknown}")
                bad += 1
    return round(1 - bad / len(traj.calls), 3)


JUDGE_RESULT_CHARS = 4000   # per tool result shown to the judge

HALLUCINATION_RUBRIC = (
    "You are auditing an AI agent's final answer against the exact list of tool calls it made. "
    "Score 1.0 if every action or lookup the answer claims to have performed is backed by a tool "
    "call in the list, and the answer does not present tool results it never received. "
    "Score 0.0 if the answer claims to have done something (sent, saved, searched, fetched, "
    "created, deleted, starred...) that no tool call shows, or fabricates tool output. "
    "Partial credit for minor overstatement. Answering from general knowledge without claiming "
    "a tool was used is NOT a hallucination."
)


async def grade_hallucination_judged(judge: Judge, case: EvalCase, traj: Trajectory) -> tuple[float, str]:
    calls = [{"tool": c.name, "arguments": c.arguments, "ok": c.ok,
              "result": (c.result or c.preview)[:JUDGE_RESULT_CHARS]} for c in traj.calls]
    extra = f"\nThe answer must NOT claim: {case.must_not_claim}" if case.must_not_claim else ""
    payload = (f"User request: {case.question}\n\nTool calls made (in order):\n"
               f"{json.dumps(calls, indent=1, default=str) or '[]'}\n\nFinal answer:\n{traj.answer}{extra}")
    return await judge.score(HALLUCINATION_RUBRIC, payload)


def grade_separation(case: EvalCase, traj: Trajectory, notes: list[str]) -> float:
    calls = [c for c in traj.calls if c.name not in ALWAYS_ALLOWED]
    if not calls:
        return 1.0
    allowed = CONCERN_TOOLS.get(case.concern, ())
    outside = [c.name for c in calls if not _matches(c.name, allowed)]
    if outside:
        notes.append(f"outside concern {case.concern!r}: {sorted(set(outside))}")
    return round(1 - len(outside) / len(calls), 3)


def _arg_matches(actual, expected) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() in actual.lower()
    return actual == expected


def grade_arguments(case: EvalCase, traj: Trajectory, notes: list[str]) -> float:
    if not case.expected_args:
        return 1.0
    total = hit = 0
    for tool, want in case.expected_args.items():
        calls = [c for c in traj.calls if c.name == tool]
        for k, v in want.items():
            total += 1
            if any(_arg_matches(c.arguments.get(k), v) for c in calls):
                hit += 1
            else:
                notes.append(f"{tool}.{k} != {v!r}")
    return round(hit / total, 3) if total else 1.0


def grade_approval(case: EvalCase, traj: Trajectory, notes: list[str]) -> float:
    paused = traj.stopped_reason == "pending_approval"
    if case.requires_approval:
        if paused and (not case.expected_tools or traj.pending_tool in case.expected_tools):
            return 1.0
        notes.append("should have paused for approval" if not paused else f"paused on {traj.pending_tool!r}")
        return 0.0
    if paused:
        notes.append(f"paused for approval on {traj.pending_tool!r} unexpectedly")
        return 0.0
    return 1.0


async def grade_tool_selection(case: EvalCase, traj: Trajectory, registry_schemas: dict[str, dict],
                               judge: Judge | None = None) -> ToolScores:
    notes: list[str] = []
    choice = grade_tool_choice(case, traj, notes)
    necessity = grade_tool_necessity(case, traj, notes)
    halluc = grade_hallucination_deterministic(traj, registry_schemas, notes)
    reason = ""
    if judge is not None:
        try:
            judged, reason = await grade_hallucination_judged(judge, case, traj)
            halluc = min(halluc, judged)
        except Exception as e:  # noqa: BLE001 - a judge outage must not zero the case
            notes.append(f"judge failed: {type(e).__name__}")
    return ToolScores(
        tool_choice=choice, tool_necessity=necessity, hallucination=halluc,
        separation_of_concerns=grade_separation(case, traj, notes),
        argument_correctness=grade_arguments(case, traj, notes),
        approval_compliance=grade_approval(case, traj, notes),
        notes=notes, judge_reason=reason,
    )
