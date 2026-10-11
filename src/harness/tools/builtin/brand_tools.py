"""Brand tools (harness.brands), built per request with the run's brand.

``finish_image`` (Plus) puts exact words, the real logo and the brand's
colours on a picture in the user's folder, in every size asked for. It is
plain image code: no AI, nothing charged. ``brands`` (Plus) lists the user's
brands or starts setting one up; saving is the user's tap on the card, so
the model never invents a brand's colours on its own.
"""

import asyncio
from pathlib import Path

from harness.brands import finish as finisher
from harness.brands import templates
from harness.db import brands as brands_db
from harness.db.brands import BrandRow
from harness.media.vision import IMAGE_TYPES
from harness.tools.base import Tool, ToolOutput
from harness.tools.builtin.files import user_folder


def _image_in(folder: Path, filename: str) -> Path | str:
    """The image by basename, or an error naming the images there are."""
    path = folder / Path(filename or "").name
    if path.suffix.lower() in IMAGE_TYPES and path.is_file():
        return path
    images = sorted(p.name for p in folder.glob("*") if p.suffix.lower() in IMAGE_TYPES)[-15:] if folder.is_dir() else []
    return (f"No image named {Path(filename or '').name!r}. "
            + (f"Images in the user's folder: {', '.join(images)}." if images else "Ask the user to upload the photo first."))


def _plan_allows(user_id: str, feature: str) -> bool:
    from harness.billing import entitlements
    from harness.billing.plans import get_plan, plan_allows_tool
    from harness.db import billing as billing_db
    return not entitlements.billing_enabled() or plan_allows_tool(get_plan(billing_db.get_account(user_id).plan), feature)


def make_finish_image_tool(user_id: str, brand: BrandRow | None = None) -> Tool:
    async def finish_image(image: str = "", headline: str = "", subline: str = "", price: str = "", cta: str = "",
                           layout: str = "band", sizes: list[str] | None = None, logo: bool = True,
                           image2: str = "", slides: list[dict] | None = None) -> ToolOutput | str:
        folder = user_folder(user_id)
        layout = layout if layout in finisher.LAYOUTS else "band"
        logo_path = folder / brand.logo if brand and brand.logo and logo else None
        cta = cta or (brand.cta if brand else "")
        if slides:
            if not await asyncio.to_thread(_plan_allows, user_id, "brand_carousel"):
                return ToolOutput(
                    "Carousel posts are part of the Pro plan, and this user's plan doesn't include them. Say so briefly, "
                    "offer a single post instead, and mention the upgrade (the card has the button).",
                    {"kind": "upgrade", "feature": "Carousel posts", "plan": "pro", "plan_label": "Pro"})
            clean = []
            for sl in slides[:10]:
                p = _image_in(folder, str(sl.get("image") or ""))
                if isinstance(p, str):
                    return p
                clean.append({"image": p.name, **{k: str(sl.get(k) or "")[:160] for k in ("headline", "subline", "price")}})
            keys = [k for k in (sizes or ["post"]) if k in finisher.CAROUSEL_SIZES] or ["post"]
            files = await asyncio.to_thread(finisher.carousel, clean, folder, folder, brand, sizes=keys, layout=layout,
                                            logo_path=logo_path, cta=cta)
            words, kind, source = {"headline": clean[0]["headline"], "cta": cta}, "carousel", clean[0]["image"]
        else:
            src = _image_in(folder, image)
            if isinstance(src, str):
                return src
            src2 = _image_in(folder, image2) if image2 else None
            if isinstance(src2, str):
                return src2
            keys = sizes or list(finisher.DEFAULT_SIZES)
            files = await asyncio.to_thread(finisher.finish, src, folder, brand, headline=headline[:160],
                                            subline=subline[:200], price=price[:24], cta=cta[:40], sizes=keys,
                                            logo_path=logo_path, layout=layout, src2_path=src2)
            words = {k: v for k, v in (("headline", headline), ("subline", subline), ("price", price), ("cta", cta)) if v}
            kind, source, clean = "single", src.name, []
        post_id = None
        if brand is not None and brand.id:
            try:
                from harness.db import brands as brands_db
                post = await asyncio.to_thread(lambda: brands_db.add_post(
                    user_id, brand.id, kind=kind, layout=layout, words=words, slides=clean,
                    sizes=sorted({f["size"] for f in files}), files=files))
                post_id = post.id
            except Exception:  # noqa: BLE001 - the images are made; the library entry is a nicety
                post_id = None
        names = ", ".join(f"{f['name']} ({f['label']}{', slide ' + str(f['slide']) if f.get('slide') else ''})" for f in files)
        note = "" if brand else " No brand is on, so neutral colours were used; offer to set one up (brands tool)."
        tip = " The card has buttons to write captions, download everything as a ZIP and send it to a client for approval." \
            if post_id else ""
        return ToolOutput(f"Made the {'carousel' if slides else 'post'} and showed it to the user: {names}.{note}{tip}",
                          {"kind": "brand_set", "brand": brand.name if brand else "", "brand_id": brand.id if brand else None,
                           "post_id": post_id, "post_kind": kind, "layout": layout, "source": source, "files": files})

    sizes = list(finisher.SIZES)
    on = (f" The brand {brand.name!r} is on: its colours, font, logo, handle and call to action are applied." if brand
          else " No brand is on right now (neutral colours).")
    return Tool(
        name="finish_image",
        description=(
            "Make a ready-to-post image (or a carousel) from pictures in the user's folder (their uploads, or ones you "
            "made with generate_image / edit_image). Writes the words EXACTLY in the brand's colours and font, stamps "
            "the real logo, and exports each size: " + ", ".join(f"{k} = {v[2]}" for k, v in finisher.SIZES.items())
            + ". Layouts: " + "; ".join(f"{k} = {v[1]}" for k, v in finisher.LAYOUTS.items())
            + ". Free and instant (no AI). Always use this for any text on an image: image models misspell words. "
            "Keep the headline short (2-8 words); details go in the sub-line. Pick the layout that fits: a price or "
            "sale -> offer; an event -> event (date and place in the sub-line); a customer review -> quote (the review "
            "in headline, the name in subline); a product on its own -> showcase; two photos -> split with image2. "
            "For a carousel pass `slides` (2-10, each {image, headline, subline}); a closing 'follow us' slide is "
            "added." + on),
        parameter={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Exact file name in the user's folder"},
                "headline": {"type": "string"},
                "subline": {"type": "string"},
                "price": {"type": "string", "description": "e.g. '₹80' or '20% OFF'"},
                "cta": {"type": "string", "description": "Call to action, e.g. 'Order now' (default: the brand's)"},
                "layout": {"type": "string", "enum": list(finisher.LAYOUTS)},
                "sizes": {"type": "array", "items": {"type": "string", "enum": sizes},
                          "description": "Default: post and story. A carousel uses post or portrait."},
                "logo": {"type": "boolean", "description": "Stamp the brand's logo (default true)"},
                "image2": {"type": "string", "description": "The 'after' photo for the split layout"},
                "slides": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
                    "image": {"type": "string"}, "headline": {"type": "string"}, "subline": {"type": "string"},
                    "price": {"type": "string"}}, "required": ["image"]}},
            },
        },
        handler=finish_image,
    )


