"""Deterministic prompt-injection detector.

Not a model: a normaliser plus pattern families, each with a weight. It is
fast enough to run on every user message and every tool result, and its
verdict is explainable ("override_instructions, hidden_text"). A model-based
screen (classifier.py) can sit on top for the grey zone."""

import base64
import re
import unicodedata
from dataclasses import dataclass, field

# characters that hide text from a human reader but not from a model
ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff\u180e"
BIDI = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
TAG_CHARS = re.compile(r"[\U000e0000-\U000e007f]")        # Unicode "tag" block: invisible ASCII
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# each family: (name, weight, patterns); score = 1 - prod(1 - w) over hits
FAMILIES: list[tuple[str, float, list[str]]] = [
    ("override_instructions", 0.9, [
        r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|rules?|directions?)",
        r"\bdisregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\b",
        r"\bforget\s+(everything|all|your)\s+(you\s+were\s+told|previous|prior|instructions?)",
        r"\bnew\s+instructions?\s*:", r"\byour\s+(new|real|true|actual)\s+(instructions?|task|goal|objective)\s+(is|are)\b",
        r"\boverride\s+(the\s+)?(system|previous|prior)\b",
        r"\bfrom\s+now\s+on\s*,?\s*(you|ignore|act|respond)",
    ]),
    ("role_hijack", 0.7, [
        r"\byou\s+are\s+now\s+(a|an|the|in)\b", r"\bact\s+as\s+(if\s+you\s+(are|were)|a|an)\b",
        r"\bpretend\s+(to\s+be|you\s+are|that\s+you)\b", r"\b(developer|debug|god|admin|jailbreak)\s+mode\b",
        r"\bDAN\b", r"\bsystem\s*(prompt|message)\s*:", r"^\s*(system|assistant)\s*:\s", r"<\|?(im_start|system|endoftext)\|?>",
    ]),
    ("assistant_addressed", 0.55, [
        r"\b(hey|hello|hi|attention|note\s+to|dear|important\s+(message|note)\s+(for|to)|addendum\s+for|message\s+for)\s*,?\s*(the\s+|any\s+)?(ai|assistant|llm|model|chatbot|language\s+models?|claude|gpt|gemini|hangul)s?\b",
        r"\bthe\s+(assistant|ai|model|agent)\s+(must|should|will|needs?\s+to|has\s+to|is\s+to)\b",
        r"\b(ai|assistant|llm|language\s+model)\s*[:,]\s*(you\s+must|please|do\s+not|never|always)\b",
        r"\bif\s+you\s+are\s+an?\s+(ai|llm|language\s+model|assistant)\b",
        r"\bthis\s+(message|instruction|note)\s+is\s+for\s+the\s+(ai|assistant|model)\b",
    ]),
    ("exfiltration", 0.85, [
        r"\b(send|post|forward|upload|transmit|leak|exfiltrate|email)\b.{0,60}\b(api[\s_-]?key|secret|token|password|credential|system\s+prompt|conversation|chat\s+history|these\s+instructions)",
        r"\b(reveal|print|repeat|show|output|display|dump)\b.{0,40}\b(system\s+prompt|your\s+instructions|initial\s+prompt|hidden\s+prompt|api[\s_-]?key|secret|token)",
        r"\bencode\b.{0,40}\b(base64|hex|url)\b.{0,60}\b(send|include|append|put)\b",
        r"!\[[^\]]*\]\((https?://[^)]*\?[^)]*)\)",                       # markdown image with a query string
        r"https?://[^\s)\"']+\?[^\s)\"']*(data|q|token|key|secret|c|p)=[A-Za-z0-9+/=%_-]{24,}",
    ]),
    ("tool_coercion", 0.75, [
        r"\b(call|invoke|run|use|execute)\s+(the\s+)?(tool|function)\s+[`'\"]?\w+",
        r"\b(write|save|create|delete|remove|overwrite|move)\s+(a|an|the|every|all)?\s*(other\s+)?(file|files)\b.{0,40}\b(named|called|to|at|here|with)\b",
        r"\b(call|calling|invoke|invoking|run|running|use|using)\s+[`'\"]?[a-z]+_[a-z_]+\b",
        r"\bvault_(request|mutate)\b", r"\bfilesystem__\w+\b", r"\bweb_search\s*\(", r"\barxiv_\w+\s*\(",
        r"\b(approve|confirm|click\s+approve)\b.{0,40}\b(automatically|without\s+asking|on\s+behalf)",
    ]),
    ("covert", 0.6, [
        r"\b(do\s+(this|it|so)\s+)?(silently|quietly|covertly|discreetly)\b",
        r"\b(do\s+not|don't|never)\s+(mention|tell|reveal|inform|disclose)\b.{0,30}\b(user|this|it|anyone)\b",
        r"\b(the\s+)?user\s+(has\s+)?(pre-?approved|already\s+approved|consented|authorised|authorized)\b",
    ]),
    ("hidden_text", 0.6, [
        r"<!--.{20,}?-->", r"<(span|div|p)[^>]*(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|color\s*:\s*(white|#fff))",
        r"\[\s*(hidden|secret|invisible)\s*(instructions?|text|note)\s*\]",
    ]),
]
COMPILED = [(name, w, [re.compile(p, re.IGNORECASE | re.DOTALL) for p in pats]) for name, w, pats in FAMILIES]

