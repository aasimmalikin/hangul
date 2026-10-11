"""Brands (harness.brands): setup from one sentence, plan slots and bought
slots, paused-not-deleted after a downgrade, per-user isolation, the logo's
colours, and the prompt text a brand adds."""
import asyncio
import io

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
from harness.api.routes import brands as brand_routes
from harness.billing import entitlements
from harness.brands import templates
from harness.brands.palette import colors_from_logo
from harness.brands.prompt import brand_block, style_line
from harness.db import billing as billing_db
from harness.db import brands as db
from harness.db.models import Brand, BrandAsset, BrandPost, User
from harness.tools.builtin import files


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
    return maker


def client(user="7"):
    app = FastAPI()
    app.include_router(brand_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user}
    return TestClient(app)


def set_plan(store, uid, plan, extra=0):
    with store() as s:
        u = s.get(User, uid)
        u.plan, u.extra_brands = plan, extra
        s.commit()


# ------------------------------------------------------------ templates

@pytest.mark.parametrize("sentence,kind", [
    ("A small café in Srinagar, cosy, students and tourists", "cafe"),
    ("my wazwan restaurant near Dal Lake", "restaurant"),
    ("a pashmina shawl boutique", "boutique"),
    ("dental clinic in Baramulla", "clinic"),
    ("JEE coaching classes for class 11", "tutor"),
    ("we make wedding decor", "events"),
    ("drone repair", None),
])
def test_match_kind(sentence, kind):
    assert templates.match_kind(sentence) == kind


def test_every_look_is_complete():
    ids = set()
    for k, (_label, _kw, looks) in templates.KINDS.items():
        assert len(looks) == 3, k
        for lk in looks:
            assert lk.id not in ids and lk.font in templates.FONT_KEYS
            assert [r for r, _h in lk.colors] == list(templates.ROLES)
            ids.add(lk.id)


def test_name_is_guessed_from_the_sentence():
    assert templates.guess_name("My café called Chinar Café in Srinagar") == "Chinar Café"
    assert templates.guess_name("a cosy café") == ""


def test_suggest_a_known_kind_costs_nothing(monkeypatch):
    import harness.providers as providers
    monkeypatch.setattr(providers, "get_provider", lambda: pytest.fail("no model call for a known kind"))
    out = asyncio.run(templates.suggest("a bakery called Sweet Crumbs"))
    assert out["kind"] == "cafe" and out["name"] == "Sweet Crumbs" and len(out["looks"]) == 3


def test_suggest_an_unknown_kind_asks_the_cheap_model_and_falls_back(monkeypatch):
    import json
    from types import SimpleNamespace

    import harness.providers as providers
    looks = [{"label": f"L{i}", "colors": ["#111111", "#FAFAFA", "#FF0000", "#000000"], "style": "s", "voice": "v",
              "font": "sans"} for i in range(3)]

    class P:
        model = "gpt-5-nano"

        async def chat(self, *_a, **_k):
            return SimpleNamespace(text=json.dumps({"name": "SkyFix", "kind": "Drone repair", "looks": looks}),
                                   input_tokens=100, output_tokens=200)
    monkeypatch.setattr(providers, "get_provider", lambda: P())
    out = asyncio.run(templates.suggest("drone repair"))
    assert out["name"] == "SkyFix" and [lk["id"] for lk in out["looks"]] == ["custom-1", "custom-2", "custom-3"]

    class Broken(P):
        async def chat(self, *_a, **_k):
            raise RuntimeError("down")
    monkeypatch.setattr(providers, "get_provider", lambda: Broken())
    assert len(asyncio.run(templates.suggest("drone repair"))["looks"]) == 3


# ------------------------------------------------------------ slots and CRUD

