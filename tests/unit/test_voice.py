"""Voice (media/voice.py, routes/voice.py): speech-to-text and streamed
text-to-speech, metered on the user's allowance. A fake OpenAI client; no
network, no model."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import voice as voice_route
from harness.billing import entitlements
from harness.media import voice


class FakeSpeechStream:
    def __init__(self, chunks):
        self.chunks = chunks
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def iter_bytes(self, n):
        for c in self.chunks:
            yield c


@pytest.fixture
def fake_openai(monkeypatch):
    calls = {"stt": [], "tts": [], "charged": []}

    async def transcriptions_create(**kw):
        calls["stt"].append(kw)
        return SimpleNamespace(text="  remind me to drink water in two minutes ")

    def speech_create(**kw):
        calls["tts"].append(kw)
        return FakeSpeechStream([b"ID3", b"\x00audio"])

    client = SimpleNamespace(audio=SimpleNamespace(
        transcriptions=SimpleNamespace(create=transcriptions_create),
        speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=speech_create))))
    import harness.providers as providers
    monkeypatch.setattr(providers, "get_provider", lambda: SimpleNamespace(client=client))
    monkeypatch.setattr(entitlements, "settle", lambda uid, cost, tid: calls["charged"].append((uid, cost)))
    return calls


def test_transcribe_returns_clean_text_and_charges(fake_openai):
    text = asyncio.run(voice.transcribe(b"x" * 32_000, "speech.webm", user_id="7", seconds=30))
    assert text == "remind me to drink water in two minutes"
    assert fake_openai["stt"][0]["model"] == "gpt-4o-mini-transcribe"
    assert fake_openai["stt"][0]["file"][2] == "audio/webm"
    (uid, cost), = fake_openai["charged"]
    assert uid == "7" and cost == Decimal("0.0015")          # 30 s at $0.003/min


def test_billed_length_cannot_be_talked_down():
    # a client claiming 1 s for a 160 KB recording is billed by size (>= 10 s)
    assert voice.estimate_seconds(b"x" * 160_000, 1) == 10
    assert voice.estimate_seconds(b"x", 10_000) == voice.MAX_SECONDS


def test_bad_audio_is_refused(fake_openai):
    with pytest.raises(voice.VoiceError):
        asyncio.run(voice.transcribe(b"", "a.webm"))
    with pytest.raises(voice.VoiceError):
        asyncio.run(voice.transcribe(b"x", "a.exe"))


def test_speech_text_drops_what_reads_badly():
    said = voice.speech_text("## Plan\n- **Buy** milk\n- See [the list](https://x.y/z)\n```py\nprint(1)\n```\nDone: https://a.b/c")
    assert said == "Plan Buy milk See the list (code shown on screen) Done: (link on screen)"


def test_speak_streams_and_charges_by_length(fake_openai):
    async def collect():
        return b"".join([c async for c in voice.speak("Hello there, it is sunny today.", user_id="7")])
    assert asyncio.run(collect()) == b"ID3\x00audio"
    assert fake_openai["tts"][0]["model"] == "gpt-4o-mini-tts" and fake_openai["tts"][0]["response_format"] == "mp3"
    assert fake_openai["charged"][0][0] == "7"


# ------------------------------------------------------------- routes

def _client(user_id="7"):
    app = FastAPI()
    app.include_router(voice_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id}
    return TestClient(app)


def test_transcribe_route(fake_openai):
    r = _client().post("/voice/transcribe", files={"file": ("speech.webm", b"x" * 8000, "audio/webm")},
                       data={"seconds": "3"})
    assert r.status_code == 200 and r.json()["text"].startswith("remind me")


def test_speak_route_streams_mp3(fake_openai):
    r = _client().post("/voice/speak", json={"text": "Take an umbrella."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3\x00audio"
    assert _client().post("/voice/speak", json={"text": "** __ **"}).status_code == 400   # nothing sayable


def test_voice_is_refused_when_nothing_is_left_to_spend(fake_openai, monkeypatch):
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: True)
    monkeypatch.setattr(entitlements, "standing", lambda uid: SimpleNamespace(
        can_spend=False, pool_exhausted=False, allowance_left=Decimal("0"), plan=SimpleNamespace(id="free")))
    r = _client().post("/voice/speak", json={"text": "hi"})
    assert r.status_code == 402 and r.headers["X-Reason"] == "insufficient_balance"
    assert fake_openai["tts"] == []
