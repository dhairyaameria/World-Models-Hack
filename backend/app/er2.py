"""Gemini Robotics ER 2 calls: the robot's perception + decision step.

The model never sees ground truth (source ids, kinds, transcripts). It gets a frame, optionally
an audio clip + mic-array bearing estimates, and the mission context.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .genai_client import ER2_MODEL, ER2_STREAMING_MODEL, client

SYSTEM_PROMPT = """You are the onboard brain of an autonomous search-and-rescue robot inside a disaster zone.
You see through a forward-facing camera and may also hear through a microphone array.
Goals, in priority order:
 1. Never move into hazards (fire, smoke, deep or dark water, live wires, collapsing structure, gas).
 2. Find and reach survivors, including ones you can only HEAR (voices, crying, tapping).
 3. Find the exit.
Rules for sound: voices may be survivors even when nothing is visible; muffled = behind a wall or
under debris; a voice that goes silent raises urgency; spoken warnings ("don't come this way") are
hazard information for that direction; hissing, creaking or rushing water are hazards you may not
see; TV/radio-like or repeating broadcast voices may be decoys. When survivors compete, prioritize by
urgency, then whether they can be reached safely, then distance.
Image points are [y, x] normalized to 0-1000. Bearings: 0 = straight ahead, +90 = right, -90 = left.
Controls: move W=forward, S=back, A=strafe left, D=strafe right; look left/right turns the camera.
Pick ONE action per step with duration_ms 300-1500. Keep "reason" to one short sentence."""


class PointOut(BaseModel):
    point: list[int] = Field(description="[y, x] normalized 0-1000")
    label: str


class HazardOut(PointOut):
    severity: Literal[1, 2, 3]


class HeardOut(BaseModel):
    bearing_deg: float
    distance_m: float
    label: str
    is_hazard: bool
    is_decoy_suspected: bool
    urgency: Literal[1, 2, 3]


class ActionOut(BaseModel):
    move: Literal["W", "A", "S", "D", "none"]
    look: Literal["left", "right", "up", "down", "none"]
    duration_ms: int


class DecisionPointOption(BaseModel):
    label: str
    description: str


class DecisionOut(BaseModel):
    survivors: list[PointOut]
    hazards: list[HazardOut]
    heard: list[HeardOut]
    exit_seen: bool
    priority: str
    action: ActionOut
    reason: str
    decision_point: Optional[list[DecisionPointOption]] = Field(
        default=None, description="Only when the path forks: 2-3 options worth imagining first")


def build_user_text(context: str = "", mic_array: Optional[str] = None) -> str:
    parts = ["Decide the next action from the current camera frame."]
    if mic_array:
        parts.append(f"MIC ARRAY (estimates, ±15°): {mic_array}")
        parts.append("The attached audio is what the microphones hear right now.")
    else:
        parts.append("No audio this step; heard = [].")
    if context:
        parts.append(f"Mission context:\n{context}")
    return "\n".join(parts)


def decide_sync(jpeg: bytes, context: str = "", audio_wav: Optional[bytes] = None,
                mic_array: Optional[str] = None, model: str = ER2_MODEL) -> tuple[DecisionOut, float]:
    """Standard (non-streaming) endpoint with enforced JSON schema. Returns (decision, latency_ms)."""
    from google.genai import types

    contents: list = [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")]
    if audio_wav:
        contents.append(types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"))
    contents.append(build_user_text(context, mic_array if audio_wav else None))

    t0 = time.perf_counter()
    resp = client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=DecisionOut,
            temperature=0.2,
        ),
    )
    latency = (time.perf_counter() - t0) * 1000
    parsed = resp.parsed if isinstance(resp.parsed, DecisionOut) else DecisionOut.model_validate_json(resp.text)
    return parsed, latency


_JSON_RE = re.compile(r"\{.*\}", re.S)


async def decide_streaming(jpeg: bytes, context: str = "",
                           model: str = ER2_STREAMING_MODEL) -> tuple[Optional[DecisionOut], float, str]:
    """One step over the Live (streaming) endpoint. Schema is requested in the prompt, not enforced.
    Returns (decision or None if unparseable, latency_ms, raw_text)."""
    from google.genai import types

    schema = json.dumps(DecisionOut.model_json_schema())
    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=SYSTEM_PROMPT + "\nReply with ONLY a JSON object matching this schema:\n" + schema,
    )
    async with client().aio.live.connect(model=model, config=config) as session:
        t0 = time.perf_counter()
        await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))
        await session.send_realtime_input(text=build_user_text(context))
        text = ""
        async for msg in session.receive():
            if msg.text:
                text += msg.text
            if msg.server_content and msg.server_content.turn_complete:
                break
        latency = (time.perf_counter() - t0) * 1000
    m = _JSON_RE.search(text)
    try:
        return (DecisionOut.model_validate_json(m.group(0)) if m else None), latency, text
    except Exception:
        return None, latency, text


def run_streaming(jpeg: bytes, context: str = ""):
    return asyncio.run(decide_streaming(jpeg, context))