def test_create_from_a_look_and_list(store):
    r = client().post("/brands", json={"name": "Chinar Café", "look": "cafe-heritage"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["kind"] == "cafe" and b["font"] == "serif" and b["colors"][0] == {"role": "primary", "hex": "#A8402C"}
    listing = client().get("/brands").json()
    assert (listing["slots"], listing["used"], listing["can_add"]) == (3, 1, True)


def test_own_choices_override_the_look(store):
    b = client().post("/brands", json={"name": "X", "look": "cafe-warm", "font": "sans",
                                       "colors": [{"role": "primary", "hex": "#00ff00"}]}).json()
    assert b["font"] == "sans" and b["colors"] == [{"role": "primary", "hex": "#00FF00"}]
    assert client().post("/brands", json={"name": "Y"}).status_code == 422          # no look, no colours
    assert client().post("/brands", json={"name": "Y", "look": "cafe-warm", "font": "comic"}).status_code == 422


def test_plan_limits_and_bought_slots(store):
    r = client("8").post("/brands", json={"name": "A", "look": "cafe-warm"})
    assert r.status_code == 402 and r.headers["X-Reason"] == "brand_limit"
    assert r.json()["detail"]["plan_needed"] == "plus"

    assert client("9").post("/brands", json={"name": "A", "look": "cafe-warm"}).status_code == 200
    r = client("9").post("/brands", json={"name": "B", "look": "cafe-warm"})
    assert r.status_code == 402 and r.json()["detail"]["buy"] == "brand_slot"
    db.add_slots("9", 1)
    assert client("9").post("/brands", json={"name": "B", "look": "cafe-warm"}).status_code == 200


def test_downgrade_pauses_never_deletes_and_hiding_frees_a_slot(store):
    ids = [client().post("/brands", json={"name": n, "look": "shop-fresh"}).json()["id"] for n in ("A", "B", "C")]
    set_plan(store, 7, "plus")
    brands = client().get("/brands").json()["brands"]
    assert [b["paused"] for b in brands] == [False, True, True]
    assert db.usable("7", ids[1]) is None and db.usable("7", ids[0]).name == "A"
    assert client().delete(f"/brands/{ids[0]}").status_code == 200
    assert [b["paused"] for b in client().get("/brands").json()["brands"]] == [False, True]


def test_another_users_brand_is_a_404(store):
    bid = client().post("/brands", json={"name": "Mine", "look": "cafe-warm"}).json()["id"]
    other = client("9")
    assert other.patch(f"/brands/{bid}", json={"voice": "x"}).status_code == 404
    assert other.delete(f"/brands/{bid}").status_code == 404
    assert other.post(f"/brands/{bid}/logo", files={"file": ("l.png", b"x", "image/png")}).status_code == 404
    assert db.get("7", bid).voice != "x"


def test_billing_off_opens_brands(store, monkeypatch):
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: False)
    assert client("8").post("/brands", json={"name": "A", "look": "cafe-warm"}).status_code == 200
    assert client("8").get("/brands").json()["slots"] == db.BILLING_OFF_SLOTS


def test_brand_name_is_matched_as_whole_words(store):
    client().post("/brands", json={"name": "Chinar Café", "look": "cafe-warm"})
    client().post("/brands", json={"name": "Chinar", "look": "cafe-warm"})
    assert db.match_name("7", "a poster for chinar café this sunday").name == "Chinar Café"
    assert db.match_name("7", "photos of Chinar trees").name == "Chinar"
    assert db.match_name("7", "photos of Chinars") is None


# ------------------------------------------------------------ logo

def _png(colours: list[tuple[int, int, int]]) -> bytes:
    im = Image.new("RGBA", (90, 30), (255, 255, 255, 0))
    for i, c in enumerate(colours):
        im.paste(c + (255,), (i * 30, 0, i * 30 + 30, 30))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_logo_is_stored_and_its_colours_suggested(store, tmp_path):
    bid = client().post("/brands", json={"name": "C", "look": "cafe-warm"}).json()["id"]
    r = client().post(f"/brands/{bid}/logo", files={"file": ("logo.png", _png([(168, 64, 44), (168, 64, 44), (40, 30, 25)]), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["brand"]["logo"] == f"brand-{bid}-logo.png" and (tmp_path / "7" / f"brand-{bid}-logo.png").is_file()
    primary = r.json()["suggested_colors"][0]["hex"]
    assert abs(int(primary[1:3], 16) - 168) < 20                      # the logo's red, not the transparent ground
    bad = client().post(f"/brands/{bid}/logo", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 422


def test_colors_from_logo_roles(tmp_path):
    p = tmp_path / "l.png"
    p.write_bytes(_png([(21, 101, 192), (38, 166, 154), (16, 38, 61)]))
    roles = [c["role"] for c in colors_from_logo(p)]
    assert roles == ["primary", "secondary", "accent", "text"]


# ------------------------------------------------------------ prompt

def test_brand_prompt_text():
    b = db.BrandRow(id=1, name="Chinar Café", colors=[{"role": "primary", "hex": "#A8402C"}],
                    style="warm light", voice="playful")
    block = brand_block(b)
    assert "Chinar Café" in block and "#A8402C" in block and "finish_image" in block and "playful" in block
    assert "No text" in style_line(b) and "warm light" in style_line(b)


# ------------------------------------------------------------ runs and tools

from types import SimpleNamespace  # noqa: E402

from harness.api.routes import ask as ask_route  # noqa: E402
from harness.tools.builtin import brand_tools, images  # noqa: E402


def _req(**kw):
    return ask_route.AskRequest(question=kw.pop("question", "hi"), **kw)


def test_run_brand_is_asked_for_inherited_or_named(store):
    a = client().post("/brands", json={"name": "Chinar Café", "look": "cafe-warm"}).json()["id"]
    b = client().post("/brands", json={"name": "Zara Boutique", "look": "bout-bright"}).json()["id"]
    run = lambda req, conv=None: asyncio.run(ask_route.resolve_brand(req, "7", conv))  # noqa: E731
    assert run(_req(brand_id=b)).id == b
    assert run(_req(), SimpleNamespace(brand_id=a)).id == a                         # the chat's brand
    assert run(_req(brand_id=0), SimpleNamespace(brand_id=a)) is None               # switched off
    assert run(_req(question="poster for zara boutique", connectors_auto=True)).id == b
    assert run(_req(question="poster for zara boutique")) is None                   # auto apps off: no guessing


def test_asking_for_an_unusable_brand_is_refused(store):
    from fastapi import HTTPException
    bid = client().post("/brands", json={"name": "Mine", "look": "cafe-warm"}).json()["id"]
    with pytest.raises(HTTPException) as e:
        asyncio.run(ask_route.check_brand_request(_req(brand_id=bid), "9"))         # someone else's
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        asyncio.run(ask_route.check_brand_request(_req(brand_id=bid), "8"))         # Free: no brands at all
    assert e.value.status_code == 402 and e.value.detail["plan_needed"] == "plus"
    set_plan(store, 7, "free")                                                       # inherited after a downgrade:
    assert asyncio.run(ask_route.resolve_brand(_req(), "7", SimpleNamespace(brand_id=bid))) is None   # dropped quietly


def _photo(folder, name="kahwa.jpg"):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), (150, 90, 40)).save(folder / name)
    return name


def test_finish_image_writes_each_size_with_the_brand(store, tmp_path):
    name = _photo(tmp_path / "7")
    brand = db.BrandRow(id=1, name="Chinar Café", colors=[{"role": "primary", "hex": "#A8402C"}], font="serif")
    tool = brand_tools.make_finish_image_tool("7", brand)
    out = asyncio.run(tool.handler(image=name, headline="Kahwa ₹80", sizes=["post", "story", "a4", "nope"]))
    assert out.ui["kind"] == "brand_set" and out.ui["brand"] == "Chinar Café"
    sizes = {f["size"]: (f["width"], f["height"]) for f in out.ui["files"]}
    assert sizes == {"post": (1080, 1080), "story": (1080, 1920), "a4": (2480, 3508)}
    for f in out.ui["files"]:
        with Image.open(tmp_path / "7" / f["name"]) as im:
            assert im.size == (f["width"], f["height"])
            if f["size"] != "story":      # a story's band is a card above the safe line instead
                assert im.getpixel((5, f["height"] - 5)) == pytest.approx((168, 64, 44), abs=6)   # the brand's band
    again = asyncio.run(tool.handler(image=name, headline="Kahwa ₹80", sizes=["post"]))
    assert again.ui["files"][0]["name"] != out.ui["files"][0]["name"]                 # never overwrites


def test_finish_image_long_text_stays_inside(tmp_path):
    from harness.brands.finish import render
    brand = db.BrandRow(id=1, name="X", colors=[{"role": "primary", "hex": "#000000"}, {"role": "secondary", "hex": "#FFFFFF"}],
                        font="display")
    img = render(Image.new("RGB", (900, 900), (0, 0, 0)), brand, "post",
                 headline="An extremely long headline that would never fit on one line of a square post " * 3,
                 subline="आज का खास · Lal Chowk")
    # nothing white touches the right edge: the text was shrunk, wrapped or trimmed
    assert all(img.getpixel((1079, y)) != (255, 255, 255) for y in range(700, 1080))


def test_finish_image_names_the_images_there_are(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "SESSIONS", tmp_path)
    _photo(tmp_path / "7", "shop.png")
    out = asyncio.run(brand_tools.make_finish_image_tool("7").handler(image="../../etc/passwd.png"))
    assert "No image named 'passwd.png'" in out and "shop.png" in out


def _fake_images(monkeypatch, calls):
    async def call(**kw):
        calls.append(kw)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"\x89PNG fake").decode())])
    import harness.providers as providers
    monkeypatch.setattr(providers, "get_provider", lambda: SimpleNamespace(client=SimpleNamespace(
        images=SimpleNamespace(generate=call, edit=call))))


