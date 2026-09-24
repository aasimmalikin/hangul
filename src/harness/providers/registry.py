"""Registry of selectable OpenAI models: pricing and reasoning-effort rules.

This is the single source of truth for which models a user may pick, what
they cost, and how "effort" maps both to OpenAI's `reasoning_effort` value
and to the agent loop's step/token budget. `cost_usd` in obs/tracing.py and
`GET /models` both read from here.

Prices are $ per 1M tokens (input, output), standard tier, no cached-input
discount. VERIFY against https://developers.openai.com/api/docs/pricing
before deploying -- the table was drafted from that page on 2026-09-18.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from harness.config import get_settings

Effort = Literal["minimal", "low", "medium", "high", "xhigh"]

# Efforts accepted by the current reasoning families (VERIFY per model page).
_EFFORTS_5_4_PLUS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh")
_EFFORTS_5_X: tuple[Effort, ...] = ("minimal", "low", "medium", "high")


@dataclass(frozen=True)
class ModelSpec:
    id: str                     # OpenAI model id, sent verbatim to the API
    label: str                  # what the UI shows
    input_usd_per_m: float
    output_usd_per_m: float
    supports_reasoning: bool
    efforts: tuple[Effort, ...] = ()   # values the API accepts; () for non-reasoning models
    default_effort: Effort | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["efforts"] = list(self.efforts)
        return d


@dataclass(frozen=True)
class EffortBudget:
    max_steps: int
    max_tokens: int


# How hard the *agent* works at each effort, on top of how hard the model
# thinks. "medium" is today's loop default; keep it that way so existing
# behaviour is unchanged when nothing is selected.
EFFORT_BUDGETS: dict[Effort, EffortBudget] = {
    "minimal": EffortBudget(max_steps=8, max_tokens=20_000),
    "low": EffortBudget(max_steps=8, max_tokens=20_000),
    "medium": EffortBudget(max_steps=20, max_tokens=50_000),
    "high": EffortBudget(max_steps=40, max_tokens=120_000),
    "xhigh": EffortBudget(max_steps=40, max_tokens=120_000),
}
DEFAULT_BUDGET = EFFORT_BUDGETS["medium"]


def _reasoning(id: str, label: str, pin: float, pout: float,
               efforts: tuple[Effort, ...] = _EFFORTS_5_4_PLUS) -> ModelSpec:
    return ModelSpec(id, label, pin, pout, supports_reasoning=True,
                     efforts=efforts, default_effort="medium")


def _plain(id: str, label: str, pin: float, pout: float) -> ModelSpec:
    return ModelSpec(id, label, pin, pout, supports_reasoning=False)


# Insertion order is the order the UI lists them.
_SPECS: list[ModelSpec] = [
    # VERIFY: prices from developers.openai.com/api/docs/pricing on 2026-09-18
    _reasoning("gpt-6-astra", "GPT-6 Astra", 10.00, 50.00),
    _reasoning("gpt-5.6-sol", "GPT-5.6 Sol", 4.00, 20.00),
    _reasoning("gpt-5.6-terra", "GPT-5.6 Terra", 2.00, 12.00),
    _reasoning("gpt-5.6-luna", "GPT-5.6 Luna", 0.20, 1.20),
    _reasoning("gpt-5.5", "GPT-5.5", 5.00, 30.00),
    _reasoning("gpt-5.4", "GPT-5.4", 2.50, 15.00),
    _reasoning("gpt-5.4-mini", "GPT-5.4 mini", 0.75, 4.50),
    _reasoning("gpt-5.4-nano", "GPT-5.4 nano", 0.20, 1.25),
    _reasoning("gpt-5.1", "GPT-5.1", 1.25, 10.00, _EFFORTS_5_X),
    _reasoning("gpt-5-mini", "GPT-5 mini", 0.25, 2.00, _EFFORTS_5_X),
    _reasoning("gpt-5-nano", "GPT-5 nano", 0.05, 0.40, _EFFORTS_5_X),
    _plain("gpt-4.1", "GPT-4.1", 2.00, 8.00),
    _plain("gpt-4.1-mini", "GPT-4.1 mini", 0.40, 1.60),
]

MODELS: dict[str, ModelSpec] = {s.id: s for s in _SPECS}


def list_models() -> list[ModelSpec]:
    return list(_SPECS)


def get_model(model_id: str) -> ModelSpec | None:
    return MODELS.get(model_id)


def default_model_id() -> str:
    return get_settings().model


def resolve(model: str | None, effort: str | None) -> tuple[ModelSpec, Effort | None]:
    """Turn a (possibly absent) user choice into a spec and an effort.

    None means "the configured default". Raises ValueError for a model that
    is not in the registry or an effort the model does not accept, so the
    route can turn it into a 422.
    """
    model_id = model or default_model_id()
    spec = get_model(model_id)
    if spec is None:
        raise ValueError(f"Unknown model '{model_id}'.")
    if not spec.supports_reasoning:
        if effort is not None:
            raise ValueError(f"Model '{spec.id}' does not take a reasoning effort.")
        return spec, None
    if effort is None:
        configured = get_settings().default_effort
        effort = configured if configured in spec.efforts else spec.default_effort
    if effort not in spec.efforts:
        raise ValueError(
            f"Effort '{effort}' is not supported by '{spec.id}' "
            f"(choose one of: {', '.join(spec.efforts)}).")
    return spec, effort  # type: ignore[return-value]


def budget_for(effort: Effort | None) -> EffortBudget:
    if effort is None:
        return DEFAULT_BUDGET
    return EFFORT_BUDGETS.get(effort, DEFAULT_BUDGET)
