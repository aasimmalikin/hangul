"""Captions for a brand post, one per platform, in the brand's voice.

One call on the cheap model (``summary_model``, metered to the user) writes
them all as JSON; the platform rules (length, hashtags, tone) are in the
prompt and enforced again here, so a caption is never cut off by the app.
"""

import json
import re

from harness.db.brands import BrandRow
from harness.logging import log

# platform -> (label, max characters, max hashtags, what the platform wants)
PLATFORMS: dict[str, tuple[str, int, int, str]] = {
    "instagram": ("Instagram", 2200, 15, "a hook in the first line, short lines, a few emojis, a call to action; hashtags go in the first comment"),
    "facebook": ("Facebook", 2000, 3, "friendly and conversational, a clear call to action, at most 3 hashtags"),
    "linkedin": ("LinkedIn", 3000, 5, "professional, a useful or proud angle, no slang, 3-5 hashtags at the end"),
    "x": ("X", 280, 2, "punchy, under 280 characters including hashtags, at most 2 hashtags"),
    "whatsapp": ("WhatsApp", 700, 0, "short, warm, like a message to regular customers, no hashtags, one emoji at most"),
}
DEFAULT_PLATFORMS = ("instagram", "facebook", "whatsapp")

_PROMPT = (
    "You write social media captions for a small business. Reply with JSON only: "
    '{"<platform>": {"text": caption, "hashtags": ["#tag", ...], "first_comment": text or ""}, ...} for exactly the '
    "platforms asked. Write in the brand's voice. Never invent prices, dates, offers or facts that aren't in the post; "
    "use the brand's own hashtags first. Platform rules:\n")


def _tags(raw) -> list[str]:
    out = []
    for t in raw or []:
        t = "#" + re.sub(r"[^\w]", "", str(t).lstrip("#"))
        if len(t) > 1 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


def clean(data: dict, platforms: list[str], brand: BrandRow) -> dict:
    """Keep the platforms asked for and hold each to its limits."""
    out = {}
    own = [t for s in brand.hashtags for t in _tags(s.get("tags") if isinstance(s, dict) else [])]
    for p in platforms:
        label, max_chars, max_tags, _rule = PLATFORMS[p]
        c = data.get(p) if isinstance(data.get(p), dict) else {}
        text = str(c.get("text") or "").strip()
        tags = _tags(c.get("hashtags"))
        tags = (own + [t for t in tags if t.lower() not in {o.lower() for o in own}])[:max_tags] if max_tags else []
        # hashtags live in `hashtags`; the model sometimes also writes them into the text
        # (then they'd be posted twice), so drop those from the text
        if tags:
            lowered = {t.lower() for t in tags}
            text = re.sub(r"(?:\s*#\w+)+\s*$", lambda m: "" if all(t.lower() in lowered for t in re.findall(r"#\w+", m.group(0))) else m.group(0), text)
            text = re.sub(r"(?<!\w)#\w+", lambda m: m.group(0) if m.group(0).lower() not in lowered else m.group(0)[1:], text).strip()
        first = str(c.get("first_comment") or "").strip()
        if p == "instagram" and tags and not first:
            first = " ".join(tags)
        if p == "x":
            room = max_chars - (len(" ".join(tags)) + 1 if tags else 0)
            if len(text) > room:
                text = text[: max(0, room - 1)].rstrip() + "…"
        else:
            text = text[:max_chars]
        out[p] = {"label": label, "text": text, "hashtags": tags, "first_comment": first[:2200]}
    return out


def _post_summary(brand: BrandRow, words: dict, layout: str, slides: list) -> str:
    lines = [f"Brand: {brand.name}", f"Voice: {brand.voice or 'friendly and clear'}"]
    for k in ("handle", "website", "cta", "footer"):
        v = getattr(brand, k, "")
        if v:
            lines.append(f"{k.title()}: {v}")
    if brand.hashtags:
        lines.append("Brand hashtags: " + "; ".join(f"{s.get('name', '')}: {' '.join(s.get('tags', []))}"
                                                  for s in brand.hashtags if isinstance(s, dict)))
    lines.append(f"Post type: {layout}")
    for k in ("headline", "subline", "price", "cta"):
        if words.get(k):
            lines.append(f"Post {k}: {words[k]}")
    for i, s in enumerate(slides or [], 1):
        if s.get("headline") or s.get("subline"):
            lines.append(f"Slide {i}: {s.get('headline', '')} {s.get('subline', '')}".strip())
    return "\n".join(lines)


async def write(brand: BrandRow, words: dict, *, layout: str = "band", slides: list | None = None,
                platforms: list[str] | tuple[str, ...] = DEFAULT_PLATFORMS, note: str = "") -> dict:
    """{platform: {label, text, hashtags, first_comment}}; raises on failure."""
    from harness.billing import meter
    from harness.config import get_settings
    from harness.obs.tracing import cost_usd
    from harness.providers import get_provider
    from harness.providers.registry import get_model

    platforms = [p for p in dict.fromkeys(platforms) if p in PLATFORMS] or list(DEFAULT_PLATFORMS)
    rules = "\n".join(f"- {p}: {PLATFORMS[p][3]} (max {PLATFORMS[p][1]} characters)" for p in platforms)
    spec = get_model(get_settings().summary_model)
    base = get_provider()
    provider = (base.bound(spec.id, "low" if "low" in spec.efforts else None)
                if spec is not None and hasattr(base, "bound") else base)
    user = _post_summary(brand, words, layout, slides or []) + f"\nPlatforms: {', '.join(platforms)}"
    if note:
        user += f"\nThe user's note: {note[:300]}"
    turn = await provider.chat([{"role": "system", "content": _PROMPT + rules}, {"role": "user", "content": user}], [])
    meter.add(cost_usd(getattr(provider, "model", get_settings().summary_model), getattr(turn, "input_tokens", 0) or 0,
                       getattr(turn, "output_tokens", 0) or 0, getattr(turn, "cached_input_tokens", 0) or 0), "captions")
    text = (turn.text or "").strip()
    try:
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except ValueError as e:
        log.warning("captions were not JSON", sample=text[:200])
        raise ValueError("The captions came back garbled; try again.") from e
    return clean(data, platforms, brand)
