"""The Brand Studio (brands v2): the kit, the photo library, the live preview,
posts in every size and as carousels, the ZIP, captions per platform, and
client review links -- with plan gates and per-user isolation."""
import asyncio
import io
import json
import time
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harness.api.auth import get_current_user
from harness.api.routes import brands as routes
from harness.billing import entitlements
from harness.brands import captions, finish, review
from harness.db import billing as billing_db
from harness.db import brands as db
from harness.db.models import Brand, BrandAsset, BrandPost, User
from harness.tools.builtin import brand_tools, files


@compiles(JSONB, "sqlite")
def _jsonb_as_json(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
def store(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for m in (Brand, BrandAsset, BrandPost, User):
        m.__table__.create(engine)
    maker = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", maker)
    monkeypatch.setattr(billing_db, "SessionLocal", maker)
    monkeypatch.setattr(files, "SESSIONS", tmp_path)
    with maker() as s:
        s.add_all([User(id=7, plan="pro"), User(id=8, plan="free"), User(id=9, plan="plus")])
        s.commit()
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: True)
    return tmp_path


def app(user="7"):
    a = FastAPI()
    a.include_router(routes.router)
    a.include_router(routes.public)
    a.dependency_overrides[get_current_user] = lambda: {"user_id": user}
    return TestClient(a)


def public():
    a = FastAPI()
    a.include_router(routes.public)
    return TestClient(a)


def _jpeg(w=900, h=600, color=(150, 90, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def brand(user="7", **kw) -> int:
    return app(user).post("/brands", json={"name": "Chinar Café", "look": "cafe-heritage", **kw}).json()["id"]


def photo(bid, user="7", **kw) -> str:
    r = app(user).post(f"/brands/{bid}/assets", files={"file": ("kahwa.jpg", _jpeg(**kw), "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["name"]


# ------------------------------------------------------------ the kit

def test_kit_fields_are_cleaned_and_kept(store):
    bid = brand()
    r = app().patch(f"/brands/{bid}", json={"handle": " @chinar.cafe! ", "website": "chinarcafe.in", "cta": "Order on Zomato",
                                            "footer": "Lal Chowk · 98765 43210",
                                            "hashtags": [{"name": "Everyday", "tags": ["kashmir", "#Srinagar", "kashmir", "chai time"]}]})
    b = r.json()
    assert b["handle"] == "chinar.cafe" and b["cta"] == "Order on Zomato"
    assert b["hashtags"] == [{"name": "Everyday", "tags": ["#kashmir", "#Srinagar", "#chaitime"]}]
    assert finish.footer_line(db.get("7", bid)) == "@chinar.cafe  ·  chinarcafe.in  ·  Lal Chowk · 98765 43210"


def test_dark_logo_is_kept_separately(store):
    bid = brand()
    buf = io.BytesIO()
    Image.new("RGBA", (60, 60), (255, 255, 255, 255)).save(buf, "PNG")
    r = app().post(f"/brands/{bid}/logo?variant=dark", files={"file": ("l.png", buf.getvalue(), "image/png")})
    assert r.json()["brand"]["logo_dark"] == f"brand-{bid}-logo-dark.png" and r.json()["brand"]["logo"] == ""
    assert r.json()["suggested_colors"] == []


# ------------------------------------------------------------ photo library

def test_photos_are_uploaded_listed_and_removed(store):
    bid = brand()
    name = photo(bid, w=4000, h=1000)
    with Image.open(store / "7" / name) as im:
        assert im.format == "JPEG" and max(im.size) == routes.PHOTO_MAX_SIDE      # capped, re-encoded
    listed = app().get(f"/brands/{bid}/assets").json()
    assert [a["name"] for a in listed] == [name] and listed[0]["width"] == 3000
    assert app().delete(f"/brands/{bid}/assets/{listed[0]['id']}").status_code == 200
    assert app().get(f"/brands/{bid}/assets").json() == []
    bad = app().post(f"/brands/{bid}/assets", files={"file": ("x.jpg", b"not a photo", "image/jpeg")})
    assert bad.status_code == 422


def test_photos_and_posts_are_per_user(store):
    bid = brand()
    name = photo(bid)
    other = app("9")
    assert other.get(f"/brands/{bid}/assets").status_code == 404
    assert other.post(f"/brands/{bid}/assets", files={"file": ("a.jpg", _jpeg(), "image/jpeg")}).status_code == 404
    assert other.post(f"/brands/{bid}/preview", json={"image": name}).status_code == 404
    pid = app().post(f"/brands/{bid}/posts", json={"image": name, "words": {"headline": "Hi"}}).json()["id"]
    assert other.get(f"/posts/{pid}/zip").status_code == 404
    assert other.post(f"/posts/{pid}/review-link").status_code == 404


def test_free_cant_use_the_studio_but_plus_can(store, monkeypatch):
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: False)
    free_bid = brand("8")                                   # made while billing was off
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: True)
    r = app("8").post(f"/brands/{free_bid}/assets", files={"file": ("a.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 402                             # Free has no brand slots: the brand is paused
    assert photo(brand("9"), "9")                           # Plus: the studio works


# ------------------------------------------------------------ preview and posts

def test_preview_is_a_small_jpeg_even_without_a_photo(store):
    bid = brand()
    r = app().post(f"/brands/{bid}/preview", json={"layout": "offer", "size": "story", "words": {"price": "20% OFF"}})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(r.content)) as im:
        assert max(im.size) == 720 and im.size[1] > im.size[0]                    # 9:16, scaled down
    assert app().post(f"/brands/{bid}/preview", json={"layout": "nope"}).status_code == 422
    assert app().post(f"/brands/{bid}/preview", json={"image": "missing.jpg"}).status_code == 422


def test_preview_shows_any_carousel_slide_and_the_closing_one(store):
    bid = brand()
    a, b = photo(bid), photo(bid, color=(20, 90, 160))
    slides = [{"image": a, "headline": "One"}, {"image": b, "headline": "Two"}]
    for i in (0, 1, 2):
        r = app().post(f"/brands/{bid}/preview", json={"slides": slides, "slide": i, "size": "portrait"})
        assert r.status_code == 200
    with Image.open(io.BytesIO(r.content)) as im:                                 # the closing slide: brand colour
        assert im.getpixel((5, 5)) == pytest.approx((168, 64, 44), abs=8)


def test_a_post_renders_every_size_and_goes_in_the_library(store):
    bid = brand()
    name = photo(bid)
    sizes = list(finish.SIZES)
    p = app().post(f"/brands/{bid}/posts", json={"image": name, "layout": "event", "sizes": sizes,
                                                 "words": {"headline": "Sufi Night", "subline": "Sat 7 pm", "cta": "Book"}}).json()
    assert p["kind"] == "single" and [f["size"] for f in p["files"]] == sizes
    for f in p["files"]:
        with Image.open(store / "7" / f["name"]) as im:
            assert im.size == (f["width"], f["height"])
    listing = app().get("/brands").json()["brands"][0]
    assert listing["posts"] == 1 and listing["cover"] == p["files"][0]["name"]
    assert [x["id"] for x in app().get(f"/brands/{bid}/posts").json()] == [p["id"]]
    assert app().delete(f"/posts/{p['id']}").status_code == 200
    assert app().get(f"/brands/{bid}/posts").json() == []


def test_carousels_are_pro(store):
    bid = brand("9")
    a = photo(bid, "9")
    body = {"slides": [{"image": a, "headline": "One"}, {"image": a, "headline": "Two"}], "sizes": ["portrait", "story"]}
    r = app("9").post(f"/brands/{bid}/posts", json=body)
    assert r.status_code == 402 and r.json()["detail"]["plan_needed"] == "pro"
    pro_bid = brand()
    b = photo(pro_bid)
    body["slides"] = [{"image": b, "headline": "One"}, {"image": b, "headline": "Two"}]
    p = app().post(f"/brands/{pro_bid}/posts", json=body).json()
    assert p["kind"] == "carousel"
    assert [(f["slide"], f["size"]) for f in p["files"]] == [(1, "portrait"), (2, "portrait"), (3, "portrait")]  # story isn't a carousel size


def test_zip_has_every_file_and_the_captions(store):
    bid = brand()
    p = app().post(f"/brands/{bid}/posts", json={"image": photo(bid), "sizes": ["post", "portrait"],
                                                 "words": {"headline": "Kahwa"}}).json()
    db.update_post("7", p["id"], captions={"instagram": {"text": "Warm up ☕", "hashtags": ["#kahwa"], "first_comment": "#kahwa"}})
    r = app().get(f"/posts/{p['id']}/zip")
    assert r.headers["content-type"] == "application/zip" and "chinar-caf" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        assert sorted(names) == sorted([f["name"] for f in p["files"]] + ["captions.txt"])
        assert "Warm up ☕" in z.read("captions.txt").decode()


# ------------------------------------------------------------ captions

def _fake_model(monkeypatch, text):
    import harness.providers as providers

    class P:
        model = "gpt-5-nano"

        async def chat(self, *_a, **_k):
            return SimpleNamespace(text=text, input_tokens=300, output_tokens=200)
    monkeypatch.setattr(providers, "get_provider", lambda: P())


def test_captions_follow_each_platforms_rules(store, monkeypatch):
    bid = brand(hashtags=None)
    app().patch(f"/brands/{bid}", json={"hashtags": [{"name": "Always", "tags": ["chinarcafe"]}]})
    p = app().post(f"/brands/{bid}/posts", json={"image": photo(bid), "words": {"headline": "Kahwa ₹80"}}).json()
    _fake_model(monkeypatch, json.dumps({
        "instagram": {"text": "Cold outside? ☕", "hashtags": ["kahwa", "#srinagar"], "first_comment": ""},
        "x": {"text": "x" * 400, "hashtags": ["#a", "#b", "#c"]},
        "whatsapp": {"text": "Kahwa is back!", "hashtags": ["#nope"]},
        "linkedin": {"text": "not asked for"}}))
    charged = []
    monkeypatch.setattr(entitlements, "settle", lambda uid, usd, tid=None: charged.append(float(usd)))
    out = app().post(f"/posts/{p['id']}/captions", json={"platforms": ["instagram", "x", "whatsapp"]}).json()["captions"]
    assert set(out) == {"instagram", "x", "whatsapp"}
    assert out["instagram"]["hashtags"][0] == "#chinarcafe"                         # the brand's own first
    assert out["instagram"]["first_comment"] == " ".join(out["instagram"]["hashtags"])
    assert len(out["x"]["text"]) + 1 + len(" ".join(out["x"]["hashtags"])) <= 280 and len(out["x"]["hashtags"]) == 2
    assert out["whatsapp"]["hashtags"] == []
    assert charged and charged[0] > 0
    edited = app().patch(f"/posts/{p['id']}/captions", json={"platform": "x", "text": "Short."}).json()
    assert edited["captions"]["x"]["text"] == "Short." and edited["captions"]["instagram"]["text"] == "Cold outside? ☕"


def test_hashtags_are_never_posted_twice():
    b = db.BrandRow(id=1, name="C")
    out = captions.clean({"x": {"text": "Weekend #Kahwa at Chinar Café! #ChinarCafe #WeekendKahwa", "hashtags": ["#ChinarCafe", "#WeekendKahwa"]},
                          "facebook": {"text": "Come in #today", "hashtags": ["#kahwa"]}}, ["x", "facebook"], b)
    assert out["x"]["text"] == "Weekend #Kahwa at Chinar Café!"                 # trailing tags in the list go
    assert out["facebook"]["text"] == "Come in #today"                          # a tag not in the list stays
    inline = captions.clean({"x": {"text": "Love #ChinarCafe mornings", "hashtags": ["#ChinarCafe"]}}, ["x"], b)
    assert inline["x"]["text"] == "Love ChinarCafe mornings"                    # inline: the word stays, the # goes


def test_garbled_captions_are_a_502_not_a_crash(store, monkeypatch):
    bid = brand()
    p = app().post(f"/brands/{bid}/posts", json={"image": photo(bid)}).json()
    _fake_model(monkeypatch, "sorry, I can't")
    assert app().post(f"/posts/{p['id']}/captions", json={}).status_code == 502


def test_caption_prompt_carries_the_kit_and_never_invites_made_up_facts():
    b = db.BrandRow(id=1, name="Chinar Café", voice="warm", handle="chinarcafe", cta="Order now",
                    hashtags=[{"name": "Always", "tags": ["#chinarcafe"]}])
    s = captions._post_summary(b, {"headline": "Kahwa", "price": "₹80"}, "offer", [])
    assert "Handle: chinarcafe" in s and "#chinarcafe" in s and "Post price: ₹80" in s
    assert "Never invent prices" in captions._PROMPT


# ------------------------------------------------------------ client review

def _post(bid=None):
    bid = bid or brand()
    return app().post(f"/brands/{bid}/posts", json={"image": photo(bid), "sizes": ["post", "story"],
                                                    "words": {"headline": "Kahwa"}}).json()


def test_review_link_shows_only_that_post_and_records_the_decision(store, monkeypatch):
    pushed = []

    async def fake_push(uid, title, body, **kw):
        pushed.append((uid, title, body))
        return 1
    import harness.push as push
    monkeypatch.setattr(push, "send", fake_push)
    p = _post()
    link = app().post(f"/posts/{p['id']}/review-link").json()
    token = link["token"]
    assert link["url"].endswith(f"/review/{token}")
    page = public().get(f"/review/{token}").json()
    assert page["brand"]["name"] == "Chinar Café" and page["post"]["review_status"] == "waiting"
    assert "brand_id" not in page["post"]
    assert public().get(f"/review/{token}/files/{p['files'][0]['name']}").status_code == 200
    other = _post()
    assert public().get(f"/review/{token}/files/{other['files'][0]['name']}").status_code == 404   # not this post's
    assert public().get(f"/review/{token}/files/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert public().post(f"/review/{token}", json={"decision": "changes", "comment": " "}).status_code == 422
    r = public().post(f"/review/{token}", json={"decision": "changes", "comment": "Bigger logo please", "name": "Asif"})
    assert r.json() == {"status": "changes", "comment": "Asif: Bigger logo please"}
    assert db.get_post("7", p["id"]).review_status == "changes"
    assert pushed and pushed[0][0] == "7" and "changes" in pushed[0][1]


def test_bad_or_expired_review_links_are_gone(store):
    p = _post()
    good = review.make(p["id"], "7")
    assert public().get(f"/review/{good[:-2]}xx").status_code == 410
    old = review.make(p["id"], "7", ttl_s=10, now=time.time() - 100)
    assert public().get(f"/review/{old}").status_code == 410
    forged = review.make(p["id"], "9")                         # someone else's id in a valid token
    assert public().get(f"/review/{forged}").status_code == 410
    from harness import approval_links
    assert public().get(f"/review/{approval_links.make(str(p['id']), '7')}").status_code == 410   # other key


def test_review_links_are_pro(store):
    bid = brand("9")
    p = app("9").post(f"/brands/{bid}/posts", json={"image": photo(bid, "9")}).json()
    r = app("9").post(f"/posts/{p['id']}/review-link")
    assert r.status_code == 402 and r.json()["detail"]["plan_needed"] == "pro"


# ------------------------------------------------------------ rendering

@pytest.mark.parametrize("layout", list(finish.LAYOUTS))
def test_every_layout_renders_every_size_with_long_words(layout):
    b = db.BrandRow(id=1, name="A Very Long Brand Name Indeed", colors=[{"role": "primary", "hex": "#123456"}],
                    font="script", handle="averylonghandle", website="example.com", footer="Shop 4, Main Road")
    src = Image.new("RGB", (800, 600), (200, 180, 150))
    words = finish.Words("A very long headline that will not fit on two lines of any post at all " * 2,
                         "And a sub-line that goes on and on about the place and the date " * 2, "₹1,99,999", "Book now")
    logo = Image.new("RGBA", (300, 120), (10, 10, 10, 255))
    for size, (w, h, _l) in finish.SIZES.items():
        img = finish.render(src, b, size, layout=layout, words=words, logo=logo, src2=src, scale=0.3)
        assert img.size == (round(w * 0.3), round(h * 0.3))


def test_fit_never_spills():
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f, lines = finish.fit(d, "word " * 200, "sans", 300, 60, 40, 10, max_lines=2)
    assert len(lines) <= 2 and all(d.textlength(ln, font=f) <= 300 for ln in lines) and lines[-1].endswith("…")


def test_story_keeps_words_out_of_the_apps_strips():
    b = db.BrandRow(id=1, name="X", colors=[{"role": "primary", "hex": "#FF0000"}, {"role": "secondary", "hex": "#FFFFFF"}])
    img = finish.render(Image.new("RGB", (900, 1600), (0, 0, 255)), b, "story", layout="band",
                        words={"headline": "Hello there"}, scale=0.5)
    w, h = img.size
    bottom_strip = [img.getpixel((w // 2, y)) for y in range(int(h * 0.86), h)]
    assert all(px[0] < 200 or px[2] > 50 for px in bottom_strip)            # no red band in the reply-bar strip


# ------------------------------------------------------------ the chat tool

def test_tool_saves_posts_to_the_brand_library_and_gates_carousels(store, monkeypatch):
    bid = brand("9")
    b = db.get("9", bid)
    name = photo(bid, "9")
    tool = brand_tools.make_finish_image_tool("9", b)
    out = asyncio.run(tool.handler(image=name, headline="Kahwa", layout="offer", price="20% OFF"))
    assert out.ui["post_id"] and out.ui["layout"] == "offer"
    assert db.list_posts("9", bid)[0].words == {"headline": "Kahwa", "price": "20% OFF"}
    up = asyncio.run(tool.handler(slides=[{"image": name, "headline": "One"}, {"image": name}]))
    assert up.ui["kind"] == "upgrade" and up.ui["plan"] == "pro"


def test_tool_makes_a_carousel_on_pro(store):
    bid = brand()
    name = photo(bid)
    tool = brand_tools.make_finish_image_tool("7", db.get("7", bid))
    out = asyncio.run(tool.handler(slides=[{"image": name, "headline": "One"}, {"image": name, "headline": "Two"}],
                                   sizes=["portrait"]))
    assert out.ui["post_kind"] == "carousel" and [f["slide"] for f in out.ui["files"]] == [1, 2, 3]
    assert "No image named" in asyncio.run(tool.handler(slides=[{"image": "nope.jpg"}]))
