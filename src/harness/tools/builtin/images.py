"""generate_image: make a picture from a description (Pro plan).

OpenAI's image model draws it; the PNG is saved in the user's own folder and
shown in the chat with a download link (``GET /files/<name>``). Each image is
charged to the user's allowance at the approximate price for its size and
quality, so a burst of requests can't run up an unbilled cost. The provider's
own safety system refuses disallowed prompts; that refusal is passed back as
text for the model to explain.
"""

import base64
from decimal import Decimal

from harness.config import get_settings
from harness.logging import log
from harness.tools.base import Tool, ToolOutput
from harness.tools.builtin.files import fresh_name, user_folder

SIZES = {"square": "1024x1024", "landscape": "1536x1024", "portrait": "1024x1536"}
QUALITIES = ("low", "medium", "high")
# $ per image, gpt-image-1 list prices (VERIFY): [quality][square?]
PRICE = {"low": (0.011, 0.016), "medium": (0.042, 0.063), "high": (0.167, 0.25)}


def image_cost(quality: str, size: str) -> float:
    square, other = PRICE.get(quality, PRICE["medium"])
    return square if size == "1024x1024" else other


def _brand_suffix(brand) -> str:
    if brand is None:
        return ""
    from harness.brands.prompt import style_line
    return style_line(brand)


def _charge(user_id: str, usd: float, thread_id: str | None) -> None:
    try:
        from harness.billing import entitlements
        entitlements.settle(user_id, Decimal(str(usd)), thread_id)
    except Exception as e:  # noqa: BLE001
        log.warning("image cost not recorded", error=str(e))


def _refusal(e: Exception) -> str:
    msg = str(getattr(e, "message", "") or e)
    if "safety" in msg.lower() or "moderation" in msg.lower() or "rejected" in msg.lower():
        return "The image service declined that request under its content policy. Suggest a different idea."
    log.warning("image call failed", error=msg[:200])
    return f"Image generation is unavailable right now ({type(e).__name__})."


def make_generate_image_tool(user_id: str, thread_id: str | None = None, brand=None) -> Tool:
    async def generate_image(prompt: str, shape: str = "square", quality: str = "") -> ToolOutput | str:
        from harness.providers import get_provider

        prompt = (prompt or "").strip()
        if len(prompt) < 3:
            return "Describe the image to draw."
        size = SIZES.get(shape, SIZES["square"])
        quality = quality if quality in QUALITIES else get_settings().image_default_quality
        try:
            resp = await get_provider().client.images.generate(
                model=get_settings().image_model, prompt=(prompt[:3600] + _brand_suffix(brand))[:4000],
                size=size, quality=quality, n=1)
        except Exception as e:  # noqa: BLE001 - refusals and outages come back as text
            return _refusal(e)
        data = base64.b64decode(resp.data[0].b64_json)
        folder = user_folder(user_id)
        name = fresh_name(folder, prompt[:50], "png")
        (folder / name).write_bytes(data)
        _charge(user_id, image_cost(quality, size), thread_id)
        return ToolOutput(f"Drew the image and showed it to the user ({name}, {size}, {quality} quality).",
                          {"kind": "image", "name": name, "prompt": prompt[:300], "size": size})

    return Tool(
        name="generate_image",
        description=(
            "Draw an image from a description: photos, illustrations, posters, social posts, thumbnails, product "
            "mock-ups, logo ideas. Write a detailed prompt (40-120 words): subject, setting, composition, lighting, "
            "colours and any exact text to include. Unless the user asked for a style (illustration, cartoon, logo, "
            "watercolour…), make it photorealistic: describe it as a real photograph (camera and lens, e.g. "
            "'shot on a full-frame camera, 85mm, f/2'; natural light and its direction; real textures, fine detail, "
            "sharp focus, true-to-life colour) and avoid words like 'digital art' or 'render'. "
            "`shape`: square (default), landscape (scenes, banners) or portrait (people, posters). `quality`: leave "
            "it out for the best quality; pass medium or low only when the user asks for a quick rough draft. "
            "The picture is shown to the user with a download link."),
        parameter={
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "shape": {"type": "string", "enum": list(SIZES)},
                "quality": {"type": "string", "enum": list(QUALITIES)},
            },
            "required": ["prompt"],
        },
        handler=generate_image,
        # gpt-image-1 at high quality often takes over a minute; the default 30 s
        # cancelled the request after OpenAI had already started (and billed) it
        timeout=180.0,
    )


