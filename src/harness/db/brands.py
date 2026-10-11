"""The user's brands (harness.brands): CRUD, and how many they may have.

Slots = the plan's ``brands_included`` + ``users.extra_brands`` (one-time
purchases). Nothing is deleted when a plan shrinks: the oldest brands that
fit stay usable and the rest are ``paused`` until the user upgrades or hides
one. A foreign id behaves exactly like a missing one (None -> 404).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import select

from harness.db.base import SessionLocal
from harness.db.models import Brand, BrandAsset, BrandPost, User

# with billing off every feature is open; this keeps the table sane
BILLING_OFF_SLOTS = 10


class LimitReached(Exception):
    def __init__(self, slots: int, used: int):
        super().__init__(f"All {slots} brand slots are in use.")
        self.slots, self.used = slots, used


@dataclass
class BrandRow:
    id: int
    name: str
    kind: str = ""
    look: str = ""
    colors: list[dict] = field(default_factory=list)
    style: str = ""
    voice: str = ""
    font: str = "sans"
    logo: str = ""
    logo_dark: str = ""
    handle: str = ""
    website: str = ""
    cta: str = ""
    footer: str = ""
    hashtags: list[dict] = field(default_factory=list)       # [{name, tags}]
    paused: bool = False
    updated_at: datetime | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return d

    def color(self, role: str, default: str = "#222222") -> str:
        return next((c["hex"] for c in self.colors if c.get("role") == role), default)


EDITABLE = ("name", "kind", "look", "colors", "style", "voice", "font", "logo",
            "logo_dark", "handle", "website", "cta", "footer", "hashtags")


def _uid(user_id: str) -> int:
    return int(user_id)


def slots(user_id: str) -> int:
    from harness.billing import entitlements
    from harness.billing.plans import get_plan
    if not entitlements.billing_enabled():
        return BILLING_OFF_SLOTS
    from harness.db import billing as billing_db
    plan = get_plan(billing_db.get_account(user_id).plan)
    with SessionLocal() as s:
        u = s.get(User, _uid(user_id))
        extra = int(getattr(u, "extra_brands", 0) or 0) if u is not None else 0
    return plan.brands_included + extra


def _rows(s, user_id: str) -> list[Brand]:
    return list(s.execute(select(Brand).where(Brand.user_id == _uid(user_id), Brand.active.is_(True))
                          .order_by(Brand.created_at, Brand.id)).scalars())


def _to(b: Brand, paused: bool) -> BrandRow:
    return BrandRow(id=b.id, name=b.name, kind=b.kind, look=b.look, colors=list(b.colors or []), style=b.style,
                    voice=b.voice, font=b.font, logo=b.logo, logo_dark=getattr(b, "logo_dark", "") or "",
                    handle=getattr(b, "handle", "") or "", website=getattr(b, "website", "") or "",
                    cta=getattr(b, "cta", "") or "", footer=getattr(b, "footer", "") or "",
                    hashtags=list(getattr(b, "hashtags", None) or []), paused=paused, updated_at=b.updated_at)


def list_for(user_id: str, limit: int | None = None) -> list[BrandRow]:
    """Oldest first; those past the slot count are paused."""
    limit = slots(user_id) if limit is None else limit
    with SessionLocal() as s:
        return [_to(b, i >= limit) for i, b in enumerate(_rows(s, user_id))]


def get(user_id: str, brand_id: int) -> BrandRow | None:
    return next((b for b in list_for(user_id) if b.id == brand_id), None)


def usable(user_id: str, brand_id: int | None) -> BrandRow | None:
    """The brand a run may use: the user's own, shown, and not paused."""
    if not brand_id:
        return None
    b = get(user_id, brand_id)
    return b if b is not None and not b.paused else None


def create(user_id: str, **fields) -> BrandRow:
    limit = slots(user_id)
    with SessionLocal() as s:
        used = len(_rows(s, user_id))
        if used >= limit:
            raise LimitReached(limit, used)
        b = Brand(user_id=_uid(user_id), **{k: v for k, v in fields.items() if k in EDITABLE})
        s.add(b)
        s.commit()
        s.refresh(b)
        return _to(b, False)


def update(user_id: str, brand_id: int, **fields) -> BrandRow | None:
    with SessionLocal() as s:
        b = s.get(Brand, brand_id)
        if b is None or b.user_id != _uid(user_id) or not b.active:
            return None
        for k, v in fields.items():
            if k in EDITABLE and v is not None:
                setattr(b, k, v)
        s.commit()
    return get(user_id, brand_id)


def hide(user_id: str, brand_id: int) -> bool:
    with SessionLocal() as s:
        b = s.get(Brand, brand_id)
        if b is None or b.user_id != _uid(user_id) or not b.active:
            return False
        b.active = False
        s.commit()
        return True


def match_name(user_id: str, text: str) -> BrandRow | None:
    """A usable brand whose name appears in the message as whole words
    (case-insensitive), longest name first: "poster for Chinar Café"."""
    import re
    t = text or ""
    for b in sorted((b for b in list_for(user_id) if not b.paused), key=lambda b: -len(b.name)):
        if len(b.name) >= 3 and re.search(rf"(?<!\w){re.escape(b.name)}(?!\w)", t, re.I):
            return b
    return None


