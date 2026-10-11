"""The brand template library: a few business kinds, three looks each.

Setting up a brand is one sentence ("a small café in Srinagar, cosy") and a
tap on one of three looks, so nobody has to think about colour codes or
fonts. ``match_kind`` finds the kind by keyword; only a sentence that
matches nothing costs one call on the cheap model (``suggest``), which
names the business and writes three looks of its own.

Fonts are keys of ``brands.fonts.FONTS``; colours are ``{role, hex}`` with
roles primary / secondary / accent / text.
"""

import json
import re
from dataclasses import asdict, dataclass

from harness.logging import log

TEMPLATES_VERSION = "1"
ROLES = ("primary", "secondary", "accent", "text")
FONT_KEYS = ("sans", "serif", "script", "display")


@dataclass(frozen=True)
class Look:
    id: str
    label: str
    colors: tuple[tuple[str, str], ...]      # (role, hex) in ROLES order
    style: str                               # image style words
    voice: str                               # writing tone
    font: str                                # FONT_KEYS

    def as_dict(self) -> dict:
        d = asdict(self)
        d["colors"] = [{"role": r, "hex": h} for r, h in self.colors]
        return d


def _look(id: str, label: str, hexes: str, style: str, voice: str, font: str) -> Look:
    return Look(id, label, tuple(zip(ROLES, hexes.split())), style, voice, font)


