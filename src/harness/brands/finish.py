"""Finishing a picture for a brand, with Pillow only: no AI, so it's exact,
instant and free to run (the Brand Studio's live preview renders on every
change for that reason).

A post is a photo, a **layout** (``LAYOUTS``: where the words, price, call
to action and logo go), the brand's colours and font, and one or more
**sizes** (``SIZES``: every platform's shape). Words are auto-fitted
(shrink, then wrap, then trim -- never off the image), the real logo file is
stamped (never redrawn), and on 9:16 sizes nothing important sits in the
top/bottom strips Instagram and WhatsApp cover with their own buttons.
Image models still garble text; this is how a post's words come out spelled
right, in the brand's font.
"""

import io
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from harness.brands.fonts import font_for
from harness.db.brands import BrandRow

# key -> (width, height, label)
SIZES: dict[str, tuple[int, int, str]] = {
    "post": (1080, 1080, "Instagram post 1:1"),
    "portrait": (1080, 1350, "Instagram feed 4:5"),
    "story": (1080, 1920, "Story · Reel cover · WhatsApp status"),
    "landscape": (1200, 628, "Facebook · LinkedIn"),
    "x": (1600, 900, "X (Twitter)"),
    "youtube": (1280, 720, "YouTube thumbnail"),
    "pinterest": (1000, 1500, "Pinterest pin"),
    "a4": (2480, 3508, "A4 print"),
}
DEFAULT_SIZES = ("post", "story")
CAROUSEL_SIZES = ("post", "portrait")
# top / bottom share of a 9:16 frame covered by the app's own buttons
SAFE_9_16 = (0.13, 0.18)

# key -> (label, what it's for, which words it uses)
LAYOUTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "band": ("Classic band", "Your words on a colour band", ("headline", "subline", "price", "cta")),
    "top_banner": ("Top banner", "Headline across the top", ("headline", "subline", "price", "cta")),
    "offer": ("Offer badge", "A big badge for a price or a sale", ("headline", "subline", "price", "cta")),
    "quote": ("Quote card", "A review or a saying, centre stage", ("headline", "subline")),
    "event": ("Event", "Name, date and place over the photo", ("headline", "subline", "price", "cta")),
    "showcase": ("Product showcase", "The product framed on your colours", ("headline", "subline", "price", "cta")),
    "split": ("Before / after", "Two photos side by side", ("headline", "subline")),
    "minimal": ("Minimal", "Just the photo, your logo and handle", ("headline",)),
}

NEUTRAL = BrandRow(id=0, name="", colors=[{"role": "primary", "hex": "#222222"}, {"role": "secondary", "hex": "#FAFAFA"},
                                          {"role": "accent", "hex": "#E0A458"}, {"role": "text", "hex": "#222222"}])

RGB = tuple[int, int, int]


@dataclass
class Words:
    headline: str = ""
    subline: str = ""
    price: str = ""
    cta: str = ""

    @classmethod
    def of(cls, d: dict | None) -> "Words":
        d = d or {}
        return cls(*(str(d.get(k) or "").strip()[:n] for k, n in
                     (("headline", 160), ("subline", 200), ("price", 24), ("cta", 40))))


# ------------------------------------------------------------ colour

def _rgb(hex_: str) -> RGB:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lum(rgb: RGB) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: RGB, b: RGB) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ink_on(bg: RGB, *candidates: RGB) -> RGB:
    """The candidate that reads best on ``bg`` (white/near-black as a last resort)."""
    options = [*candidates, (255, 255, 255), (20, 20, 20)]
    good = [c for c in candidates if contrast(bg, c) >= 4.5]
    return good[0] if good else max(options, key=lambda c: contrast(bg, c))


def _shade(c: RGB, k: float) -> RGB:
    return tuple(max(0, min(255, round(v * k))) for v in c)  # type: ignore[return-value]


@dataclass
class Palette:
    primary: RGB
    secondary: RGB
    accent: RGB
    text: RGB

    @classmethod
    def of(cls, b: BrandRow) -> "Palette":
        return cls(_rgb(b.color("primary")), _rgb(b.color("secondary", "#FAFAFA")),
                   _rgb(b.color("accent", b.color("primary"))), _rgb(b.color("text", "#222222")))


# ------------------------------------------------------------ text