def add_slots(user_id: str, n: int) -> None:
    """One-time purchases (the payment webhook)."""
    with SessionLocal() as s:
        u = s.get(User, _uid(user_id))
        if u is not None and n > 0:
            u.extra_brands = int(u.extra_brands or 0) + n
            s.commit()


# ------------------------------------------------------------ photo library

@dataclass
class AssetRow:
    id: int
    brand_id: int
    name: str
    width: int
    height: int
    created_at: datetime | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat() if self.created_at else None
        return d


def _asset(a: BrandAsset) -> AssetRow:
    return AssetRow(a.id, a.brand_id, a.name, a.width, a.height, a.created_at)


ASSET_LIMIT = 200      # per brand; the library is for reuse, not storage


def add_asset(user_id: str, brand_id: int, name: str, width: int, height: int) -> AssetRow:
    with SessionLocal() as s:
        n = s.query(BrandAsset).filter(BrandAsset.brand_id == brand_id, BrandAsset.active.is_(True)).count()
        if n >= ASSET_LIMIT:
            raise LimitReached(ASSET_LIMIT, n)
        a = BrandAsset(brand_id=brand_id, user_id=_uid(user_id), name=name, width=width, height=height)
        s.add(a)
        s.commit()
        s.refresh(a)
        return _asset(a)


def list_assets(user_id: str, brand_id: int) -> list[AssetRow]:
    with SessionLocal() as s:
        rows = s.execute(select(BrandAsset).where(BrandAsset.brand_id == brand_id, BrandAsset.user_id == _uid(user_id),
                                                  BrandAsset.active.is_(True))
                         .order_by(BrandAsset.created_at.desc(), BrandAsset.id.desc())).scalars()
        return [_asset(a) for a in rows]


def hide_asset(user_id: str, brand_id: int, asset_id: int) -> bool:
    with SessionLocal() as s:
        a = s.get(BrandAsset, asset_id)
        if a is None or a.user_id != _uid(user_id) or a.brand_id != brand_id or not a.active:
            return False
        a.active = False
        s.commit()
        return True


# ------------------------------------------------------------ posts

REVIEW_STATES = ("none", "waiting", "approved", "changes")


@dataclass
class PostRow:
    id: int
    brand_id: int
    kind: str
    layout: str
    words: dict
    slides: list
    sizes: list
    files: list
    captions: dict
    review_status: str = "none"
    review_comment: str = ""
    reviewed_at: datetime | None = None
    created_at: datetime | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("reviewed_at", "created_at"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


def _post(p: BrandPost) -> PostRow:
    return PostRow(p.id, p.brand_id, p.kind, p.layout, dict(p.words or {}), list(p.slides or []), list(p.sizes or []),
                   list(p.files or []), dict(p.captions or {}), p.review_status, p.review_comment, p.reviewed_at,
                   p.created_at)


def add_post(user_id: str, brand_id: int, *, kind: str, layout: str, words: dict, slides: list, sizes: list,
             files: list) -> PostRow:
    with SessionLocal() as s:
        p = BrandPost(brand_id=brand_id, user_id=_uid(user_id), kind=kind, layout=layout, words=words, slides=slides,
                      sizes=sizes, files=files, captions={})
        s.add(p)
        s.commit()
        s.refresh(p)
        return _post(p)


def list_posts(user_id: str, brand_id: int, limit: int = 60) -> list[PostRow]:
    with SessionLocal() as s:
        rows = s.execute(select(BrandPost).where(BrandPost.brand_id == brand_id, BrandPost.user_id == _uid(user_id),
                                                 BrandPost.active.is_(True))
                         .order_by(BrandPost.created_at.desc(), BrandPost.id.desc()).limit(limit)).scalars()
        return [_post(p) for p in rows]


def post_counts(user_id: str) -> dict[int, int]:
    from sqlalchemy import func
    with SessionLocal() as s:
        rows = s.execute(select(BrandPost.brand_id, func.count()).where(BrandPost.user_id == _uid(user_id),
                                                                        BrandPost.active.is_(True))
                         .group_by(BrandPost.brand_id)).all()
        return {b: n for b, n in rows}


def get_post(user_id: str | None, post_id: int) -> PostRow | None:
    """The caller's post; ``user_id=None`` only for a verified review link."""
    with SessionLocal() as s:
        p = s.get(BrandPost, post_id)
        if p is None or not p.active or (user_id is not None and p.user_id != _uid(user_id)):
            return None
        return _post(p)


def post_owner(post_id: int) -> str | None:
    with SessionLocal() as s:
        p = s.get(BrandPost, post_id)
        return str(p.user_id) if p is not None and p.active else None


def update_post(user_id: str | None, post_id: int, **fields) -> PostRow | None:
    allowed = {"captions", "review_status", "review_comment", "reviewed_at", "active"}
    with SessionLocal() as s:
        p = s.get(BrandPost, post_id)
        if p is None or not p.active or (user_id is not None and p.user_id != _uid(user_id)):
            return None
        for k, v in fields.items():
            if k in allowed:
                setattr(p, k, v)
        s.commit()
        s.refresh(p)
        return _post(p)