# high input fidelity makes the source photo's tokens count; a rough per-edit
# estimate on top of the output price (VERIFY against OpenAI's pricing page)
EDIT_INPUT_USD = 0.03
EDIT_MAX_SIDE = 2048


def _shape_of(w: int, h: int) -> str:
    return "landscape" if w > h * 1.15 else "portrait" if h > w * 1.15 else "square"


def make_edit_image_tool(user_id: str, thread_id: str | None = None, brand=None) -> Tool:
    """Change a picture the user uploaded (Pro): new background, light, mood or
    style, keeping what's in it. OpenAI redraws the whole picture from it at
    high input fidelity, so faces and products stay close but can drift a
    little -- the description tells the model to say so for product shots."""
    async def edit_image(image: str, instruction: str, shape: str = "", quality: str = "") -> ToolOutput | str:
        import asyncio
        import io

        from PIL import Image

        from harness.providers import get_provider
        from harness.tools.builtin.brand_tools import _image_in

        instruction = (instruction or "").strip()
        if len(instruction) < 3:
            return "Say what to change in the picture."
        folder = user_folder(user_id)
        src = _image_in(folder, image)
        if isinstance(src, str):
            return src

        def prepare() -> tuple[bytes, str]:
            with Image.open(src) as im:
                im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
                im.thumbnail((EDIT_MAX_SIDE, EDIT_MAX_SIDE))
                buf = io.BytesIO()
                im.save(buf, "PNG")
                return buf.getvalue(), _shape_of(im.width, im.height)
        data, natural = await asyncio.to_thread(prepare)
        size = SIZES.get(shape or natural, SIZES["square"])
        quality = quality if quality in QUALITIES else get_settings().image_default_quality
        prompt = (instruction[:3600] + _brand_suffix(brand))[:4000]
        try:
            resp = await get_provider().client.images.edit(
                model=get_settings().image_model, image=(f"{src.stem}.png", data, "image/png"), prompt=prompt,
                size=size, quality=quality, input_fidelity="high", n=1)
        except Exception as e:  # noqa: BLE001 - refusals and outages come back as text
            return _refusal(e)
        out = base64.b64decode(resp.data[0].b64_json)
        name = fresh_name(folder, f"{src.stem} edited", "png")
        (folder / name).write_bytes(out)
        _charge(user_id, image_cost(quality, size) + EDIT_INPUT_USD, thread_id)
        return ToolOutput(f"Edited {src.name} and showed it to the user ({name}, {size}, {quality} quality).",
                          {"kind": "image", "name": name, "prompt": instruction[:300], "size": size, "source": src.name})

    on = f" The brand {brand.name!r} is on: its style and colours are applied." if brand else ""
    return Tool(
        name="edit_image",
        description=(
            "Change a photo in the user's folder (their upload): new background, setting, light, season, mood or "
            "style, keeping the subject. E.g. 'put the cup on a marble table by a window, soft morning light'. "
            "Describe the change in detail. It redraws the picture, so a product's label or a face can shift "
            "slightly: for product photos say so, and keep the original if exactness matters. Never ask it to "
            "write words: finish_image adds text exactly. `shape` defaults to the photo's own; `quality` leave out "
            "for the best." + on),
        parameter={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Exact file name in the user's folder"},
                "instruction": {"type": "string"},
                "shape": {"type": "string", "enum": list(SIZES)},
                "quality": {"type": "string", "enum": list(QUALITIES)},
            },
            "required": ["image", "instruction"],
        },
        handler=edit_image,
        timeout=180.0,
    )