def _wrap(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and draw.textlength(trial, font=f) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def fit(draw: ImageDraw.ImageDraw, text: str, font_key: str, max_w: float, max_h: float, start: float,
        min_size: float, max_lines: int = 2, leading: float = 1.15):
    """(font, lines): the largest size whose wrapped lines fit the box, at most
    ``max_lines``; at the smallest size, the overflow is trimmed with "…"."""
    text = " ".join(text.split())
    size = int(start)
    while size >= min_size:
        f = font_for(font_key, text, size)
        lines = _wrap(draw, text, f, int(max_w))
        if (len(lines) <= max_lines and all(draw.textlength(ln, font=f) <= max_w for ln in lines)
                and len(lines) * size * leading <= max_h):
            return f, lines
        size = int(size * 0.92)
    f = font_for(font_key, text, int(min_size))
    lines = _wrap(draw, text, f, int(max_w))[:max_lines] or [""]
    last = lines[-1]
    if " ".join(lines) != text:
        while last and draw.textlength(last + "…", font=f) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return f, lines


def _text_block(draw, x, y, lines, f, fill, leading=1.15, anchor_x="l", width=0):
    for ln in lines:
        if anchor_x == "m":
            draw.text((x + width / 2, y), ln, font=f, fill=fill, anchor="ma")
        else:
            draw.text((x, y), ln, font=f, fill=fill)
        y += f.size * leading
    return y


def _pill(draw, x, y, text, size, fill, ink, *, anchor="l", font_key="sans") -> tuple[float, float, float, float]:
    """A rounded label; ``anchor`` l / r / m for where x is. Returns its box."""
    f = font_for(font_key, text, size)
    tw = draw.textlength(text, font=f)
    h = f.size * 1.55
    w = tw + h * 0.9
    x0 = x if anchor == "l" else x - w if anchor == "r" else x - w / 2
    draw.rounded_rectangle((x0, y, x0 + w, y + h), radius=h / 2, fill=fill)
    draw.text((x0 + w / 2, y + h / 2), text, font=f, fill=ink, anchor="mm")
    return x0, y, x0 + w, y + h


# ------------------------------------------------------------ images

def _cover(src: Image.Image, w: int, h: int, focus: tuple[float, float]) -> Image.Image:
    return ImageOps.fit(src.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS,
                        centering=(min(max(focus[0], 0), 1), min(max(focus[1], 0), 1)))


def _scrim(img: Image.Image, y0: float, y1: float, color: RGB, a0: int, a1: int) -> None:
    """A vertical gradient of ``color`` from alpha a0 at y0 to a1 at y1."""
    y0, y1 = int(max(0, y0)), int(min(img.height, y1))
    if y1 <= y0:
        return
    grad = Image.new("L", (1, y1 - y0))
    grad.putdata([round(a0 + (a1 - a0) * i / max(1, y1 - y0 - 1)) for i in range(y1 - y0)])
    mask = grad.resize((img.width, y1 - y0))
    img.paste(Image.new("RGB", (img.width, y1 - y0), color), (0, y0), mask)


def _stamp_logo(img: Image.Image, logo: Image.Image | None, box: float, x: float, y: float, plate: RGB | None,
                *, anchor: str = "tr") -> tuple[float, float, float, float] | None:
    """Paste the logo inside a box; ``anchor`` (t/m/b + l/m/r) names the point (x, y) is."""
    if logo is None:
        return None
    lg = logo.convert("RGBA")
    lg.thumbnail((int(box), int(box)), Image.Resampling.LANCZOS)
    m = round(box * 0.12) if plate else 0
    w, h = lg.width + 2 * m, lg.height + 2 * m
    x0 = x - w if anchor[1] == "r" else x - w / 2 if anchor[1] == "m" else x
    y0 = y - h if anchor[0] == "b" else y - h / 2 if anchor[0] == "m" else y
    x0, y0 = int(x0), int(y0)
    if plate is not None:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=max(4, m), fill=225)
        img.paste(Image.new("RGB", (w, h), plate), (x0, y0), mask)
    img.paste(lg, (x0 + m, y0 + m), lg)
    return x0, y0, x0 + w, y0 + h


def _name_tag(draw, brand: BrandRow, x, y, unit, pal: Palette, anchor="r"):
    if brand.name:
        _pill(draw, x, y, brand.name, unit * 0.036, pal.secondary, ink_on(pal.secondary, pal.primary, pal.text),
              anchor=anchor, font_key=brand.font)


def footer_line(brand: BrandRow) -> str:
    return "  ·  ".join(x for x in (brand.handle and ("@" + brand.handle.lstrip("@")), brand.website, brand.footer) if x)


# ------------------------------------------------------------ the frame every layout draws in

@dataclass
class Frame:
    img: Image.Image
    draw: ImageDraw.ImageDraw
    w: int
    h: int
    unit: float
    pad: float
    top: float           # content may start here (below the 9:16 safe strip)
    bottom: float        # ... and must end here
    pal: Palette
    brand: BrandRow
    logo: Image.Image | None


