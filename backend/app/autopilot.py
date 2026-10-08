"""AGENT_MODE=live: Gemini Robotics ER 2 + mission memory + safety layer."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time

from .er2 import DecisionOut, decide_sync
from .models import Action, Decision, Hazard, Heard, PointLabel
from .safety import AudioHazard, hazard_ahead, timeout_action
from .state import Episode

log = logging.getLogger("rescuesim.autopilot")

# Typical: ~2 s without audio, 5-7 s with audio. A hung call freezes the robot until timeout.
MODEL_TIMEOUT_S = float(os.getenv("MODEL_TIMEOUT_S", "6"))
AUDIO_TIMEOUT_S = float(os.getenv("AUDIO_TIMEOUT_S", "9"))
# ER 2 takes ~2-3 s per decision; stretch safe forward moves to cover that gap so motion doesn't stall.
MAX_FORWARD_MS = int(os.getenv("MAX_FORWARD_MS", "1500"))
EVENT_ALERT_S = 20  # how long a world event stays in the agent's context
# Audio adds ~3-4 s per call, so only attach it on audio events or every Nth decision while audible.
AUDIO_EVERY_N = int(os.getenv("AUDIO_EVERY_N", "4"))
HAZARD_SOUNDS = {"gas_hiss": "gas hiss", "creak": "structural creaking", "fire": "fire crackling",
                 "water": "rushing water"}


def audio_hazards(heard) -> list[AudioHazard]:
    """Deterministic 'onboard sound classifier' for the safety layer. In this sim the class comes
    from the source kind; on a real robot it would be a small audio classifier (e.g. YAMNet)."""
    out = []
    for h in heard:
        s = h.source
        if s.kind in HAZARD_SOUNDS:
            out.append(AudioHazard(HAZARD_SOUNDS[s.kind], h.bearing_deg, h.distance_m))
        elif s.kind == "voice" and s.is_hazard:  # spoken warning, e.g. "don't come this way"
            out.append(AudioHazard("spoken warning", h.bearing_deg, h.distance_m, is_warning=True))
    return out


def _angle(a: float, b: float) -> float:
    return abs(((a - b) + 180) % 360 - 180)


def remember_heard(ep: Episode, heard_est, model_heard) -> None:
    """Associate each sound the model identified with the nearest-bearing source the engine tracks."""
    for mh in model_heard:
        if not heard_est:
            break
        best = min(heard_est, key=lambda e: _angle(e.bearing_deg, mh.bearing_deg))
        if _angle(best.bearing_deg, mh.bearing_deg) <= 45:
            ep.heard_labels[best.source.id] = (mh.label, mh.is_hazard, mh.is_decoy_suspected, mh.urgency)


def tracked_heard(ep: Episode, heard_est) -> list[Heard]:
    out = []
    for e in heard_est:
        if e.source.id in ep.heard_labels:
            label, hz, decoy, urg = ep.heard_labels[e.source.id]
            out.append(Heard(source_id=e.source.id, bearing_deg=e.bearing_deg, distance_m=e.distance_m,
                             label=label, is_hazard=hz, is_decoy_suspected=decoy, urgency=urg))
    return out


PURSUIT_CONE_DEG = 25
TURN_DPS = float(os.getenv("TURN_DPS", "60"))


def pursuit_target(tracked: list[Heard]) -> Heard | None:
    """The survivor sound to go to: highest urgency, then nearest. Hazards and decoys are skipped."""
    candidates = [h for h in tracked if not h.is_hazard and not h.is_decoy_suspected]
    return max(candidates, key=lambda h: (h.urgency, -h.distance_m), default=None)


def steer_toward(action: Action, target: Heard | None) -> tuple[Action, str | None]:
    """Low-level controller: the model chose WHAT to pursue; this keeps the heading on it.
    Only replaces a forward move that would leave the target off to the side."""
    if target is None or action.move != "W" or abs(target.bearing_deg) <= PURSUIT_CONE_DEG:
        return action, None
    turn_ms = int(min(1500, max(300, abs(target.bearing_deg) / TURN_DPS * 1000)))
    side = "left" if target.bearing_deg < 0 else "right"
    return (Action(look=side, duration_ms=turn_ms),
            f"turning {side} toward {target.label} ({target.bearing_deg:+.0f}°, ~{target.distance_m:.0f} m)")


def build_context(ep: Episode, tracked: list[Heard] | None = None) -> str:
    lines = [
        f"Scenario: {ep.scenario.title}. {ep.scenario.description}",
        f"Steps taken: {ep.steps}. Estimated pose: x={ep.pose.x:.1f} m, y={ep.pose.y:.1f} m, "
        f"heading {ep.pose.heading_deg:.0f}°.",
        f"Survivors found so far: {', '.join(ep.survivors_found) or 'none'}.",
    ]
    now = time.time()
    fresh = [clause for t, clause in ep.events if now - t < EVENT_ALERT_S]
    if fresh:
        lines.append("ALERT, this just happened in the world: " + " ".join(fresh)
                     + " Re-check the path: slow down, use short moves, and scan before advancing.")
    if tracked:
        lines.append("Sounds you identified earlier, at their current mic-array estimates "
                     "(no new audio this step): " + "; ".join(
                         f"{h.label} at bearing {h.bearing_deg:+.0f}°, ~{h.distance_m:.0f} m"
                         + (" (hazard)" if h.is_hazard else "") + (" (likely decoy)" if h.is_decoy_suspected else "")
                         for h in tracked))
    if ep.recent:
        lines.append("Your last decisions (oldest first) — avoid repeating moves that made no progress:")
        lines += [f"  - {r}" for r in ep.recent]
    if ep.playbook:
        lines.append("Lessons from earlier missions:")
        lines += [f"  - {lesson}" for lesson in ep.playbook]
    return "\n".join(lines)


def to_contract(out: DecisionOut) -> tuple[Action, list[PointLabel], list[Hazard], list[Heard]]:
    def pt(p: list[int]) -> tuple[int, int]:
        y, x = (list(p) + [500, 500])[:2]
        return (min(1000, max(0, int(y))), min(1000, max(0, int(x))))

    action = Action(move=out.action.move, look=out.action.look,
                    duration_ms=min(1500, max(300, out.action.duration_ms)))
    survivors = [PointLabel(point=pt(s.point), label=s.label) for s in out.survivors]
    hazards = [Hazard(point=pt(h.point), label=h.label, severity=h.severity) for h in out.hazards]
    heard = [Heard(bearing_deg=h.bearing_deg, distance_m=h.distance_m, label=h.label,
                   is_hazard=h.is_hazard, is_decoy_suspected=h.is_decoy_suspected, urgency=h.urgency)
             for h in out.heard]
    return action, survivors, hazards, heard


async def live_decision(ep: Episode, jpeg_b64: str) -> Decision:
    jpeg = base64.b64decode(jpeg_b64)
    t0 = time.perf_counter()

    heard = ep.audio.hear(ep.pose) if ep.audio else []
    audio_wav = mic_text = None
    if ep.hearing and heard:
        event = ep.audio.take_event()
        ep.decisions_since_audio += 1
        if event or ep.decisions_since_audio >= AUDIO_EVERY_N:
            ep.decisions_since_audio = 0
            audio_wav = ep.audio.mix(heard)
            mic_text = ep.audio.describe(heard)
            ep.record("audio_sent", event=event, mic=mic_text)
    elif ep.audio:
        ep.audio.take_event()

    try:
        out, _ = await asyncio.wait_for(
            asyncio.to_thread(decide_sync, jpeg,
                              build_context(ep, None if audio_wav else (tracked_heard(ep, heard) if ep.hearing else None)),
                              audio_wav, mic_text),
            timeout=AUDIO_TIMEOUT_S if audio_wav else MODEL_TIMEOUT_S)
    except Exception as e:
        log.warning("ER 2 call failed for %s: %s %s", ep.id, type(e).__name__, str(e)[:200])
        action, reason = timeout_action()
        ep.apply(action)
        return Decision(episode_id=ep.id, ts=time.time(), action=action, pose=ep.pose, reason=reason,
                        source="cloud", latency_ms=(time.perf_counter() - t0) * 1000)
    latency_ms = (time.perf_counter() - t0) * 1000

    action, survivors, hazards, model_heard = to_contract(out)
    if audio_wav:
        remember_heard(ep, heard, model_heard)
    heard_out = tracked_heard(ep, heard) if ep.hearing else []
    target = pursuit_target(heard_out) if ep.hearing else None
    action, steering = steer_toward(action, target)
    reason = out.reason + (f" Steering: {steering}." if steering else "")
    priority = (f"reach {target.label} ({target.bearing_deg:+.0f}°, ~{target.distance_m:.0f} m)"
                if target else out.priority)
    action, override = ep.safety.check(action, hazards,
                                       audio=audio_hazards(heard) if ep.hearing else None,
                                       heading_deg=ep.pose.heading_deg)
    alert = any(time.time() - t < EVENT_ALERT_S for t, _ in ep.events)
    if (override is None and not alert and action.move == "W" and action.look == "none"
            and hazard_ahead(hazards, min_severity=2) is None):
        action.duration_ms = min(MAX_FORWARD_MS, max(action.duration_ms, int(latency_ms * 0.9)))

    for s in survivors:
        if s.label not in ep.survivors_found:
            ep.survivors_found.append(s.label)
    ep.recent.append(f"{action.move}/{action.look} {action.duration_ms}ms: {reason}"
                     + (f" [SAFETY OVERRIDE: {override}]" if override else ""))
    ep.apply(action)

    return Decision(
        episode_id=ep.id, ts=time.time(), action=action, survivors=survivors, hazards=hazards,
        heard=heard_out, priority=priority, exit_seen=out.exit_seen, pose=ep.pose,
        reason=reason, safety_override=override, source="cloud", latency_ms=latency_ms,
    )
