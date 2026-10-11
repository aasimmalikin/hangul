"""Colours from a logo, with Pillow only (no AI, no cost): the few strongest
colours, ignoring transparent and near-white/near-black background pixels,
offered to the user as the brand's colours to accept or change."""

from pathlib import Path

from PIL import Image

from harness.brands.templates import ROLES


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _lum(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def colors_from_logo(path: Path | str, n: int = 4) -> list[dict]:
    """[{role, hex}] for primary / secondary / accent / text. The most common
    non-background colour is primary; the lightest is the background
    (secondary, else a warm off-white); text is dark enough to read on it."""
    with Image.open(path) as im:
        im = im.convert("RGBA")
        im.thumbnail((160, 160))
        data = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
        pixels = [p[:3] for p in data if p[3] > 128]
    if not pixels:
        return []
    keep = [p for p in pixels if 0.06 < _lum(p) < 0.94] or pixels
    small = Image.new("RGB", (len(keep), 1))
    small.putdata(keep)
    q = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    found = [tuple(pal[i * 3:i * 3 + 3]) for _c, i in counts]
    found = [c for i, c in enumerate(found) if all(sum(abs(a - b) for a, b in zip(c, o)) > 60 for o in found[:i])]
    primary = found[0]
    accent = found[1] if len(found) > 1 else primary
    light = max(found, key=_lum)
    secondary = light if _lum(light) > 0.85 else (0xF6, 0xF1, 0xEA)
    text = min(found, key=_lum) if _lum(min(found, key=_lum)) < 0.25 else (0x22, 0x1E, 0x1B)
    return [{"role": r, "hex": _hex(c)} for r, c in zip(ROLES, (primary, secondary, accent, text))][:n]
