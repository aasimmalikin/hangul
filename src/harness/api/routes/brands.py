"""/brands: the user's brand looks (harness.brands) for the /brands page and
the setup card. Creating one past the plan's slots is a 402 ``brand_limit``
whose detail says how to get another (a bigger plan or a one-time slot). A
foreign id is a 404, exactly like a missing one."""

import asyncio
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from harness.api.auth import get_current_user
from harness.brands import templates
from harness.brands.palette import colors_from_logo
from harness.db import brands as db

router = APIRouter()

LOGO_MAX_BYTES = 5 * 1024 * 1024
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Color(BaseModel):
    role: str = Field(pattern="^(primary|secondary|accent|text)$")
    hex: str

    @field_validator("hex")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX.match(v):
            raise ValueError("colours are #RRGGBB")
        return v.upper()


class HashtagSet(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            t = "#" + re.sub(r"[^\w]", "", t.lstrip("#"))[:60]
            if len(t) > 1 and t not in out:
                out.append(t)
        return out


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    look: str | None = Field(default=None, max_length=48)     # a template look id; fills what's not given
    kind: str | None = Field(default=None, max_length=32)
    colors: list[Color] | None = Field(default=None, max_length=6)
    style: str | None = Field(default=None, max_length=300)
    voice: str | None = Field(default=None, max_length=300)
    font: str | None = None
    # the kit (brands v2)
    handle: str | None = Field(default=None, max_length=60)
    website: str | None = Field(default=None, max_length=200)
    cta: str | None = Field(default=None, max_length=60)
    footer: str | None = Field(default=None, max_length=120)
    hashtags: list[HashtagSet] | None = Field(default=None, max_length=10)

    @field_validator("handle")
    @classmethod
    def _handle(cls, v: str | None) -> str | None:
        return None if v is None else re.sub(r"[^\w.]", "", v.strip().lstrip("@"))[:60]

    @field_validator("font")
    @classmethod
    def _font(cls, v: str | None) -> str | None:
        if v is not None and v not in templates.FONT_KEYS:
            raise ValueError(f"font must be one of {', '.join(templates.FONT_KEYS)}")
        return v


class BrandPatch(BrandIn):
    name: str | None = Field(default=None, min_length=1, max_length=80)


def _fields(body: BrandIn) -> dict:
    """Template look first, the user's own choices on top."""
    out: dict = {}
    found = templates.find_look(body.look) if body.look else None
    if found:
        kind, lk = found
        out.update(kind=kind, look=lk.id, colors=lk.as_dict()["colors"], style=lk.style, voice=lk.voice, font=lk.font)
    elif body.look:
        out["look"] = body.look        # custom-N from /suggest: the fields come with it
    for k in ("name", "kind", "style", "voice", "font", "handle", "website", "cta", "footer"):
        v = getattr(body, k)
        if v is not None:
            out[k] = v.strip() if isinstance(v, str) else v
    if body.colors is not None:
        out["colors"] = [c.model_dump() for c in body.colors]
    if body.hashtags is not None:
        out["hashtags"] = [h.model_dump() for h in body.hashtags]
    return out


def _limit_402(e: db.LimitReached, user_id: str) -> HTTPException:
    from harness.billing import entitlements
    from harness.billing.plans import get_plan
    from harness.db import billing as billing_db
    plan = get_plan(billing_db.get_account(user_id).plan) if entitlements.billing_enabled() else None
    plan_needed = "plus" if plan is not None and plan.id == "free" else None
    detail = ("Brands are part of the Plus and Pro plans." if plan_needed else
              f"You're using all {e.slots} of your brand slots. Hide one, or add another slot.")
    return HTTPException(status_code=402, headers={"X-Reason": "brand_limit"},
                         detail={"detail": detail, "code": "brand_limit", "slots": e.slots, "used": e.used,
                                 "plan_needed": plan_needed, "buy": None if plan_needed else "brand_slot"})


@router.get("/brands")
async def list_brands(user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    slots = await asyncio.to_thread(db.slots, uid)
    rows = await asyncio.to_thread(db.list_for, uid, slots)
    counts = await asyncio.to_thread(db.post_counts, uid)
    covers = await asyncio.to_thread(_covers, uid, [b.id for b in rows])
    return {"brands": [{**b.as_dict(), "posts": counts.get(b.id, 0), "cover": covers.get(b.id)} for b in rows],
            "slots": slots, "used": len(rows), "can_add": len(rows) < slots,
            "templates_version": templates.TEMPLATES_VERSION}


def _covers(user_id: str, brand_ids: list[int]) -> dict[int, str]:
    """The newest post's first image per brand: what the brand's card shows."""
    out = {}
    for bid in brand_ids:
        posts = db.list_posts(user_id, bid, limit=1)
        if posts and posts[0].files:
            out[bid] = posts[0].files[0]["name"]
    return out


@router.get("/brands/templates")
async def brand_templates() -> dict:
    return {"version": templates.TEMPLATES_VERSION, "fonts": list(templates.FONT_KEYS), "kinds": templates.kinds()}


class SuggestIn(BaseModel):
    sentence: str = Field(min_length=2, max_length=400)


@router.post("/brands/suggest")
async def suggest(body: SuggestIn, user: dict = Depends(get_current_user)) -> dict:
    """Three looks for a one-sentence description. Only a sentence no template
    matches costs anything (one cheap-model call, charged to the user)."""
    from harness.billing import meter
    async with meter.metering(user["user_id"], settle_on_exit=True):
        return await templates.suggest(body.sentence)


@router.post("/brands")
async def create_brand(body: BrandIn, user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    fields = _fields(body)
    if not fields.get("colors"):
        raise HTTPException(status_code=422, detail="Pick a look or give the brand its colours.")
    try:
        b = await asyncio.to_thread(lambda: db.create(uid, **fields))
    except db.LimitReached as e:
        raise await asyncio.to_thread(_limit_402, e, uid)
    return b.as_dict()


@router.patch("/brands/{brand_id}")
async def patch_brand(brand_id: int, body: BrandPatch, user: dict = Depends(get_current_user)) -> dict:
    fields = _fields(body)
    b = await asyncio.to_thread(lambda: db.update(user["user_id"], brand_id, **fields))
    if b is None:
        raise HTTPException(status_code=404, detail="No such brand.")
    return b.as_dict()


@router.delete("/brands/{brand_id}")
async def delete_brand(brand_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(db.hide, user["user_id"], brand_id):
        raise HTTPException(status_code=404, detail="No such brand.")
    return {"ok": True}


@router.post("/brands/{brand_id}/logo")
async def upload_logo(brand_id: int, file: UploadFile = File(...), variant: str = "light",
                      user: dict = Depends(get_current_user)) -> dict:
    """Store the logo as a PNG in the user's folder (re-encoded, so only the
    pixels are kept) and suggest the colours it uses; the user confirms them.
    ``variant=dark`` is the version for dark backgrounds (no colours suggested)."""
    dark = variant == "dark"
    from PIL import Image, UnidentifiedImageError

    from harness.tools.builtin.files import user_folder
    uid = user["user_id"]
    if await asyncio.to_thread(db.get, uid, brand_id) is None:
        raise HTTPException(status_code=404, detail="No such brand.")
    data = await file.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="A logo can be up to 5 MB.")

    def save() -> tuple[str, list[dict]]:
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.width * im.height > 40_000_000:
                    raise HTTPException(status_code=422, detail="That image is too large.")
                im = im.convert("RGBA")
                im.thumbnail((1200, 1200))
                name = f"brand-{brand_id}-logo{'-dark' if dark else ''}.png"
                path = user_folder(uid) / name
                im.save(path, "PNG")
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=422, detail="Upload the logo as PNG, JPG or WebP.")
        return name, [] if dark else colors_from_logo(path)

    name, colors = await asyncio.to_thread(save)
    b = await asyncio.to_thread(lambda: db.update(uid, brand_id, **({"logo_dark": name} if dark else {"logo": name})))
    return {"brand": b.as_dict() if b else None, "suggested_colors": colors}


# ================================================================ the studio
# Photos, live preview, posts (with captions, a ZIP and client review). The
# rendering is Pillow only (brands/finish.py): free, so the preview can run on
# every change; only captions cost anything (one cheap-model call, metered).

PHOTO_MAX_BYTES = 15 * 1024 * 1024
PHOTO_MAX_SIDE = 3000


def need(user_id: str, feature: str) -> None:
    """402 plan_required when the user's plan doesn't include ``feature``
    (billing.plans.GATED_TOOLS); nothing with billing off."""
    from harness.billing import entitlements
    from harness.billing.plans import gate_for, get_plan, plan_allows_tool
    from harness.db import billing as billing_db
    if not entitlements.billing_enabled():
        return
    plan = get_plan(billing_db.get_account(user_id).plan)
    if not plan_allows_tool(plan, feature):
        plan_needed, label = gate_for(feature)
        raise HTTPException(status_code=402, headers={"X-Reason": "plan_required"},
                            detail={"detail": f"{label} is part of the {get_plan(plan_needed).label} plan.",
                                    "code": "plan_required", "plan_needed": plan_needed})


async def _usable(user_id: str, brand_id: int):
    b = await asyncio.to_thread(db.get, user_id, brand_id)
    if b is None:
        raise HTTPException(status_code=404, detail="No such brand.")
    if b.paused:
        raise HTTPException(status_code=402, headers={"X-Reason": "brand_limit"},
                            detail={"detail": "This brand is paused on your plan. Upgrade or remove another brand to use it.",
                                    "code": "brand_limit", "plan_needed": None, "buy": "brand_slot"})
    return b


@router.get("/brands/{brand_id}/assets")
async def list_assets(brand_id: int, user: dict = Depends(get_current_user)) -> list[dict]:
    if await asyncio.to_thread(db.get, user["user_id"], brand_id) is None:
        raise HTTPException(status_code=404, detail="No such brand.")
    return [a.as_dict() for a in await asyncio.to_thread(db.list_assets, user["user_id"], brand_id)]


@router.post("/brands/{brand_id}/assets")
async def add_asset(brand_id: int, file: UploadFile = File(...), user: dict = Depends(get_current_user)) -> dict:
    """A photo for the brand's library: turned upright (EXIF), capped at 3000 px,
    re-encoded as JPEG (only the pixels are kept) in the user's folder."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    from harness.tools.builtin.files import fresh_name, user_folder
    uid = user["user_id"]
    b = await _usable(uid, brand_id)
    await asyncio.to_thread(need, uid, "brand_studio")
    data = await file.read(PHOTO_MAX_BYTES + 1)
    if len(data) > PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="A photo can be up to 15 MB.")

    def save() -> tuple[str, int, int]:
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.width * im.height > 60_000_000:
                    raise HTTPException(status_code=422, detail="That image is too large.")
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
                folder = user_folder(uid)
                stem = re.sub(r"[^\w-]+", "-", (file.filename or "photo").rsplit(".", 1)[0])[:30] or "photo"
                name = fresh_name(folder, f"{b.name} {stem}", "jpg")
                im.save(folder / name, "JPEG", quality=92, optimize=True)
                return name, im.width, im.height
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=422, detail="That isn't a photo we can read. Try a JPG, PNG or WebP.")

    name, w, h = await asyncio.to_thread(save)
    try:
        a = await asyncio.to_thread(db.add_asset, uid, brand_id, name, w, h)
    except db.LimitReached:
        raise HTTPException(status_code=409, detail=f"A brand's library holds up to {db.ASSET_LIMIT} photos. Remove some first.")
    return a.as_dict()


@router.delete("/brands/{brand_id}/assets/{asset_id}")
async def remove_asset(brand_id: int, asset_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(db.hide_asset, user["user_id"], brand_id, asset_id):
        raise HTTPException(status_code=404, detail="No such photo.")
    return {"ok": True}


class Slide(BaseModel):
    image: str = Field(min_length=1, max_length=200)
    headline: str = Field(default="", max_length=160)
    subline: str = Field(default="", max_length=200)
    price: str = Field(default="", max_length=24)


class Design(BaseModel):
    layout: str = "band"
    words: dict[str, str] = Field(default_factory=dict)
    image: str | None = Field(default=None, max_length=200)       # a photo in the user's folder
    image2: str | None = Field(default=None, max_length=200)      # before/after's second photo
    focus: tuple[float, float] = (0.5, 0.45)
    sizes: list[str] = Field(default_factory=lambda: ["post", "story"], max_length=8)
    slides: list[Slide] = Field(default_factory=list, max_length=10)   # a carousel when given
    closing: bool = True

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: str) -> str:
        from harness.brands.finish import LAYOUTS
        if v not in LAYOUTS:
            raise ValueError(f"layout must be one of {', '.join(LAYOUTS)}")
        return v

    @field_validator("words")
    @classmethod
    def _words(cls, v: dict) -> dict:
        return {k: str(v.get(k) or "")[:200] for k in ("headline", "subline", "price", "cta") if v.get(k)}


def _photo(user_id: str, name: str | None):
    """A photo in the user's folder by basename, or 422 naming the problem."""
    if not name:
        return None
    from harness.tools.builtin.brand_tools import _image_in
    from harness.tools.builtin.files import user_folder
    p = _image_in(user_folder(user_id), name)
    if isinstance(p, str):
        raise HTTPException(status_code=422, detail=p)
    return p


class PreviewIn(Design):
    size: str = "post"
    slide: int = 0            # carousel: which slide to show (0 = the cover); len(slides) = the closing slide


@router.post("/brands/{brand_id}/preview")
async def preview(brand_id: int, body: PreviewIn, user: dict = Depends(get_current_user)):
    """A small JPEG of the design, for the live preview. Free: no AI."""
    from fastapi.responses import Response

    from harness.brands import finish as finisher
    from harness.tools.builtin.files import user_folder
    uid = user["user_id"]
    b = await _usable(uid, brand_id)
    folder = user_folder(uid)
    closing = bool(body.slides) and body.slide >= len(body.slides)
    if body.slides and not closing:
        s = body.slides[max(0, body.slide)]
        src, words, layout = _photo(uid, s.image), {**s.model_dump(), "cta": ""}, body.layout if body.slide == 0 else "band"
        label = "" if body.slide == 0 else f"{body.slide + 1}/{len(body.slides) + (1 if body.closing else 0)}"
    else:
        src, words, layout, label = _photo(uid, body.image), body.words, body.layout, ""
    jpeg = await asyncio.to_thread(
        finisher.preview, src, b, body.size if body.size in finisher.SIZES else "post", layout=layout, words=words,
        logo_path=folder / b.logo if b.logo else None, focus=body.focus, src2_path=_photo(uid, body.image2),
        closing=closing, slide=label)
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/brands/{brand_id}/posts")
async def make_post(brand_id: int, body: Design, user: dict = Depends(get_current_user)) -> dict:
    """Render every size (every slide of a carousel) and keep the post."""
    from harness.brands import finish as finisher
    from harness.tools.builtin.files import user_folder
    uid = user["user_id"]
    b = await _usable(uid, brand_id)
    await asyncio.to_thread(need, uid, "brand_carousel" if body.slides else "brand_studio")
    folder = user_folder(uid)
    logo = folder / b.logo if b.logo else None
    if body.slides:
        for s in body.slides:
            _photo(uid, s.image)
        sizes = [k for k in body.sizes if k in finisher.CAROUSEL_SIZES] or ["post"]
        files = await asyncio.to_thread(finisher.carousel, [s.model_dump() for s in body.slides], folder, folder, b,
                                        sizes=sizes, layout=body.layout, logo_path=logo,
                                        cta=body.words.get("cta", "") or b.cta, closing=body.closing)
        kind = "carousel"
    else:
        src = _photo(uid, body.image)
        if src is None:
            raise HTTPException(status_code=422, detail="Choose a photo first.")
        sizes = [k for k in body.sizes if k in finisher.SIZES] or list(finisher.DEFAULT_SIZES)
        w = finisher.Words.of(body.words)
        files = await asyncio.to_thread(finisher.finish, src, folder, b, headline=w.headline, subline=w.subline,
                                        price=w.price, cta=w.cta, sizes=sizes, logo_path=logo, layout=body.layout,
                                        focus=body.focus, src2_path=_photo(uid, body.image2))
        kind = "single"
    post = await asyncio.to_thread(lambda: db.add_post(uid, brand_id, kind=kind, layout=body.layout, words=body.words,
                                                       slides=[s.model_dump() for s in body.slides], sizes=sizes,
                                                       files=files))
    return post.as_dict()


@router.get("/brands/{brand_id}/posts")
async def list_posts(brand_id: int, user: dict = Depends(get_current_user)) -> list[dict]:
    if await asyncio.to_thread(db.get, user["user_id"], brand_id) is None:
        raise HTTPException(status_code=404, detail="No such brand.")
    return [p.as_dict() for p in await asyncio.to_thread(db.list_posts, user["user_id"], brand_id)]


async def _post(user_id: str, post_id: int):
    p = await asyncio.to_thread(db.get_post, user_id, post_id)
    if p is None:
        raise HTTPException(status_code=404, detail="No such post.")
    return p


@router.delete("/posts/{post_id}")
async def delete_post(post_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Hide the post (its files stay in the user's folder, like everything else they made)."""
    await _post(user["user_id"], post_id)
    await asyncio.to_thread(lambda: db.update_post(user["user_id"], post_id, active=False))
    return {"ok": True}


@router.get("/posts/{post_id}/zip")
async def post_zip(post_id: int, user: dict = Depends(get_current_user)):
    from fastapi.responses import Response

    from harness.brands import finish as finisher
    from harness.tools.builtin.files import user_folder
    uid = user["user_id"]
    p = await _post(uid, post_id)
    b = await asyncio.to_thread(db.get, uid, p.brand_id)
    data = await asyncio.to_thread(finisher.make_zip, user_folder(uid), p.files, p.captions)
    import unicodedata
    raw = f"{b.name if b else 'post'}-{p.created_at:%Y-%m-%d}-{post_id}" if p.created_at else f"post-{post_id}"
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()      # headers are ASCII
    stem = re.sub(r"[^A-Za-z0-9-]+", "-", raw).strip("-").lower() or f"post-{post_id}"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{stem}.zip"', "Cache-Control": "private, no-store"})


class CaptionsIn(BaseModel):
    platforms: list[str] = Field(default_factory=lambda: ["instagram", "facebook", "whatsapp"], max_length=5)
    note: str = Field(default="", max_length=300)


@router.post("/posts/{post_id}/captions")
async def write_captions(post_id: int, body: CaptionsIn, user: dict = Depends(get_current_user)) -> dict:
    """Captions for each platform in the brand's voice (one cheap-model call, charged)."""
    from harness.billing import meter
    from harness.brands import captions
    uid = user["user_id"]
    p = await _post(uid, post_id)
    b = await _usable(uid, p.brand_id)
    await asyncio.to_thread(need, uid, "write_caption")
    try:
        async with meter.metering(uid, settle_on_exit=True):
            out = await captions.write(b, p.words, layout=p.layout, slides=p.slides, platforms=body.platforms,
                                       note=body.note)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    p = await asyncio.to_thread(lambda: db.update_post(uid, post_id, captions={**p.captions, **out}))
    return p.as_dict()


class CaptionEdit(BaseModel):
    platform: str
    text: str = Field(max_length=3000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    first_comment: str = Field(default="", max_length=2200)


@router.patch("/posts/{post_id}/captions")
async def edit_caption(post_id: int, body: CaptionEdit, user: dict = Depends(get_current_user)) -> dict:
    from harness.brands.captions import PLATFORMS
    uid = user["user_id"]
    p = await _post(uid, post_id)
    if body.platform not in PLATFORMS:
        raise HTTPException(status_code=422, detail="Unknown platform.")
    caps = {**p.captions, body.platform: {"label": PLATFORMS[body.platform][0], "text": body.text,
                                          "hashtags": body.hashtags, "first_comment": body.first_comment}}
    return (await asyncio.to_thread(lambda: db.update_post(uid, post_id, captions=caps))).as_dict()


@router.post("/posts/{post_id}/review-link")
async def review_link(post_id: int, user: dict = Depends(get_current_user)) -> dict:
    """A private link for the client: they see the post and approve it or ask for changes."""
    from datetime import UTC, datetime

    from harness.brands import review
    uid = user["user_id"]
    await _post(uid, post_id)
    await asyncio.to_thread(need, uid, "brand_review")
    token = review.make(post_id, uid)
    await asyncio.to_thread(lambda: db.update_post(uid, post_id, review_status="waiting", review_comment="",
                                                   reviewed_at=None))
    return {"url": review.url(token), "token": token,
            "expires_at": datetime.fromtimestamp(review.read(token)[2], UTC).isoformat()}


# ---------------------------------------------------------------- the client's side (no account)
# The signed link is the credential (harness.brands.review). Only the post's own
# files and its brand's logo can be fetched, and only its review can change.

public = APIRouter()


def _from_link(token: str):
    from harness.brands import review
    try:
        post_id, uid, expires = review.read(token)
    except review.LinkError:
        raise HTTPException(status_code=410, detail="This review link has expired or isn't valid. Ask for a new one.")
    p = db.get_post(uid, post_id)
    if p is None:
        raise HTTPException(status_code=410, detail="This post is no longer available.")
    return uid, p, expires


@public.get("/review/{token}")
async def review_page(token: str) -> dict:
    from datetime import UTC, datetime
    uid, p, expires = await asyncio.to_thread(_from_link, token)
    b = await asyncio.to_thread(db.get, uid, p.brand_id)
    brand = {"name": b.name, "colors": b.colors, "font": b.font, "logo": b.logo or None, "handle": b.handle} if b else None
    return {"brand": brand, "post": {k: v for k, v in p.as_dict().items() if k != "brand_id"},
            "expires_at": datetime.fromtimestamp(expires, UTC).isoformat()}


@public.get("/review/{token}/files/{name}")
async def review_file(token: str, name: str):
    from fastapi.responses import FileResponse

    from harness.tools.builtin.files import user_folder
    uid, p, _exp = await asyncio.to_thread(_from_link, token)
    b = await asyncio.to_thread(db.get, uid, p.brand_id)
    allowed = {f["name"] for f in p.files} | ({b.logo} if b and b.logo else set())
    base = name.rsplit("/", 1)[-1]
    if base not in allowed:
        raise HTTPException(status_code=404, detail="Not part of this post.")
    path = user_folder(uid) / base
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path, headers={"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex"})


class Decision(BaseModel):
    decision: str = Field(pattern="^(approve|changes)$")
    comment: str = Field(default="", max_length=2000)
    name: str = Field(default="", max_length=80)


@public.post("/review/{token}")
async def review_decide(token: str, body: Decision) -> dict:
    from datetime import UTC, datetime
    uid, p, _exp = await asyncio.to_thread(_from_link, token)
    if body.decision == "changes" and not body.comment.strip():
        raise HTTPException(status_code=422, detail="Say what you'd like changed.")
    who = body.name.strip()
    comment = (f"{who}: " if who else "") + body.comment.strip()
    status = "approved" if body.decision == "approve" else "changes"
    p = await asyncio.to_thread(lambda: db.update_post(None, p.id, review_status=status, review_comment=comment,
                                                       reviewed_at=datetime.now(UTC)))
    b = await asyncio.to_thread(db.get, uid, p.brand_id)
    try:
        from harness import push
        title = f"✅ {b.name if b else 'Your client'}: post approved" if status == "approved" else \
            f"✏️ {b.name if b else 'Your client'} asked for changes"
        await push.send(uid, title, comment or "Open the post to see it.", url=f"/brands/{p.brand_id}?post={p.id}",
                        tag=f"review-{p.id}")
    except Exception as e:  # noqa: BLE001 - the decision is saved either way
        from harness.logging import log
        log.warning("review notification failed", error=str(e))
    return {"status": status, "comment": comment}
