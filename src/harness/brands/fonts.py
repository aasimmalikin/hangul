"""The four brand fonts (SIL Open Font License, bundled in ``fonts/``) and
glyph fallback: text the brand font can't draw (Hindi in a Latin display
font, say) is set in Poppins, which covers Devanagari, then DejaVu."""

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

DIR = Path(__file__).parent / "fonts"

# key -> (file, variable-font instance or None)
FONTS: dict[str, tuple[str, str | None]] = {
    "sans": ("Poppins-Bold.ttf", None),
    "serif": ("PlayfairDisplay.ttf", "Bold"),
    "script": ("Caveat.ttf", "Bold"),
    "display": ("Anton-Regular.ttf", None),
}
FALLBACK = "sans"


def _dejavu() -> str | None:
    from harness.tools.builtin.files import FONT_DIRS
    for d in FONT_DIRS:
        p = Path(d) / "DejaVuSans-Bold.ttf"
        if p.is_file():
            return str(p)
    return None


@lru_cache(maxsize=8)
def _cmap(path: str) -> frozenset[int]:
    from fontTools.ttLib import TTFont
    return frozenset(TTFont(path).getBestCmap())


def _path(key: str) -> str:
    return str(DIR / FONTS.get(key, FONTS[FALLBACK])[0])


def covers(key: str, text: str) -> bool:
    cmap = _cmap(_path(key))
    return all(ord(c) in cmap for c in text if not c.isspace())


@lru_cache(maxsize=128)
def _load(path: str, instance: str | None, size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM
                           if ImageFont.core.HAVE_RAQM else ImageFont.Layout.BASIC)
    if instance:
        try:
            f.set_variation_by_name(instance)
        except (OSError, ValueError):
            pass
    return f


def font_for(key: str, text: str, size: int) -> ImageFont.FreeTypeFont:
    """The brand font if it can draw every character of ``text``, else the fallback."""
    size = max(8, int(size))
    if key not in FONTS:
        key = FALLBACK
    if covers(key, text):
        return _load(_path(key), FONTS[key][1], size)
    if covers(FALLBACK, text):
        return _load(_path(FALLBACK), None, size)
    dv = _dejavu()
    return _load(dv, None, size) if dv else _load(_path(FALLBACK), None, size)
