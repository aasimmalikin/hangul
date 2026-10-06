"""Markdown answers -> WhatsApp text, and splitting long answers.

WhatsApp has its own light formatting (*bold*, _italic_, ~strike~, ```mono```)
and no tables, headings or link markup, and a message holds at most 4,096
characters.
"""

import re

MAX_CHARS = 4096
LIMIT = 3900              # leave room for "(1/3)" and safety


def to_whatsapp(md: str) -> str:
    text = md.replace("\r\n", "\n")
    code_blocks: list[str] = []

    def keep_code(m: re.Match) -> str:
        code_blocks.append(m.group(1).strip("\n"))
        return f"\x00{len(code_blocks) - 1}\x00"
    text = re.sub(r"```[a-zA-Z0-9_-]*\n?(.*?)```", keep_code, text, flags=re.S)
    # italics first (*x* -> _x_), so the bold made next (**x** -> *x*) isn't turned into italics
    text = re.sub(r"(?<![*\w])\*(?!\s)([^*\n]+?)\*(?![*\w])", r"_\1_", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"*{m.group(1) or m.group(2)}*", text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.M)                    # headings -> bold line
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1: \2", text)                     # images -> text + link
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)} ({m.group(2)})", text)
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.M)                           # bullets
    text = re.sub(r"^\|?\s*:?-{3,}.*$", "", text, flags=re.M)                       # table rules
    text = re.sub(r"^\|(.+)\|\s*$", lambda m: " · ".join(c.strip() for c in m.group(1).split("|")), text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return re.sub(r"\x00(\d+)\x00", lambda m: f"```{code_blocks[int(m.group(1))]}```", text)


def split(text: str, limit: int = LIMIT) -> list[str]:
    """Chunks of at most ``limit`` characters, broken at paragraphs, then lines,
    then words; numbered "(1/3)" when there is more than one."""
    if len(text) <= limit:
        return [text]
    parts, rest = [], text
    while len(rest) > limit:
        cut = max(rest.rfind("\n\n", 0, limit), rest.rfind("\n", 0, limit))
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    n = len(parts)
    return [f"{p}\n\n({i}/{n})" for i, p in enumerate(parts, 1)]


def one_line(text: str, limit: int = 200) -> str:
    """Template variables may not contain newlines, tabs or 4+ spaces in a row."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
