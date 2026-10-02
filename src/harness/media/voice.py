"""Speech in and out, on the user's allowance.

* ``transcribe``: audio -> text (the mic button, hands-free mode, voice notes).
* ``speak``: text -> streamed MP3 (read-aloud, hands-free replies). Streamed so
  playback starts after the first bytes, not after the whole answer.

Voice is a front end on the normal chat pipeline, not a second agent: the
transcript is sent as an ordinary message, so every tool, approval, memory,
billing and security rule applies unchanged. Costs here are estimated from
audio length / text length at the rates in settings and charged through
``entitlements.settle`` like any other model spend.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

from harness.config import get_settings
from harness.logging import log

AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".wav": "audio/wav",
               ".webm": "audio/webm", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".mpga": "audio/mpeg"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024          # same cap as every upload (~10 min of speech)
MAX_SECONDS = 15 * 60
MAX_SPEAK_CHARS = 4000                      # the TTS input limit is 4096


class VoiceError(ValueError):
    pass


def _charge(user_id: str | None, usd: float, what: str) -> None:
    if not user_id or usd <= 0:
        return
    try:
        from harness.billing import entitlements
        entitlements.settle(user_id, Decimal(str(round(usd, 6))), None)
    except Exception as e:  # noqa: BLE001 - bookkeeping must not lose the audio
        log.warning("voice cost not recorded", what=what, error=str(e))


def estimate_seconds(data: bytes, claimed: float | None) -> float:
    """What to bill for. The client's duration is trusted only up to a cap and
    never below a floor from the size (compressed speech is >= ~4 KB/s)."""
    floor = len(data) / 16_000
    claimed = max(0.0, min(float(claimed or 0), MAX_SECONDS))
    return max(floor, claimed, 1.0)


async def transcribe(data: bytes, filename: str, *, user_id: str | None = None,
                     seconds: float | None = None, language: str | None = None) -> str:
    from harness.providers import get_provider

    if not data:
        raise VoiceError("No audio received.")
    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceError("That recording is too long (max about 10 minutes).")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".webm"
    if ext not in AUDIO_TYPES:
        raise VoiceError(f"Unsupported audio type '{ext}'.")
    s = get_settings()
    kwargs = dict(model=s.stt_model, file=(f"audio{ext}", data, AUDIO_TYPES[ext]))
    if language:
        kwargs["language"] = language[:8]
    resp = await get_provider().client.audio.transcriptions.create(**kwargs)
    text = (getattr(resp, "text", "") or "").strip()
    _charge(user_id, estimate_seconds(data, seconds) / 60 * s.stt_usd_per_minute, "stt")
    return text


def speech_text(text: str) -> str:
    """What is worth saying aloud: markdown syntax, code and bare URLs read
    badly, so they are dropped or simplified."""
    import re
    t = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "(link on screen)", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"[*_~|>]+", "", t)
    return re.sub(r"\s+", " ", t).strip()[:MAX_SPEAK_CHARS]


async def speak(text: str, *, user_id: str | None = None) -> AsyncIterator[bytes]:
    """MP3 bytes for ``text`` as they are generated."""
    from harness.providers import get_provider

    said = speech_text(text)
    if not said:
        raise VoiceError("Nothing to say.")
    s = get_settings()
    _charge(user_id, len(said) / 1000 * s.tts_usd_per_1k_chars, "tts")
    async with get_provider().client.audio.speech.with_streaming_response.create(
            model=s.tts_model, voice=s.tts_voice, input=said, response_format="mp3",
            instructions="Speak naturally and warmly, like a helpful assistant, at a relaxed pace.") as resp:
        async for chunk in resp.iter_bytes(4096):
            yield chunk