# kind -> (label, keywords, three looks)
KINDS: dict[str, tuple[str, tuple[str, ...], tuple[Look, ...]]] = {
    "cafe": ("Café", ("cafe", "café", "coffee", "chai", "tea", "kahwa", "bakery", "bake", "cake", "dessert"), (
        _look("cafe-warm", "Warm & cosy", "#B5502F #F4EBDD #E0A458 #3B2A20",
              "warm natural light, wooden textures, steam and soft shadows, hand-drawn touches, cosy", "friendly and playful, short sentences", "script"),
        _look("cafe-minimal", "Modern minimal", "#1F1F1F #F5F3EE #8BA888 #1F1F1F",
              "clean bright minimal styling, lots of white space, soft daylight, muted sage accents", "calm and confident, few words", "sans"),
        _look("cafe-heritage", "Kashmiri heritage", "#A8402C #F3E6D3 #C9A227 #2E1F18",
              "rich chinar reds and gold, copper samovars, papier-mâché patterns, warm golden light", "warm and proud of tradition", "serif"),
    )),
    "restaurant": ("Restaurant", ("restaurant", "dhaba", "kitchen", "food", "biryani", "wazwan", "pizza", "diner", "catering"), (
        _look("rest-bold", "Bold & hungry", "#C62828 #FFF4E5 #FFB300 #1A1A1A",
              "close-up food photography, glossy textures, dramatic warm light, appetising steam", "punchy and mouth-watering", "display"),
        _look("rest-fine", "Fine dining", "#1C1C1C #F2EEE6 #B08D57 #1C1C1C",
              "dark moody backgrounds, elegant plating, single soft spotlight, gold accents", "refined and understated", "serif"),
        _look("rest-street", "Street food", "#FF6F00 #FFF8E1 #2E7D32 #212121",
              "vibrant street scenes, bright daylight, lively colours, motion and crowds", "energetic and casual", "display"),
    )),
    "salon": ("Salon & beauty", ("salon", "beauty", "spa", "parlour", "parlor", "hair", "nails", "makeup", "barber"), (
        _look("salon-blush", "Soft blush", "#C77D8B #FBF1F1 #D4AF37 #3A2A2E",
              "soft pastel light, glowing skin, silk and petals, airy and elegant", "warm, caring and elegant", "serif"),
        _look("salon-luxe", "Black & gold luxe", "#111111 #F7F3EA #C9A227 #111111",
              "high-contrast studio light, glossy black surfaces, gold details, luxurious", "premium and confident", "display"),
        _look("salon-fresh", "Fresh & natural", "#5B8C6A #F3F7F2 #E8B4A0 #23302A",
              "natural daylight, green plants, wood and linen, clean and organic", "gentle and natural", "sans"),
    )),
    "boutique": ("Boutique & fashion", ("boutique", "fashion", "clothing", "clothes", "apparel", "saree", "pheran", "jewellery", "jewelry", "handicraft", "shawl", "pashmina"), (
        _look("bout-editorial", "Editorial", "#222222 #F4F1EC #B5502F #222222",
              "fashion editorial photography, natural poses, soft directional light, neutral backdrops", "stylish and confident", "serif"),
        _look("bout-bright", "Bright & bold", "#D81B60 #FFF3F8 #FFC107 #1A1A1A",
              "bold colour blocking, bright even light, playful compositions", "fun and upbeat", "display"),
        _look("bout-craft", "Handcrafted heritage", "#7A2E2E #F6EEDF #C9A227 #2B1D16",
              "close-ups of handwork and embroidery, warm window light, rich textiles, heritage", "proud of craft, warm", "serif"),
    )),
    "clinic": ("Clinic & health", ("clinic", "doctor", "dental", "dentist", "hospital", "physio", "pharmacy", "health", "diagnostic", "yoga", "gym", "fitness"), (
        _look("clinic-trust", "Trust blue", "#1565C0 #F3F8FD #26A69A #10263D",
              "clean bright clinical spaces, friendly professionals, soft even light", "clear, caring and trustworthy", "sans"),
        _look("clinic-calm", "Calm green", "#2E7D6B #F1F8F5 #A5D6A7 #18332B",
              "calm natural light, plants, soft greens, reassuring and gentle", "gentle and reassuring", "sans"),
        _look("clinic-energy", "Active & energetic", "#E65100 #FFF5EC #1E88E5 #1B1B1B",
              "dynamic motion, bright light, healthy active people, bold contrast", "motivating and upbeat", "display"),
    )),
    "tutor": ("Tutor & coaching", ("tutor", "tuition", "coaching", "classes", "academy", "school", "teacher", "course", "training", "institute"), (
        _look("tutor-bright", "Bright & friendly", "#3949AB #F5F6FF #FFB300 #1A1F3D",
              "bright classroom light, books and notebooks, smiling students, cheerful", "encouraging and clear", "sans"),
        _look("tutor-pro", "Professional", "#263238 #F4F6F7 #00897B #263238",
              "clean desks, laptops, focused learners, neutral tones", "professional and to the point", "sans"),
        _look("tutor-kids", "Playful kids", "#F4511E #FFF8E1 #43A047 #212121",
              "colourful playful illustrations feel, crayons and blocks, joyful", "playful and warm", "display"),
    )),
    "startup": ("Startup & tech", ("startup", "app", "software", "saas", "tech", "ai", "platform", "product", "agency", "studio"), (
        _look("start-modern", "Modern tech", "#4F46E5 #F5F5FF #22D3EE #111827",
              "sleek modern devices, clean gradients, soft glow, minimal", "clear and confident, no jargon", "sans"),
        _look("start-dark", "Dark & premium", "#0F172A #E2E8F0 #F59E0B #0F172A",
              "dark backgrounds, crisp product shots, rim light, premium", "bold and concise", "display"),
        _look("start-friendly", "Friendly & human", "#0E9F6E #F0FDF8 #F97316 #1F2937",
              "real people using the product, natural light, warm and approachable", "friendly and human", "sans"),
    )),
    "shop": ("Shop & retail", ("shop", "store", "kirana", "grocery", "mart", "retail", "dry fruits", "saffron", "electronics", "hardware", "pharmacy"), (
        _look("shop-fresh", "Fresh & local", "#2E7D32 #F4FAF2 #FBC02D #1B2A1C",
              "fresh produce, bright daylight, neat shelves, local and honest", "warm and neighbourly", "sans"),
        _look("shop-deal", "Big deals", "#D32F2F #FFFDE7 #FFC107 #1A1A1A",
              "bold product shots, bright clean background, energetic", "punchy, offer-first", "display"),
        _look("shop-premium", "Premium goods", "#3E2723 #FAF6F0 #C9A227 #3E2723",
              "product on marble or wood, soft studio light, elegant packaging", "premium and trustworthy", "serif"),
    )),
    "events": ("Events & weddings", ("event", "events", "wedding", "party", "birthday", "planner", "decor", "photography", "photographer", "dj"), (
        _look("event-elegant", "Elegant", "#6D2E46 #FBF4F0 #D4AF37 #2D1B22",
              "fairy lights, florals, soft bokeh, romantic golden hour", "warm and celebratory", "script"),
        _look("event-festive", "Festive", "#C2185B #FFF8E1 #FF9800 #2A1A1F",
              "marigolds, diyas, vibrant colours, joyful crowds, festive", "joyful and lively", "display"),
        _look("event-modern", "Modern minimal", "#212121 #FAFAFA #9E9E9E #212121",
              "clean venues, white florals, soft natural light, minimal", "calm and elegant", "serif"),
    )),
    "freelancer": ("Freelancer & personal brand", ("freelance", "freelancer", "consultant", "designer", "writer", "creator", "influencer", "portfolio", "coach", "personal brand"), (
        _look("free-clean", "Clean professional", "#1E3A5F #F5F7FA #E07A5F #1E3A5F",
              "clean workspace, natural light, confident portraits, neutral tones", "professional and personable", "sans"),
        _look("free-creative", "Creative", "#7B1FA2 #FBF5FF #FFB74D #1F1029",
              "bold colours, creative tools, playful compositions", "creative and witty", "display"),
        _look("free-warm", "Warm & personal", "#8D5B4C #FAF5F0 #A3B18A #2F2420",
              "warm earthy tones, cafés and notebooks, golden light", "warm and genuine", "serif"),
    )),
}


