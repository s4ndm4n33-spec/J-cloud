"""Voice routes — Whisper STT + OpenAI TTS via the Universal Key.

Both endpoints use `emergentintegrations` under the Emergent Universal LLM Key
so the user gets voice-in / voice-out with zero extra credentials.

- POST /api/voice/transcribe — multipart file upload, returns {text}.
- POST /api/voice/speak — {text, voice?}, returns audio/mpeg bytes.

The J persona uses `onyx` by default (deep, authoritative — the JARVIS voice).
"""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from emergentintegrations.llm.openai import OpenAISpeechToText, OpenAITextToSpeech

from deps import EMERGENT_LLM_KEY, get_current_user

log = logging.getLogger("gauntlet.voice")
router = APIRouter()

# Voice choices we expose. `onyx` = J's canonical voice.
J_VOICES = {"onyx", "sage", "echo", "ash", "fable", "alloy", "coral", "nova", "shimmer"}
MAX_TTS_CHARS = 4096
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Whisper's own cap


@router.post("/voice/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str = Form("en"),
    _user: dict = Depends(get_current_user),
):
    """Whisper STT — audio in, text out."""
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail=f"Audio exceeds {MAX_AUDIO_BYTES // (1024*1024)}MB cap")

    # Whisper cares about the filename extension. Browser MediaRecorder
    # produces `audio/webm;codecs=opus` — save it as .webm so Whisper handles it.
    fname = file.filename or "clip.webm"
    if "." not in fname:
        fname += ".webm"
    buf = io.BytesIO(audio)
    buf.name = fname

    stt = OpenAISpeechToText(api_key=EMERGENT_LLM_KEY)
    try:
        resp = await stt.transcribe(
            file=buf,
            model="whisper-1",
            response_format="json",
            language=language or None,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"whisper transcribe failed: {e}")
        raise HTTPException(status_code=502, detail=f"transcribe failed: {e}") from e
    text = getattr(resp, "text", None) or (resp.get("text") if isinstance(resp, dict) else "") or ""
    return {"text": text.strip()}


@router.post("/voice/speak")
async def voice_speak(
    payload: dict,
    _user: dict = Depends(get_current_user),
):
    """OpenAI TTS — text in, mp3 bytes out."""
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    if len(text) > MAX_TTS_CHARS:
        # Silently truncate rather than fail — voice is a "nice-to-have" surface.
        text = text[:MAX_TTS_CHARS]

    voice = payload.get("voice") or "onyx"
    if voice not in J_VOICES:
        voice = "onyx"
    speed = float(payload.get("speed") or 1.0)
    speed = max(0.5, min(speed, 2.0))

    tts = OpenAITextToSpeech(api_key=EMERGENT_LLM_KEY)
    try:
        audio_bytes = await tts.generate_speech(
            text=text,
            model="tts-1",
            voice=voice,
            response_format="mp3",
            speed=speed,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"tts failed: {e}")
        raise HTTPException(status_code=502, detail=f"tts failed: {e}") from e

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-Gauntlet-Voice": voice},
    )