import base64  # noqa: E402


def test_edit_image_keeps_the_photo_close_and_charges(store, tmp_path, monkeypatch):
    calls, charged = [], []
    _fake_images(monkeypatch, calls)
    monkeypatch.setattr(entitlements, "settle", lambda uid, cost, tid: charged.append(cost))
    name = _photo(tmp_path / "7")
    brand = db.BrandRow(id=1, name="Chinar Café", colors=[{"role": "primary", "hex": "#A8402C"}], style="warm light")
    out = asyncio.run(images.make_edit_image_tool("7", "t1", brand).handler(image=name, instruction="on a marble table"))
    kw = calls[0]
    assert kw["input_fidelity"] == "high" and kw["size"] == "1536x1024"               # the photo's own shape
    assert "marble" in kw["prompt"] and "warm light" in kw["prompt"] and "No text" in kw["prompt"]
    assert kw["image"][2] == "image/png" and out.ui["source"] == name
    assert (tmp_path / "7" / out.ui["name"]).read_bytes() == b"\x89PNG fake"
    assert float(charged[0]) == pytest.approx(0.25 + images.EDIT_INPUT_USD)
    assert "No image named" in asyncio.run(images.make_edit_image_tool("7").handler(image="nope.jpg", instruction="x y z"))


def test_generate_image_follows_the_brand(store, monkeypatch):
    calls = []
    _fake_images(monkeypatch, calls)
    monkeypatch.setattr(entitlements, "settle", lambda *a: None)
    brand = db.BrandRow(id=1, name="Chinar Café", colors=[{"role": "primary", "hex": "#A8402C"}], style="warm light")
    asyncio.run(images.make_generate_image_tool("7", None, brand).handler(prompt="a cup of kahwa"))
    asyncio.run(images.make_generate_image_tool("7").handler(prompt="a cup of kahwa"))
    assert "Chinar Café" in calls[0]["prompt"] and "#A8402C" in calls[0]["prompt"]
    assert calls[1]["prompt"] == "a cup of kahwa"


