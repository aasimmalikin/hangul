"""POST /voice/transcribe (audio -> text) and POST /voice/speak (text ->
streamed MP3). Both need a signed-in user and, when billing is on, something
left to spend -- voice is metered like questions are."""

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.logging import log
from harness.media import voice

router = APIRouter()


async def _can_spend(user_id: str) -> None:
    from harness.billing import entitlements
    if not entitlements.billing_enabled():
        return
    st = await asyncio.to_thread(entitlements.standing, user_id)
    if not st.can_spend:
        code = "free_pool_exhausted" if st.pool_exhausted and st.allowance_left > 0 else "insufficient_balance"
        raise HTTPException(status_code=402, headers={"X-Reason": code}, detail={
            "detail": "You've used this period's allowance. Upgrade or buy credits to keep using voice.",
            "code": code, "plan_needed": "plus" if st.plan.id == "free" else None})


@router.post("/voice/transcribe")
async def transcribe(file: UploadFile = File(...), seconds: float | None = Form(default=None),
                     language: str | None = Form(default=None, max_length=8),
                     user: dict = Depends(get_current_user)) -> dict:
    await _can_spend(user["user_id"])
    data = b""
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > voice.MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="That recording is too long (max about 10 minutes).")
    try:
        text = await voice.transcribe(data, file.filename or "speech.webm", user_id=user["user_id"],
                                      seconds=seconds, language=language)
    except voice.VoiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - provider outage -> a clean 502
        log.warning("transcription failed", error=str(e)[:200])
        raise HTTPException(status_code=502, detail="Couldn't understand the audio right now. Try again.")
    return {"text": text}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


@router.post("/voice/speak")
async def speak(req: SpeakIn, user: dict = Depends(get_current_user)):
    await _can_spend(user["user_id"])
    stream = voice.speak(req.text, user_id=user["user_id"])
    try:
        first = await anext(stream)          # fail before the 200 if the provider refuses
    except voice.VoiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StopAsyncIteration:
        raise HTTPException(status_code=502, detail="No audio came back.")
    except Exception as e:  # noqa: BLE001
        log.warning("speech failed", error=str(e)[:200])
        raise HTTPException(status_code=502, detail="Couldn't speak that right now.")

    async def body():
        yield first
        async for chunk in stream:
            yield chunk

    return StreamingResponse(body(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