def kinds() -> list[dict]:
    """The whole library, for the setup screen."""
    return [{"kind": k, "label": label, "looks": [lk.as_dict() for lk in looks]}
            for k, (label, _kw, looks) in KINDS.items()]


def find_look(look_id: str) -> tuple[str, Look] | None:
    for k, (_label, _kw, looks) in KINDS.items():
        for lk in looks:
            if lk.id == look_id:
                return k, lk
    return None


def match_kind(sentence: str) -> str | None:
    """The kind whose keywords appear in the sentence (whole words; most hits wins)."""
    s = (sentence or "").lower()
    best, hits = None, 0
    for k, (_label, words, _looks) in KINDS.items():
        n = sum(1 for w in words if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", s))
        if n > hits:
            best, hits = k, n
    return best


_NAME = re.compile(r"(?:called|named|name is|it's|it is)\s+[\"“']?([A-Z0-9][\w&'’ .-]{1,40}?)[\"”']?(?:[,.!]|$|\s+(?:in|at|for|a|an|the)\b)")


def guess_name(sentence: str) -> str:
    """'My café called Chinar Café in Srinagar' -> 'Chinar Café'; '' when unsure."""
    m = _NAME.search(sentence or "")
    return m.group(1).strip() if m else ""


_SUGGEST_PROMPT = (
    "You set up a small business's brand for a design tool. From the owner's one-sentence description, reply with "
    "JSON only: {\"name\": business name or \"\", \"kind\": a 1-3 word type, \"looks\": [three looks, each "
    "{\"label\": 2-3 words, \"colors\": [4 hex codes: primary, secondary (light background), accent, text], "
    "\"style\": image style words (max 25 words), \"voice\": writing tone (max 10 words), \"font\": one of "
    + ", ".join(FONT_KEYS) + "}]}. Make the three looks clearly different. Text colour must be readable on the "
    "secondary colour.")

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _clean_custom(data: dict) -> list[dict]:
    out = []
    for i, lk in enumerate((data.get("looks") or [])[:3]):
        hexes = [h for h in (lk.get("colors") or []) if isinstance(h, str) and _HEX.match(h)]
        if len(hexes) < 4:
            continue
        out.append({"id": f"custom-{i + 1}", "label": str(lk.get("label") or f"Look {i + 1}")[:40],
                    "colors": [{"role": r, "hex": h.upper()} for r, h in zip(ROLES, hexes)],
                    "style": str(lk.get("style") or "")[:300], "voice": str(lk.get("voice") or "")[:300],
                    "font": lk.get("font") if lk.get("font") in FONT_KEYS else "sans"})
    return out


async def suggest(sentence: str) -> dict:
    """{kind, label, name, looks[3]} for the setup screen. A known kind costs
    nothing; otherwise one cheap-model call (on the open meter) writes looks,
    and if that fails the startup/freelancer looks are a safe default."""
    sentence = (sentence or "").strip()[:400]
    kind = match_kind(sentence)
    if kind:
        label, _kw, looks = KINDS[kind]
        return {"kind": kind, "label": label, "name": guess_name(sentence), "looks": [lk.as_dict() for lk in looks]}
    try:
        from harness.billing import meter
        from harness.config import get_settings
        from harness.obs.tracing import cost_usd
        from harness.providers import get_provider
        from harness.providers.registry import get_model

        spec = get_model(get_settings().summary_model)
        base = get_provider()
        provider = (base.bound(spec.id, "low" if "low" in spec.efforts else None)
                    if spec is not None and hasattr(base, "bound") else base)
        turn = await provider.chat([{"role": "system", "content": _SUGGEST_PROMPT},
                                    {"role": "user", "content": sentence}], [])
        meter.add(cost_usd(getattr(provider, "model", get_settings().summary_model),
                           getattr(turn, "input_tokens", 0) or 0, getattr(turn, "output_tokens", 0) or 0,
                           getattr(turn, "cached_input_tokens", 0) or 0), "brand_suggest")
        text = (turn.text or "").strip()
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        looks = _clean_custom(data)
        if len(looks) == 3:
            return {"kind": "custom", "label": str(data.get("kind") or "Your business")[:40],
                    "name": str(data.get("name") or guess_name(sentence))[:80], "looks": looks}
    except Exception as e:  # noqa: BLE001 - fall back to a sensible default
        log.warning("brand suggestion failed", error=str(e)[:200])
    label, _kw, looks = KINDS["freelancer" if re.search(r"\b(i am|i'm|my work|myself)\b", sentence, re.I) else "startup"]
    return {"kind": "custom", "label": "Your business", "name": guess_name(sentence),
            "looks": [lk.as_dict() for lk in looks]}