def _frame(img: Image.Image, brand: BrandRow, logo, safe: tuple[float, float]) -> Frame:
    w, h = img.size
    unit = min(w, h)
    pad = unit * 0.055
    return Frame(img, ImageDraw.Draw(img), w, h, unit, pad, h * safe[0] + pad, h - h * safe[1] - pad,
                 Palette.of(brand), brand, logo)


def _measure(fr: Frame, words: Words, width: float, max_h: float, dense: float = 1.0) -> tuple[list, float]:
    """The band's contents fitted into ``max_h``: ([(kind, font, lines, leading)], total height)."""
    d, unit = fr.draw, fr.unit
    items: list = []
    gap = unit * 0.018
    if words.headline:
        f, lines = fit(d, words.headline, fr.brand.font, width, max_h * (0.6 if words.subline else 0.8),
                       unit * 0.092 * dense, unit * 0.034, max_lines=2)
        items.append(("head", f, lines, 1.15))
    if words.subline:
        f, lines = fit(d, words.subline, "sans", width, max_h * 0.25, unit * 0.042 * dense, unit * 0.022, max_lines=2)
        items.append(("sub", f, lines, 1.3))
    if words.cta:
        items.append(("cta", None, [words.cta + "  →"], 0))
    foot = footer_line(fr.brand)
    if foot:
        f = font_for("sans", foot, unit * 0.026)
        items.append(("foot", f, [foot], 1.3))
    total = 0.0
    for i, (kind, f, lines, lead) in enumerate(items):
        total += (gap * (1.4 if kind == "cta" else 1) if i else 0)
        total += unit * 0.042 * 1.55 if kind == "cta" else f.size * lead * len(lines)
    return items, total


def _draw_items(fr: Frame, items: list, y: float, ink: RGB, align: str = "l", x: float | None = None) -> float:
    d, pal, unit, pad = fr.draw, fr.pal, fr.unit, fr.pad
    x = pad if x is None else x
    width = fr.w - 2 * x
    gap = unit * 0.018
    for i, (kind, f, lines, lead) in enumerate(items):
        if i:
            y += gap * (1.4 if kind == "cta" else 1)
        if kind == "cta":
            _pill(d, (fr.w / 2) if align == "m" else x, y, lines[0], unit * 0.042, pal.accent,
                  ink_on(pal.accent, pal.text, pal.secondary), anchor="m" if align == "m" else "l")
            y += unit * 0.042 * 1.55
        else:
            y = _text_block(d, x, y, lines, f, ink, lead, anchor_x="m" if align == "m" else "l", width=width)
    return y


def _bottom_band(fr: Frame, words: Words, *, share: float = 0.18, dense: float = 1.0, align: str = "l") -> float | None:
    """The words on a primary band at the bottom: full width, or on a 9:16 frame a
    rounded card that ends at the safe line (the app's reply bar covers below it).
    Returns the band's top, or None when there are no words."""
    if not (words.headline or words.subline or words.cta):
        return None
    vpad = fr.pad * 0.8
    story = fr.bottom < fr.h - fr.pad * 1.5
    inset = fr.pad * 1.5 if story else fr.pad
    # the photo is the post: the band never takes more than ~40% of the frame
    items, total = _measure(fr, words, fr.w - 2 * inset, fr.h * (0.4 if fr.h <= fr.w * 1.3 else 0.32) - 2 * vpad, dense)
    band = max(total + 2 * vpad, fr.unit * share)
    ink = ink_on(fr.pal.primary, fr.pal.secondary, fr.pal.text)
    if story:
        y1 = fr.bottom + fr.pad * 0.5
        y0 = y1 - band
        _scrim(fr.img, y0 - fr.unit * 0.15, fr.h, (0, 0, 0), 0, 120)
        fr.draw.rounded_rectangle((fr.pad * 0.5, y0, fr.w - fr.pad * 0.5, y1), radius=fr.unit * 0.04, fill=fr.pal.primary)
        _draw_items(fr, items, y0 + (band - total) / 2, ink, align, x=inset)
        return y0
    y0 = fr.h - band
    fr.draw.rectangle((0, y0, fr.w, fr.h), fill=fr.pal.primary)
    _draw_items(fr, items, y0 + (band - total) / 2, ink, align)
    return y0


def _price(fr: Frame, words: Words, x: float, y: float, anchor="l"):
    if words.price:
        _pill(fr.draw, x, y, words.price, fr.unit * 0.06, fr.pal.accent, ink_on(fr.pal.accent, fr.pal.text, fr.pal.secondary),
              anchor=anchor)


