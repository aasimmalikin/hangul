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


def make_generate_image_tool(user_id: str, thread_id: str | None = None) -> Tool:
    async def generate_image(prompt: str, shape: str = "square", quality: str = "") -> ToolOutput | str:
        from harness.providers import get_provider

        prompt = (prompt or "").strip()
        if len(prompt) < 3:
            return "Describe the image to draw."
        size = SIZES.get(shape, SIZES["square"])
        quality = quality if quality in QUALITIES else get_settings().image_default_quality
        try:
            resp = await get_provider().client.images.generate(
                model=get_settings().image_model, prompt=prompt[:4000], size=size, quality=quality, n=1)
        except Exception as e:  # noqa: BLE001 - refusals and outages come back as text
            msg = str(getattr(e, "message", "") or e)
            if "safety" in msg.lower() or "moderation" in msg.lower() or "rejected" in msg.lower():
                return "The image service declined that request under its content policy. Suggest a different idea."
            log.warning("image generation failed", error=msg[:200])
            return f"Image generation is unavailable right now ({type(e).__name__})."
        data = base64.b64decode(resp.data[0].b64_json)
        folder = user_folder(user_id)
        name = fresh_name(folder, prompt[:50], "png")
        (folder / name).write_bytes(data)
        try:
            from harness.billing import entitlements
            entitlements.settle(user_id, Decimal(str(image_cost(quality, size))), thread_id)
        except Exception as e:  # noqa: BLE001
            log.warning("image cost not recorded", error=str(e))
        return ToolOutput(f"Drew the image and showed it to the user ({name}, {size}, {quality} quality).",
                          {"kind": "image", "name": name, "prompt": prompt[:300], "size": size})

    return Tool(
        name="generate_image",
        description=(
            "Draw an image from a description: illustrations, posters, social posts, thumbnails, product mock-ups, "
            "logos ideas. Write a vivid, specific prompt (subject, style, colours, composition, any text to include). "
            "`shape`: square (default), landscape or portrait. `quality`: low/medium/high (default medium; high is "
            "slower and costs more). The picture is shown to the user with a download link."),
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
    )
