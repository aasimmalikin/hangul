"""The eval catalog: every eval the admin page knows about, with its status.

``status="available"`` evals are implemented as a suite in ``suites.py`` and
can be run from the admin page / run_evals.py. ``"planned"`` ones are listed
so the roadmap is visible in the same place, with what they would need."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EvalSpec:
    key: str
    name: str
    category: str                  # quality | tool_use | trajectory | safety | conversation | ops
    status: str                    # available | planned
    description: str
    metrics: tuple[str, ...] = ()  # metric keys the suite reports
    grader: str = ""               # deterministic | judge | mixed | human
    suite: str | None = None       # which suite produces it (None for planned)
    needs: str = ""                # what a planned eval still requires
    sources: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


CATALOG: tuple[EvalSpec, ...] = (
    # ------------------------------------------------------------ available
    EvalSpec(
        key="qa_correctness", name="Answer correctness", category="quality", status="available",
        description="LLM judge scores the final answer against a reference answer (docs-only registry).",
        metrics=("avg_correctness", "pass_rate"), grader="judge", suite="qa",
    ),
    EvalSpec(
        key="qa_faithfulness", name="Faithfulness / groundedness", category="quality", status="available",
        description="Every claim in the answer is supported by the retrieved context (hallucination in RAG).",
        metrics=("avg_faithfulness",), grader="judge", suite="qa",
    ),
    EvalSpec(
        key="tool_choice", name="Tool choice", category="tool_use", status="available",
        description="Did the agent call the tools the request needed? Set-F1 of called vs expected tools, "
                    "tolerating declared extras (e.g. checking docs before the web).",
        metrics=("avg_tool_choice",), grader="deterministic", suite="tool_selection",
    ),
    EvalSpec(
        key="tool_necessity", name="Tool necessity", category="tool_use", status="available",
        description="Did it avoid calls it did not need: unneeded tools, repeated identical calls, and "
                    "forbidden tools (any forbidden call zeroes the case). A no-tool request must make no calls.",
        metrics=("avg_tool_necessity",), grader="deterministic", suite="tool_selection",
    ),
    EvalSpec(
        key="tool_hallucination", name="Tool hallucination", category="tool_use", status="available",
        description="Invented tool names or undeclared arguments (deterministic) and, with a judge, answers "
                    "that claim an action or result no tool call backs.",
        metrics=("avg_hallucination",), grader="mixed", suite="tool_selection",
    ),
    EvalSpec(
        key="separation_of_concerns", name="Separation of concerns", category="tool_use", status="available",
        description="Every call stays inside the request's single concern (docs / web / compute / files / "
                    "external / memory) -- no answering a docs question from the web, no writing files via an API.",
        metrics=("avg_separation_of_concerns",), grader="deterministic", suite="tool_selection",
    ),
    EvalSpec(
        key="argument_correctness", name="Argument correctness", category="tool_use", status="available",
        description="Expected (tool, argument, value) pairs appear in the calls (filesystem path, provider name...).",
        metrics=("avg_argument_correctness",), grader="deterministic", suite="tool_selection",
    ),
    EvalSpec(
        key="approval_compliance", name="Approval compliance", category="safety", status="available",
        description="Destructive/external-write requests pause for human approval on the expected tool, "
                    "and nothing else pauses.",
        metrics=("avg_approval_compliance",), grader="deterministic", suite="tool_selection",
    ),
    EvalSpec(
        key="trajectory_efficiency", name="Trajectory efficiency", category="trajectory", status="available",
        description="Steps, tool calls, repeated calls (loops) and budget stops per case.",
        metrics=("avg_steps", "avg_tool_calls", "loop_rate", "budget_stop_rate"), grader="deterministic",
        suite="tool_selection",
    ),
    EvalSpec(
        key="cost_latency", name="Cost & latency", category="ops", status="available",
        description="Tokens, priced cost and wall-clock latency per case, from the run itself.",
        metrics=("avg_cost_usd", "avg_latency_ms", "total_cost_usd"), grader="deterministic",
        suite="tool_selection",
    ),
    # -------------------------------------------------------------- planned
    EvalSpec(
        key="task_completion", name="Task completion (end state)", category="quality", status="planned",
        description="Verify the goal was achieved by inspecting side effects (file written with the right "
                    "content, API call landed) rather than the answer text.",
        grader="deterministic", needs="a sandboxed session folder + mock upstream per case, and a per-case "
                                     "state assertion in the dataset",
    ),
    EvalSpec(
        key="multi_turn", name="Multi-turn fidelity", category="conversation", status="planned",
        description="Context retention, goal drift and turns-to-resolution across a scripted conversation.",
        grader="mixed", needs="conversation-level datasets (scripted user turns) and a session-level runner",
    ),
    EvalSpec(
        key="retrieval_quality", name="Retrieval precision / recall", category="quality", status="planned",
        description="Were the right chunks retrieved for the question (contextual precision & recall)?",
        grader="deterministic", needs="labelled relevant chunk ids per case in the evalset",
    ),
    EvalSpec(
        key="prompt_injection", name="Prompt-injection resistance", category="safety", status="available",
        description="Each case poisons one tool's result with an attack (exfiltrate, call a tool, reveal the "
                    "prompt, hidden text). Scores: attack blocked (forbidden tool never ran; a pause for "
                    "approval counts), no leak (canary/secrets stayed in), detected (the screen flagged it), "
                    "task completed (the user's real request was still served), reported (judge).",
        metrics=("attack_success_rate", "leak_rate", "detection_rate", "avg_task_completed", "avg_reported", "pass_rate"),
        grader="mixed", suite="prompt_injection",
    ),
    EvalSpec(
        key="pii_leakage", name="PII / secret leakage", category="safety", status="planned",
        description="Answers and tool arguments never contain another user's data or a vault secret.",
        grader="deterministic", needs="seeded canary values in memory/docs and a scanner over answers",
    ),
    EvalSpec(
        key="consistency", name="Consistency (pass^k)", category="quality", status="planned",
        description="Run each case k times; report pass@k and pass^k to expose flaky tool choices.",
        grader="deterministic", needs="k× the run budget; a repeat option on the runner",
    ),
    EvalSpec(
        key="judge_calibration", name="Judge calibration", category="ops", status="planned",
        description="Agreement between the LLM judge and human labels on a sampled set, so judge scores "
                    "can be trusted as a gate.",
        grader="human", needs="a human-labelled sample (evals/calibration is an empty placeholder)",
    ),
    EvalSpec(
        key="production_drift", name="Production monitoring & drift", category="ops", status="planned",
        description="Tool-error rate, approval rejection rate, cost per run and faithfulness sampled from "
                    "live traces, alerting on regressions vs the eval baseline.",
        grader="deterministic", needs="persisting traces beyond the in-memory ring buffer and a sampler that "
                                     "grades a slice of real runs",
    ),
    EvalSpec(
        key="user_feedback", name="User feedback", category="ops", status="planned",
        description="Thumbs up/down and free-text on answers, joined to the run trace for review.",
        grader="human", needs="a feedback part in the chat UI and a table to store it",
    ),
)

SUITES: dict[str, str] = {
    "qa": "Answer quality (correctness + faithfulness) on data/evalset.jsonl",
    "tool_selection": "Tool selection, necessity, hallucination, separation of concerns, arguments, "
                      "approval, efficiency and cost on data/evalsets/tool_selection.jsonl",
    "prompt_injection": "Red-team: poisoned tool results on data/evalsets/prompt_injection.jsonl",
}


def catalog() -> list[dict]:
    return [e.as_dict() for e in CATALOG]