def _corner_logo(fr: Frame, anchor="tr"):
    x = fr.w - fr.pad if anchor[1] == "r" else fr.pad
    y = fr.top if anchor[0] == "t" else fr.bottom
    if not _stamp_logo(fr.img, fr.logo, fr.unit * 0.15, x, y, fr.pal.secondary, anchor=anchor):
        _name_tag(fr.draw, fr.brand, x, y if anchor[0] == "t" else y - fr.unit * 0.06, fr.unit, fr.pal,
                  anchor="r" if anchor[1] == "r" else "l")


# ------------------------------------------------------------ layouts

def _band(fr: Frame, words: Words, **_):
    _bottom_band(fr, words, share=0.2)
    _price(fr, words, fr.pad, fr.top)
    _corner_logo(fr, "tr")


def _top_banner(fr: Frame, words: Words, **_):
    if words.headline or words.subline or words.cta:
        vpad = fr.pad * 0.8
        items, total = _measure(fr, words, fr.w - 2 * fr.pad, fr.h * 0.45 - 2 * vpad)
        y1 = fr.top - fr.pad + total + 2 * vpad
        fr.draw.rectangle((0, 0, fr.w, y1), fill=fr.pal.primary)
        _draw_items(fr, items, fr.top - fr.pad + vpad, ink_on(fr.pal.primary, fr.pal.secondary, fr.pal.text))
    _price(fr, words, fr.pad, fr.bottom - fr.unit * 0.093)
    _corner_logo(fr, "br")


def _offer(fr: Frame, words: Words, **_):
    _bottom_band(fr, Words(words.headline, words.subline, "", words.cta), share=0.16, dense=0.85)
    if words.price:
        r = fr.unit * 0.19
        cx, cy = fr.w - fr.pad - r, fr.top + r
        d, pal = fr.draw, fr.pal
        d.ellipse((cx - r * 1.08, cy - r * 1.08, cx + r * 1.08, cy + r * 1.08), fill=pal.secondary)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=pal.accent)
        ink = ink_on(pal.accent, pal.text, pal.secondary)
        f, lines = fit(d, words.price, "display" if fr.brand.font != "script" else "sans", r * 1.5, r * 1.3,
                       r * 0.62, r * 0.2, max_lines=2, leading=1.0)
        y = cy - f.size * len(lines) / 2
        for ln in lines:
            d.text((cx, y), ln, font=f, fill=ink, anchor="ma")
            y += f.size
    _corner_logo(fr, "tl")


def _quote(fr: Frame, words: Words, src: Image.Image, **_):
    pal, d = fr.pal, fr.draw
    bg = fr.img.filter(ImageFilter.GaussianBlur(fr.unit * 0.02))
    fr.img.paste(Image.blend(bg, Image.new("RGB", bg.size, _shade(pal.primary, 0.55)), 0.72))
    ink = ink_on(_shade(pal.primary, 0.55), (255, 255, 255), pal.secondary)
    qf = font_for("serif", "“", fr.unit * 0.3)
    d.text((fr.w / 2, fr.top + fr.unit * 0.02), "“", font=qf, fill=pal.accent, anchor="ma")
    box_top = fr.top + fr.unit * 0.25
    box_bottom = fr.bottom - fr.unit * (0.24 if fr.logo or fr.brand.name else 0.08)
    if words.headline:
        f, lines = fit(d, words.headline, fr.brand.font if fr.brand.font != "display" else "serif", fr.w - 3 * fr.pad,
                       (box_bottom - box_top) * 0.8, fr.unit * 0.085, fr.unit * 0.034, max_lines=6, leading=1.25)
        block = f.size * 1.25 * len(lines)
        y = box_top + ((box_bottom - box_top) * 0.8 - block) / 2
        y = _text_block(d, fr.pad, y, lines, f, ink, 1.25, anchor_x="m", width=fr.w - 2 * fr.pad)
        if words.subline:
            sf, sl = fit(d, "— " + words.subline.lstrip("—- "), "sans", fr.w - 3 * fr.pad, fr.unit * 0.1,
                         fr.unit * 0.04, fr.unit * 0.022, max_lines=2)
            _text_block(d, fr.pad, y + fr.unit * 0.03, sl, sf, pal.accent, 1.3, anchor_x="m", width=fr.w - 2 * fr.pad)
    foot = footer_line(fr.brand)
    logo_bottom = fr.bottom - (fr.unit * 0.05 if foot else 0)
    if not _stamp_logo(fr.img, fr.logo, fr.unit * 0.11, fr.w / 2, logo_bottom, pal.secondary, anchor="bm"):
        _name_tag(d, fr.brand, fr.w / 2, logo_bottom - fr.unit * 0.06, fr.unit, pal, anchor="m")
    if foot:
        ff = font_for("sans", foot, fr.unit * 0.024)
        d.text((fr.w / 2, fr.bottom + fr.pad * 0.3), foot, font=ff, fill=ink, anchor="md")


