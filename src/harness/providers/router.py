"""Auto model choice: the right model (and depth) for each message.

The picker's default is "Auto". Each message is sorted into one of three
levels by instant word and length rules -- no extra model call, so no added
cost or delay -- and mapped to a model the user's plan includes:

  quick     reminders, lists, weather, conversions, one-liners   -> cheapest, low depth
  everyday  most requests (reading mail, calendar, summaries)     -> cheap model, medium depth
  write     drafts, replies, rewrites the user will send          -> mid model, medium depth
  deep      research mode, analysis, comparisons, code, long asks,
            and new images (the model writes the image model's prompt) -> strongest allowed, high depth

Most messages are "everyday", so that level runs on the cheap model: a
calendar lookup does not need the mid model, which costs ten times as much.

A model the user picks by hand always wins; "auto" is only ever a request.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from harness.config import get_settings
from harness.providers.registry import Effort, ModelSpec, get_model, list_models

AUTO = "auto"
EFFORT_ORDER: tuple[Effort, ...] = ("minimal", "low", "medium", "high", "xhigh")

_DEEP = re.compile(
    r"\b(analy[sz]e|analysis|compare|comparison|versus|vs\.?|pros and cons|trade-?offs?|strategy|in depth|in-depth|"
    r"detailed|step by step|explain why|why does|prove|proof|derive|research|investigate|evaluate|critique|review my|"
    r"essay|report|thesis|business plan|financial model|forecast|debug|refactor|code|python|javascript|sql|algorithm|"
    r"spreadsheet|csv|excel|chart|statement|where did my money go|calculate my|budget for)\b", re.I)
_QUICK = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|ok|okay)\b|\b(remind me|reminder|add .{1,40} to (my )?(list|shopping)|"
    r"shopping list|to-?do|note:|take a note|weather|temperature|umbrella|convert|in (usd|inr|eur|gbp)|"
    r"what time|time in|timezone|how many .{1,20} in|define|meaning of|spell|translate)\b", re.I)

_WRITE = re.compile(
    r"\b(draft|write|compose|reply|respond|rewrite|reword|rephrase|proofread|polish|cover letter|letter to|"
    r"message to|email (him|her|them|back)|caption|announcement)\b", re.I)

# A new picture (generate_image is Pro, so the frontier model is always in the
# plan). Needs a drawing verb: "what's in this image?" is a view_image lookup.
_IMAGE = re.compile(
    r"\bdraw\b(?!\s+(up|on|from|a conclusion|attention)\b)|\billustrate (a|an|me)\b|"
    r"\b(generate|create|make|design|render|paint|sketch)\b.{0,40}?\b(image|picture|pic|photo|poster|logo|"
    r"illustration|thumbnail|wallpaper|artwork|icon|banner|drawing|painting|sticker|mock-?up)s?\b", re.I)


@dataclass(frozen=True)
class AutoChoice:
    level: str            # quick | everyday | write | deep
    model: str
    effort: Effort | None


def level_for(question: str, mode: str = "default") -> str:
    q = (question or "").strip()
    if mode == "research":
        return "deep"
    words = len(q.split())
    if _DEEP.search(q) or _IMAGE.search(q) or words > 80 or q.count("\n") > 6:
        return "deep"
    if _QUICK.search(q) and words <= 25:
        return "quick"
    if _WRITE.search(q):
        return "write"
    # short but multi-step (mail, calendar, planning, writing): not "quick"
    if words <= 6 and "?" not in q and not re.search(
            r"\b(email|mail|inbox|calendar|meeting|schedule|draft|write|plan|brief|summari[sz]e|reply)\b", q, re.I):
        return "quick"
    return "everyday"


def _ladder(level: str) -> list[str]:
    s = get_settings()
    fast, everyday, balanced, best = s.auto_fast_model, s.auto_everyday_model, s.auto_balanced_model, s.auto_best_model
    return {"quick": [fast], "everyday": [everyday, fast], "write": [balanced, fast],
            "deep": [best, balanced, fast]}[level]


def _clamp(spec: ModelSpec, want: Effort, max_effort: Effort) -> Effort | None:
    if not spec.supports_reasoning:
        return None
    cap = EFFORT_ORDER.index(max_effort)
    allowed = [e for e in spec.efforts if EFFORT_ORDER.index(e) <= cap]
    if not allowed:
        return None
    if want in allowed:
        return want
    below = [e for e in allowed if EFFORT_ORDER.index(e) <= EFFORT_ORDER.index(want)]
    return max(below, key=EFFORT_ORDER.index) if below else min(allowed, key=EFFORT_ORDER.index)


def choose(question: str, mode: str = "default", *, allowed: Callable[[ModelSpec], bool] = lambda s: True,
           max_effort: Effort = "xhigh") -> AutoChoice:
    level = level_for(question, mode)
    want: Effort = {"quick": "low", "everyday": "medium", "write": "medium", "deep": "high"}[level]
    for model_id in _ladder(level):
        spec = get_model(model_id)
        if spec is not None and allowed(spec):
            return AutoChoice(level, spec.id, _clamp(spec, want, max_effort))
    # nothing on the ladder is allowed: the plan's cheapest model
    spec = min((s for s in list_models() if allowed(s)), key=lambda s: s.input_usd_per_m + s.output_usd_per_m)
    return AutoChoice(level, spec.id, _clamp(spec, want, max_effort))
