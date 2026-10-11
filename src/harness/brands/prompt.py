"""What the model is told about the brand that's on: the full block in the
system prompt, and one line added to every image prompt."""

from harness.db.brands import BrandRow


def _colors(b: BrandRow) -> str:
    return ", ".join(f"{c['role']} {c['hex']}" for c in b.colors)


def brand_block(b: BrandRow) -> str:
    return (
        f"=== BRAND: {b.name} ===\n"
        f"The user is making things for their brand \"{b.name}\". Everything you make for them follows it.\n"
        f"Colours: {_colors(b)}.\n"
        f"Image style: {b.style or 'clean and professional'}.\n"
        f"Writing voice: {b.voice or 'friendly and clear'}.\n"
        "For a post or poster from the user's photo: edit_image (if the picture itself should change) then "
        "finish_image. Any words on an image (offers, prices, dates, the name) go through finish_image, which "
        "writes them exactly in the brand font with the real logo; never ask the image model to draw text."
    )


def style_line(b: BrandRow) -> str:
    """Appended to generate_image / edit_image prompts."""
    names = ", ".join(c["hex"] for c in b.colors[:3])
    return (f" Brand look for {b.name}: {b.style or 'clean and professional'}; colour palette {names}. "
            "No text, letters or logos in the image.")
