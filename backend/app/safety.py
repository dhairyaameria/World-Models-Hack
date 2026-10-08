"""Deterministic safety layer. Runs AFTER every model decision (cloud, onboard, baseline) and can
override it. No model can bypass these rules."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .models import Action, Hazard

# Region of the frame the robot is about to drive into ([y, x] normalized 0-1000).
AHEAD_Y_MIN = 600
AHEAD_X_MIN, AHEAD_X_MAX = 300, 700
OSCILLATION_WINDOW = 6


def hazard_ahead(hazards: list[Hazard], min_severity: int = 3) -> Optional[Hazard]:
    for h in hazards:
        y, x = h.point
        if h.severity >= min_severity and y >= AHEAD_Y_MIN and AHEAD_X_MIN <= x <= AHEAD_X_MAX:
            return h
    return None


@dataclass
class SafetyLayer:
    recent_turns: deque = field(default_factory=lambda: deque(maxlen=OSCILLATION_WINDOW))
    _force_forward_next: bool = False

    def check(self, action: Action, hazards: list[Hazard]) -> tuple[Action, Optional[str]]:
        """Return (possibly replaced action, override reason or None)."""
        # Rule 1: never drive forward into a deadly hazard directly ahead.
        h = hazard_ahead(hazards)
        if h is not None and action.move == "W":
            self.recent_turns.clear()
            side = "right" if h.point[1] < 500 else "left"
            return (Action(move="S", look=side, duration_ms=600),
                    f"{h.label} directly ahead, backing off")

        # Rule 2: break left/right oscillation (the model flip-flopping between turns).
        if action.look in ("left", "right") and action.move == "none":
            self.recent_turns.append(action.look)
            turns = list(self.recent_turns)
            if len(turns) == OSCILLATION_WINDOW and all(a != b for a, b in zip(turns, turns[1:])):
                self.recent_turns.clear()
                if hazard_ahead(hazards, min_severity=2) is None:
                    return Action(move="W", duration_ms=800), "stuck turning back and forth, committing forward"
                return Action(look="right", duration_ms=1500), "stuck turning back and forth, turning 90°"
        else:
            self.recent_turns.clear()
        return action, None


def timeout_action() -> tuple[Action, str]:
    return Action(move="none", duration_ms=300), "re-assessing"