def make_brands_tool(user_id: str, brand: BrandRow | None = None) -> Tool:
    async def brands(action: str = "list", description: str = "") -> ToolOutput | str:
        if action == "setup":
            if len(description.strip()) < 2:
                return "Ask the user, in one sentence, what the brand is for (their business, its feel, who it's for)."
            rows = await asyncio.to_thread(brands_db.list_for, user_id)
            slots = await asyncio.to_thread(brands_db.slots, user_id)
            if len(rows) >= slots:
                return (f"All {slots} of the user's brand slots are in use. They can remove one on the Brands page, "
                        "or add a slot there (a one-time purchase).")
            sug = await templates.suggest(description)
            return ToolOutput(
                "Showed the user three looks for their brand; they pick one with a tap (it isn't saved until then). "
                "Don't list colours or repeat the looks; one short sentence is enough.",
                {"kind": "brand_setup", "sentence": description[:400], "suggestion": sug})
        rows = await asyncio.to_thread(brands_db.list_for, user_id)
        if not rows:
            return "The user has no brands yet. Offer to set one up (action='setup' with their one-sentence description)."
        lines = [f"- {b.name}{' (paused: over their plan)' if b.paused else ''}{' [ON in this chat]' if brand and b.id == brand.id else ''}"
                 f": {b.style}; voice: {b.voice}{'; has a logo' if b.logo else ''}" for b in rows]
        return ("The user's brands:\n" + "\n".join(lines)
                + "\nA brand is switched on with the brand chip above the message box, or by naming it in a message.")

    return Tool(
        name="brands",
        description=(
            "The user's brands (their business looks: colours, font, logo, voice). action='list' shows them; "
            "action='setup' with `description` (the user's one sentence about the business) shows three looks to "
            "pick from. Use setup when the user wants posts/posters for a business that has no brand yet."),
        parameter={
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["list", "setup"]}, "description": {"type": "string"}},
            "required": ["action"],
        },
        handler=brands,
    )
