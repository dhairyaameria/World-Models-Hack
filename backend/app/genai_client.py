"""Thin wrappers around google-genai. Model IDs come from env so they can be updated without
code changes (run scripts/list_models.py to see what your key can access)."""

from __future__ import annotations

import io
import os
import wave
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ER2_MODEL = os.getenv("ER2_MODEL", "gemini-robotics-er-2-preview")
ER2_STREAMING_MODEL = os.getenv("ER2_STREAMING_MODEL", "gemini-robotics-er-2-streaming-preview")
FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-flash-latest")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")


@lru_cache(maxsize=1)
def client():
    from google import genai

    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is not set. Put it in backend/.env (see .env.example).")
    return genai.Client()


def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def tts(text: str, style: str, voice: str = "Kore") -> bytes:
    """Speak `text` in `style` (e.g. 'a weak, exhausted whisper'). Returns WAV bytes."""
    from google.genai import types

    resp = client().models.generate_content(
        model=TTS_MODEL,
        contents=f"Say this as {style}: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    part = resp.candidates[0].content.parts[0]
    mime = part.inline_data.mime_type or ""
    rate = int(mime.split("rate=")[1].split(";")[0]) if "rate=" in mime else 24000
    return pcm_to_wav(part.inline_data.data, rate)


def generate_image(prompt: str) -> bytes:
    """Returns image bytes (PNG/JPEG as produced by the model)."""
    from google.genai import types

    resp = client().models.generate_content(
        model=IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="16:9"),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    raise RuntimeError("image model returned no image")