def _event(fr: Frame, words: Words, **_):
    pal, d = fr.pal, fr.draw
    dark = _shade(pal.primary, 0.35)
    scrim_from = fr.h * 0.38
    ink = (255, 255, 255) if contrast(dark, (255, 255, 255)) >= 4.5 else pal.secondary
    width = fr.w - 2 * fr.pad
    y = fr.bottom
    foot = footer_line(fr.brand)
    parts = []
    if foot:
        ff = font_for("sans", foot, fr.unit * 0.026)
        parts.append(("foot", ff, [foot], 1.3))
    if words.cta or words.price:
        parts.append(("cta", None, [], 0))
    if words.subline:
        sf, sl = fit(d, words.subline, "sans", width, fr.unit * 0.13, fr.unit * 0.045, fr.unit * 0.024, max_lines=2)
        parts.append(("sub", sf, sl, 1.3))
    if words.headline:
        hf, hl = fit(d, words.headline, fr.brand.font, width, fr.h * 0.3, fr.unit * 0.12, fr.unit * 0.04, max_lines=3,
                     leading=1.08)
        parts.append(("head", hf, hl, 1.08))
    gap = fr.unit * 0.022
    height = sum((fr.unit * 0.045 * 1.55 if k == "cta" else f.size * lead * len(ls)) + gap for k, f, ls, lead in parts)
    scrim_from = min(scrim_from, fr.bottom - height - fr.unit * 0.3)
    _scrim(fr.img, scrim_from, fr.h, dark, 0, 240)
    d = fr.draw = ImageDraw.Draw(fr.img)
    for kind, f, lines, lead in parts:          # bottom-up
        if kind == "cta":
            h = fr.unit * 0.045 * 1.55
            y -= h
            x = fr.pad
            if words.cta:
                x = _pill(d, x, y, words.cta + "  →", fr.unit * 0.045, pal.accent, ink_on(pal.accent, pal.text, pal.secondary))[2] + gap
            if words.price:
                _pill(d, x, y, words.price, fr.unit * 0.045, pal.secondary, ink_on(pal.secondary, pal.primary, pal.text))
            y -= gap
            continue
        block = f.size * lead * len(lines)
        y -= block
        _text_block(d, fr.pad, y, lines, f, pal.accent if kind == "sub" and contrast(dark, pal.accent) >= 3 else ink, lead)
        if kind == "head":
            d.rectangle((fr.pad, y - gap * 1.4, fr.pad + fr.unit * 0.12, y - gap * 1.4 + fr.unit * 0.012), fill=pal.accent)
        y -= gap
    _corner_logo(fr, "tl")