BASE64_BLOB = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{80,}={0,2}(?![A-Za-z0-9+/])")


@dataclass
class Finding:
    score: float                       # 0..1
    families: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    hidden_chars: int = 0
    decoded_hits: list[str] = field(default_factory=list)

    @property
    def severity(self) -> str:
        if self.score >= 0.8:
            return "high"
        if self.score >= 0.45:
            return "medium"
        if self.score > 0:
            return "low"
        return "none"

    def as_dict(self) -> dict:
        return {"score": round(self.score, 3), "severity": self.severity, "families": self.families,
                "reasons": self.reasons[:8], "hidden_chars": self.hidden_chars}


def normalize(text: str) -> tuple[str, int]:
    """NFKC-fold, drop zero-width / bidi / tag / control characters. Returns
    the clean text and how many hidden characters were removed (itself a
    signal: honest documents do not carry hundreds of zero-width joiners)."""
    if not text:
        return "", 0
    before = len(text)
    text = TAG_CHARS.sub("", text)
    text = CONTROL.sub("", text)
    text = "".join(ch for ch in text if ch not in ZERO_WIDTH and ch not in BIDI)
    text = unicodedata.normalize("NFKC", text)
    return text, before - len(text)


def _decode_blobs(text: str, limit: int = 3) -> list[str]:
    out = []
    for m in BASE64_BLOB.finditer(text):
        if len(out) >= limit:
            break
        try:
            raw = base64.b64decode(m.group(0) + "=" * (-len(m.group(0)) % 4), validate=False)
            s = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if s.isprintable() or "\n" in s:
            out.append(s[:500])
    return out


def scan(text: str, *, decode: bool = True) -> Finding:
    """Score how much `text` looks like instructions aimed at the assistant."""
    clean, hidden = normalize(text or "")
    if not clean.strip():
        return Finding(score=0.0, hidden_chars=hidden)
    families: list[str] = []
    reasons: list[str] = []
    miss = 1.0
    for name, weight, pats in COMPILED:
        hit = next((p for p in pats if p.search(clean)), None)
        if hit is not None:
            families.append(name)
            m = hit.search(clean)
            reasons.append(f"{name}: '{clean[max(0, m.start()-20):m.end()+20].strip()[:90]}'")
            miss *= 1 - weight
    decoded_hits: list[str] = []
    if decode:
        for s in _decode_blobs(clean):
            inner = scan(s, decode=False)
            if inner.score >= 0.45:
                decoded_hits.append(s[:120])
                families.append("encoded_payload")
                reasons.append(f"encoded_payload: base64 decodes to instruction-like text ({inner.families})")
                miss *= 1 - 0.8
                break
    if hidden >= 8:
        families.append("hidden_chars")
        reasons.append(f"hidden_chars: {hidden} zero-width/bidi/tag characters removed")
        miss *= 1 - (0.5 if hidden < 50 else 0.8)
    return Finding(score=round(1 - miss, 3), families=families, reasons=reasons,
                   hidden_chars=hidden, decoded_hits=decoded_hits)