def test_brand_tools_are_plan_gated():
    from harness.billing.plans import PLANS, plan_allows_tool
    assert not plan_allows_tool(PLANS["free"], "finish_image") and plan_allows_tool(PLANS["plus"], "finish_image")
    assert not plan_allows_tool(PLANS["plus"], "edit_image") and plan_allows_tool(PLANS["pro"], "edit_image")


def test_brands_tool_lists_and_starts_setup(store):
    tool = brand_tools.make_brands_tool("7")
    assert "no brands yet" in asyncio.run(tool.handler(action="list"))
    out = asyncio.run(tool.handler(action="setup", description="a pashmina shawl shop"))
    assert out.ui["kind"] == "brand_setup" and len(out.ui["suggestion"]["looks"]) == 3
    client().post("/brands", json={"name": "Chinar Café", "look": "cafe-warm"})
    assert "Chinar Café" in asyncio.run(tool.handler(action="list"))


# ------------------------------------------------------------ buying a slot

def test_paying_for_brand_slots_adds_them(store, monkeypatch):
    from harness.billing import dodo
    monkeypatch.setenv("DODO_PRODUCT_BRAND_SLOT", "pdt_slot")
    monkeypatch.setenv("DODO_PRODUCT_TOPUP", "pdt_topup")
    monkeypatch.setattr(dodo.ledger, "record_transaction", lambda **kw: None)
    pay = {"type": "payment.succeeded", "data": {"payment_id": "p1", "metadata": {"user_id": "9"},
           "product_cart": [{"product_id": "pdt_slot", "quantity": 2}, {"product_id": "pdt_topup", "quantity": 1}]}}
    assert dodo.apply_event(pay) == "topup+brand_slot"
    assert db.slots("9") == 1 + 2                                                    # Plus includes one
    assert dodo.apply_event({"type": "payment.succeeded", "data": {"metadata": {"user_id": "9"},
                             "product_cart": [{"product_id": "pdt_other"}]}}) == "ignored:payment"


def test_checkout_sells_the_regional_slot_when_it_exists(monkeypatch):
    from harness.api.routes.billing import checkout_product
    monkeypatch.setenv("DODO_PRODUCT_BRAND_SLOT", "pdt_slot")
    assert checkout_product("brand_slot", "month", "in") == "brand_slot"
    monkeypatch.setenv("DODO_PRODUCT_BRAND_SLOT_IN", "pdt_slot_in")
    assert checkout_product("brand_slot", "month", "in") == "brand_slot_in"
    assert checkout_product("brand_slot", "year", "intl") == "brand_slot"