def _showcase(fr: Frame, words: Words, src: Image.Image, focus=(0.5, 0.5), **_):
    pal, d = fr.pal, fr.draw
    d.rectangle((0, 0, fr.w, fr.h), fill=pal.secondary)
    ink = ink_on(pal.secondary, pal.text, pal.primary)
    width = fr.w - 2 * fr.pad
    y = fr.top
    if fr.logo is not None:
        logo_box = _stamp_logo(fr.img, fr.logo, fr.unit * 0.1, fr.w / 2, y + fr.unit * 0.05, None, anchor="mm")
        y = logo_box[3] + fr.unit * 0.02
    elif fr.brand.name:
        nf = font_for(fr.brand.font, fr.brand.name, fr.unit * 0.04)
        d.text((fr.w / 2, y), fr.brand.name, font=nf, fill=pal.primary, anchor="ma")
        y += nf.size * 1.4
    if words.headline:
        hf, hl = fit(d, words.headline, fr.brand.font, width, fr.h * 0.16, fr.unit * 0.085, fr.unit * 0.032, max_lines=2)
        y = _text_block(d, fr.pad, y, hl, hf, ink, anchor_x="m", width=width) + fr.unit * 0.015
    tail = (fr.unit * 0.05 if words.subline else 0) + (fr.unit * 0.075 if words.cta else 0) \
        + (fr.unit * 0.04 if footer_line(fr.brand) else 0)
    card_bottom = fr.bottom - tail - fr.unit * 0.02
    cw = fr.w * 0.8
    ch = max(fr.unit * 0.25, card_bottom - y - fr.unit * 0.02)
    cx0, cy0 = (fr.w - cw) / 2, y + fr.unit * 0.02
    photo = _cover(src, int(cw), int(ch), focus)
    shadow = Image.new("L", (int(cw), int(ch)), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((0, 0, int(cw) - 1, int(ch) - 1), radius=int(fr.unit * 0.04), fill=255)
    soft = Image.new("L", fr.img.size, 0)
    soft.paste(shadow, (int(cx0), int(cy0 + fr.unit * 0.015)))
    soft = soft.filter(ImageFilter.GaussianBlur(fr.unit * 0.02)).point(lambda v: v * 0.35)
    fr.img.paste(_shade(pal.secondary, 0.55), (0, 0, fr.w, fr.h), soft)
    fr.img.paste(photo, (int(cx0), int(cy0)), shadow)
    d = fr.draw = ImageDraw.Draw(fr.img)
    if words.price:
        _pill(d, cx0 + cw - fr.unit * 0.03, cy0 + ch - fr.unit * 0.06, words.price, fr.unit * 0.055, pal.accent,
              ink_on(pal.accent, pal.text, pal.secondary), anchor="r")
    y = cy0 + ch + fr.unit * 0.035
    if words.subline:
        sf, sl = fit(d, words.subline, "sans", width, fr.unit * 0.06, fr.unit * 0.036, fr.unit * 0.022, max_lines=1)
        y = _text_block(d, fr.pad, y, sl, sf, ink, 1.3, anchor_x="m", width=width)
    if words.cta:
        _pill(d, fr.w / 2, y + fr.unit * 0.01, words.cta + "  →", fr.unit * 0.04, pal.primary,
              ink_on(pal.primary, pal.secondary, (255, 255, 255)), anchor="m")
        y += fr.unit * 0.075
    foot = footer_line(fr.brand)
    if foot:
        ff = font_for("sans", foot, fr.unit * 0.024)
        d.text((fr.w / 2, fr.bottom + fr.pad * 0.3), foot, font=ff, fill=ink, anchor="md")


def _split(fr: Frame, words: Words, src: Image.Image, src2: Image.Image | None = None, focus=(0.5, 0.5), **_):
    pal, d = fr.pal, fr.draw
    if src2 is not None:
        half = fr.w // 2
        fr.img.paste(_cover(src, half, fr.h, focus), (0, 0))
        fr.img.paste(_cover(src2, fr.w - half, fr.h, focus), (half, 0))
        d.rectangle((half - fr.unit * 0.006, 0, half + fr.unit * 0.006, fr.h), fill=pal.secondary)
        r = fr.unit * 0.04
        d.ellipse((half - r, fr.h * 0.45 - r, half + r, fr.h * 0.45 + r), fill=pal.accent)
        d.text((half, fr.h * 0.45), "⇆", font=font_for("sans", "⇆", r), fill=ink_on(pal.accent, pal.text, pal.secondary),
               anchor="mm")
        for x, label in ((fr.pad, "Before"), (half + fr.pad * 0.6, "After")):
            _pill(d, x, fr.top, label, fr.unit * 0.04, pal.secondary, ink_on(pal.secondary, pal.primary, pal.text))
    _bottom_band(fr, Words(words.headline, words.subline), share=0.14, align="m")
    if src2 is None:
        _corner_logo(fr, "tr")
    else:
        _stamp_logo(fr.img, fr.logo, fr.unit * 0.1, fr.w - fr.pad, fr.top, pal.secondary, anchor="tr")


def _minimal(fr: Frame, words: Words, **_):
    pal, d = fr.pal, fr.draw
    _scrim(fr.img, fr.h * 0.72, fr.h, (0, 0, 0), 0, 150)
    foot = footer_line(fr.brand) or fr.brand.name
    y = fr.bottom
    if foot:
        ff = font_for("sans", foot, fr.unit * 0.032)
        d.text((fr.pad, y), foot, font=ff, fill=(255, 255, 255), anchor="ld")
        y -= ff.size * 1.6
    if words.headline:
        _pill(d, fr.pad, y - fr.unit * 0.065, words.headline[:60], fr.unit * 0.042, pal.secondary,
              ink_on(pal.secondary, pal.primary, pal.text), font_key=fr.brand.font)
    _stamp_logo(fr.img, fr.logo, fr.unit * 0.13, fr.w - fr.pad, fr.bottom, pal.secondary, anchor="br")


DRAW = {"band": _band, "top_banner": _top_banner, "offer": _offer, "quote": _quote, "event": _event,
        "showcase": _showcase, "split": _split, "minimal": _minimal}


def render(src: Image.Image, brand: BrandRow, size: str | tuple[int, int], *, layout: str = "band",
           words: Words | dict | None = None, logo: Image.Image | None = None, focus: tuple[float, float] = (0.5, 0.45),
           src2: Image.Image | None = None, slide: str = "", scale: float = 1.0, **legacy) -> Image.Image:
    """One finished image. ``size`` is a SIZES key or (w, h); ``scale`` < 1
    renders a smaller copy of the same design (the live preview)."""
    if isinstance(words, dict) or words is None:
        words = Words.of(words or {k: legacy.get(k, "") for k in ("headline", "subline", "price", "cta")})
    w, h = SIZES[size][:2] if isinstance(size, str) else size
    w, h = max(64, round(w * scale)), max(64, round(h * scale))
    safe = SAFE_9_16 if abs(h / w - 16 / 9) < 0.02 else (0.0, 0.0)
    if layout not in DRAW:
        layout = "band"
    img = _cover(src, w, h, focus)
    fr = _frame(img, brand, logo, safe)
    DRAW[layout](fr, words, src=src, src2=src2, focus=focus)
    if slide:
        _pill(ImageDraw.Draw(fr.img), fr.pad, fr.top if not words.price or layout != "band" else fr.top + fr.unit * 0.1,
              slide, fr.unit * 0.034, fr.pal.secondary, ink_on(fr.pal.secondary, fr.pal.primary, fr.pal.text))
    return fr.img


def closing_slide(brand: BrandRow, size: str | tuple[int, int], *, logo: Image.Image | None = None, cta: str = "",
                  scale: float = 1.0) -> Image.Image:
    """The last carousel slide: logo, name, handle and a call to action on the brand's colours."""
    w, h = SIZES[size][:2] if isinstance(size, str) else size
    w, h = max(64, round(w * scale)), max(64, round(h * scale))
    pal = Palette.of(brand)
    img = Image.new("RGB", (w, h), pal.primary)
    d = ImageDraw.Draw(img)
    unit = min(w, h)
    ink = ink_on(pal.primary, pal.secondary, (255, 255, 255))
    y = h * 0.3
    box = _stamp_logo(img, logo, unit * 0.22, w / 2, y, pal.secondary, anchor="mm")
    y = (box[3] if box else y) + unit * 0.06
    if brand.name:
        f, lines = fit(d, brand.name, brand.font, w * 0.8, unit * 0.2, unit * 0.09, unit * 0.04)
        y = _text_block(d, 0, y, lines, f, ink, anchor_x="m", width=w)
    if brand.handle:
        hf = font_for("sans", brand.handle, unit * 0.045)
        d.text((w / 2, y + unit * 0.02), "@" + brand.handle.lstrip("@"), font=hf, fill=pal.accent if contrast(pal.primary, pal.accent) >= 3 else ink, anchor="ma")
        y += hf.size * 1.6 + unit * 0.02
    _pill(d, w / 2, y + unit * 0.04, (cta or brand.cta or "Follow for more") + "  →", unit * 0.045, pal.secondary,
          ink_on(pal.secondary, pal.primary, pal.text), anchor="m")
    if brand.website or brand.footer:
        line = "  ·  ".join(x for x in (brand.website, brand.footer) if x)
        ff = font_for("sans", line, unit * 0.028)
        d.text((w / 2, h - unit * 0.08), line, font=ff, fill=ink, anchor="md")
    return img


# ------------------------------------------------------------ files

def _stem(brand: BrandRow, size: str, headline: str, slide: int | None = None) -> str:
    base = f"{brand.name or 'post'} {date.today().isoformat()} {size}{f' slide {slide}' if slide else ''} {headline}"
    return unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()[:70]


def _open(p: Path | None) -> Image.Image | None:
    if p is None or not p.is_file():
        return None
    im = Image.open(p)
    im.load()
    return im


def finish(src_path: Path, out_dir: Path, brand: BrandRow | None, *, headline: str = "", subline: str = "",
           price: str = "", cta: str = "", sizes: list[str] | tuple[str, ...] = DEFAULT_SIZES,
           logo_path: Path | None = None, layout: str = "band", focus: tuple[float, float] = (0.5, 0.45),
           src2_path: Path | None = None) -> list[dict]:
    """Write one JPEG per size into ``out_dir`` (new names, never an overwrite)
    and return ``[{name, size, width, height, label}]``."""
    from harness.tools.builtin.files import fresh_name

    brand = brand or NEUTRAL
    words = Words(headline, subline, price, cta)
    keys = [k for k in dict.fromkeys(sizes) if k in SIZES] or list(DEFAULT_SIZES)
    logo, src2 = _open(logo_path), _open(src2_path)
    out = []
    with Image.open(src_path) as src:
        src.load()
        for k in keys:
            img = render(src, brand, k, layout=layout, words=words, logo=logo, focus=focus, src2=src2)
            name = fresh_name(out_dir, _stem(brand, k, headline or Path(src_path).stem), "jpg")
            img.save(out_dir / name, "JPEG", quality=92, optimize=True, progressive=True)
            w, h, label = SIZES[k]
            out.append({"name": name, "size": k, "width": w, "height": h, "label": label})
    for im in (logo, src2):
        if im is not None:
            im.close()
    return out


def carousel(slides: list[dict], out_dir: Path, folder: Path, brand: BrandRow | None, *, sizes=("post",),
             layout: str = "band", logo_path: Path | None = None, cta: str = "", closing: bool = True) -> list[dict]:
    """A carousel: the first slide in ``layout``, the rest as numbered bands,
    and (``closing``) a last slide with the logo, handle and a call to action.
    ``slides`` are ``{image, headline, subline, price}`` with images in ``folder``."""
    from harness.tools.builtin.files import fresh_name

    brand = brand or NEUTRAL
    keys = [k for k in dict.fromkeys(sizes) if k in CAROUSEL_SIZES] or ["post"]
    logo = _open(logo_path)
    total = len(slides) + (1 if closing else 0)
    out = []
    for i, s in enumerate(slides, 1):
        with Image.open(folder / Path(str(s.get("image") or "")).name) as src:
            src.load()
            for k in keys:
                words = Words.of({**s, "cta": cta if i == 1 and not closing else ""})
                img = render(src, brand, k, layout=layout if i == 1 else "band", words=words, logo=logo,
                             slide="" if i == 1 else f"{i}/{total}")
                name = fresh_name(out_dir, _stem(brand, k, s.get("headline") or "", i), "jpg")
                img.save(out_dir / name, "JPEG", quality=92, optimize=True, progressive=True)
                w, h, label = SIZES[k]
                out.append({"name": name, "size": k, "width": w, "height": h, "label": label, "slide": i})
    if closing:
        for k in keys:
            img = closing_slide(brand, k, logo=logo, cta=cta)
            name = fresh_name(out_dir, _stem(brand, k, "follow", total), "jpg")
            img.save(out_dir / name, "JPEG", quality=92, optimize=True, progressive=True)
            w, h, label = SIZES[k]
            out.append({"name": name, "size": k, "width": w, "height": h, "label": label, "slide": total})
    if logo is not None:
        logo.close()
    return out


def preview(src_path: Path | None, brand: BrandRow, size: str, *, layout: str = "band", words: dict | None = None,
            logo_path: Path | None = None, focus: tuple[float, float] = (0.5, 0.45), src2_path: Path | None = None,
            max_side: int = 720, closing: bool = False, slide: str = "") -> bytes:
    """A small JPEG of the same design, for the studio's live preview (free)."""
    w, h = SIZES.get(size, SIZES["post"])[:2]
    scale = min(1.0, max_side / max(w, h))
    logo = _open(logo_path)
    try:
        if closing:
            img = closing_slide(brand, size, logo=logo, cta=(words or {}).get("cta", ""), scale=scale)
        else:
            src = _open(src_path) or sample_photo(brand)
            img = render(src, brand, size if size in SIZES else "post", layout=layout, words=words, logo=logo,
                         focus=focus, src2=_open(src2_path), scale=scale, slide=slide)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        return buf.getvalue()
    finally:
        if logo is not None:
            logo.close()


def sample_photo(brand: BrandRow, w: int = 1200, h: int = 1200) -> Image.Image:
    """A soft placeholder in the brand's colours, for previews before any photo is chosen."""
    pal = Palette.of(brand)
    top, bottom = _shade(pal.accent, 1.1), _shade(pal.primary, 0.75)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line((0, y, w, y), fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    r = w * 0.2
    d.ellipse((w / 2 - r, h * 0.42 - r, w / 2 + r, h * 0.42 + r), fill=_shade(pal.secondary, 0.97))
    d.ellipse((w / 2 - r * 0.72, h * 0.42 - r * 0.72, w / 2 + r * 0.72, h * 0.42 + r * 0.72), fill=_shade(pal.primary, 0.9))
    return img.filter(ImageFilter.GaussianBlur(2))


def make_zip(folder: Path, files: list[dict], captions: dict | None = None, *, title: str = "post") -> bytes:
    """Every file of a post plus its captions (captions.txt), named for a scheduler."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            p = folder / Path(f["name"]).name
            if p.is_file():
                z.write(p, Path(f["name"]).name)
        if captions:
            lines = []
            for platform, c in captions.items():
                lines.append(f"=== {platform.upper()} ===\n{c.get('text', '')}")
                if c.get("hashtags"):
                    lines.append(" ".join(c["hashtags"]))
                if c.get("first_comment"):
                    lines.append(f"First comment: {c['first_comment']}")
                lines.append("")
            z.writestr("captions.txt", "\n".join(lines))
    return buf.getvalue()
