"""AGENT_MODE=live: Gemini Robotics ER 2 + mission memory + safety layer."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time

from .er2 import DecisionOut, decide_sync
from .models import Action, Decision, Hazard, Heard, PointLabel
from .safety import hazard_ahead, timeout_action
from .state import Episode

log = logging.getLogger("rescuesim.autopilot")

MODEL_TIMEOUT_S = float(os.getenv("MODEL_TIMEOUT_S", "10"))
# ER 2 takes ~2-3 s per decision; stretch safe forward moves to cover that gap so motion doesn't stall.
MAX_FORWARD_MS = int(os.getenv("MAX_FORWARD_MS", "1500"))
EVENT_ALERT_S = 20  # how long a world event stays in the agent's context


def build_context(ep: Episode) -> str:
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
    try:
        out, _ = await asyncio.wait_for(
            asyncio.to_thread(decide_sync, jpeg, build_context(ep)), timeout=MODEL_TIMEOUT_S)
    except Exception as e:
        log.warning("ER 2 call failed for %s: %s %s", ep.id, type(e).__name__, str(e)[:200])
        action, reason = timeout_action()
        ep.apply(action)
        return Decision(episode_id=ep.id, ts=time.time(), action=action, pose=ep.pose, reason=reason,
                        source="cloud", latency_ms=(time.perf_counter() - t0) * 1000)
    latency_ms = (time.perf_counter() - t0) * 1000

    action, survivors, hazards, heard = to_contract(out)
    action, override = ep.safety.check(action, hazards)
    alert = any(time.time() - t < EVENT_ALERT_S for t, _ in ep.events)
    if (override is None and not alert and action.move == "W" and action.look == "none"
            and hazard_ahead(hazards, min_severity=2) is None):
        action.duration_ms = min(MAX_FORWARD_MS, max(action.duration_ms, int(latency_ms * 0.9)))

    for s in survivors:
        if s.label not in ep.survivors_found:
            ep.survivors_found.append(s.label)
    ep.recent.append(f"{action.move}/{action.look} {action.duration_ms}ms: {out.reason}"
                     + (f" [SAFETY OVERRIDE: {override}]" if override else ""))
    ep.apply(action)

    return Decision(
        episode_id=ep.id, ts=time.time(), action=action, survivors=survivors, hazards=hazards,
        heard=heard, priority=out.priority, exit_seen=out.exit_seen, pose=ep.pose,
        reason=out.reason, safety_override=override, source="cloud", latency_ms=latency_ms,
    )
