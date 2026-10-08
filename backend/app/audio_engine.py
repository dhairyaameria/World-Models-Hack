"""Audio scene engine + simulated microphone array (P16).

Reactor renders video only, so sound lives here: sources sit at map positions, and from the
robot's dead-reckoned pose we compute what it hears. Two views of the same scene:
  - ground truth (true bearing/distance/gain) -> frontend speakers + operator radar
  - mic-array estimates (noisy bearing/distance, front/back confusion) -> the robot's brain
The model never sees source ids, kinds or transcripts.
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from . import audio_synth
from .models import AudioSource, AudioSourceState, Pose

SR = 16000
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
AUDIBLE_GAIN = 0.04          # below this the mic array doesn't pick the source up
BEARING_SIGMA_DEG = 12.0
FRONT_BACK_CONFUSION = 0.05
REVEAL_FACING_DEG = 40.0


def wrap_deg(a: float) -> float:
    return (a + 180) % 360 - 180


def relative(pose: Pose, pos: tuple[float, float]) -> tuple[float, float]:
    """(bearing_deg relative to heading, distance_m). Heading 0 faces +y, positive = clockwise."""
    dx, dy = pos[0] - pose.x, pos[1] - pose.y
    absolute = math.degrees(math.atan2(dx, dy))
    return wrap_deg(absolute - pose.heading_deg), math.hypot(dx, dy)


def position_from(pose: Pose, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    a = math.radians(pose.heading_deg + bearing_deg)
    return (round(pose.x + math.sin(a) * distance_m, 2), round(pose.y + math.cos(a) * distance_m, 2))


@lru_cache(maxsize=64)
def load_clip(clip_url: str) -> np.ndarray:
    path = STATIC_DIR / clip_url.removeprefix("/static/")
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SR:
        n = int(len(mono) * SR / sr)
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono).astype(np.float32)
    return mono


@dataclass
class Estimate:
    """What the mic array reports for one audible source."""
    source: AudioSource
    bearing_deg: float
    distance_m: float
    true_bearing_deg: float
    true_distance_m: float
    gain: float


@dataclass
class AudioScene:
    sources: list[AudioSource]
    started_at: float = field(default_factory=time.time)
    seed: int = 0
    revealed: set[str] = field(default_factory=set)
    _was_audible: set[str] = field(default_factory=set)
    _pending_event: Optional[str] = None
    _injected_at: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)

    # ----- time & activity -----
    def elapsed(self, now: Optional[float] = None) -> float:
        return (now or time.time()) - self.started_at

    def _active(self, s: AudioSource, t: float) -> bool:
        return t >= s.start_s and (s.stop_s is None or t < s.stop_s)

    def gain(self, s: AudioSource, distance: float) -> float:
        g = 10 ** (s.gain_db / 20) / max(1.0, distance / 1.5)
        return float(g * (0.5 if s.muffled else 1.0))

    def inject(self, s: AudioSource) -> None:
        """Add a source that starts now (operator / compare view)."""
        s = s.model_copy(update={"start_s": self.elapsed() + s.start_s,
                                 "stop_s": None if s.stop_s is None else self.elapsed() + s.stop_s})
        self.sources = [x for x in self.sources if x.id != s.id] + [s]

    # ----- ground truth for speakers / radar -----
    def states(self, pose: Pose) -> list[AudioSourceState]:
        t = self.elapsed()
        out = []
        for s in self.sources:
            bearing, dist = relative(pose, s.position)
            playing = self._active(s, t)
            out.append(AudioSourceState(
                id=s.id, kind=s.kind, clip_url=s.clip_url, bearing_deg=round(bearing, 1),
                distance_m=round(dist, 2), gain=round(self.gain(s, dist) if playing else 0.0, 3),
                muffled=s.muffled, playing=playing))
        return out

    # ----- the robot's ears -----
    def hear(self, pose: Pose) -> list[Estimate]:
        """Mic-array estimates for every audible source; also updates audio-event detection."""
        t = self.elapsed()
        heard: list[Estimate] = []
        audible_now: set[str] = set()
        for s in self.sources:
            if not self._active(s, t):
                continue
            bearing, dist = relative(pose, s.position)
            g = self.gain(s, dist)
            if g < AUDIBLE_GAIN:
                continue
            audible_now.add(s.id)
            sigma = BEARING_SIGMA_DEG * (1.6 if s.muffled else 1.0) * (1.3 if dist > 10 else 1.0)
            est_b = bearing + float(self.rng.normal(0, sigma))
            if self.rng.random() < FRONT_BACK_CONFUSION:
                est_b = 180 - est_b  # classic mic-array front/back ambiguity
            est_d = dist * float(self.rng.uniform(0.7, 1.3))
            heard.append(Estimate(s, round(wrap_deg(est_b)), round(est_d, 1), bearing, dist, g))

        kinds = {x.id: x.kind for x in self.sources}
        started = audible_now - self._was_audible
        stopped = self._was_audible - audible_now
        if started:
            self._pending_event = "new sound: " + ", ".join(sorted(started))
        elif any(kinds.get(i) == "voice" for i in stopped):
            self._pending_event = "a voice went silent"
        self._was_audible = audible_now
        return heard

    def take_event(self) -> Optional[str]:
        ev, self._pending_event = self._pending_event, None
        return ev

    @staticmethod
    def describe(heard: list[Estimate]) -> str:
        """Text for the model: estimates only, no ids/kinds/ground truth."""
        parts = []
        for i, h in enumerate(sorted(heard, key=lambda e: -e.gain), 1):
            loud = "loud" if h.gain > 0.35 else "moderate" if h.gain > 0.12 else "faint"
            parts.append(f"src{i}: bearing {h.bearing_deg:+.0f}°, ~{h.distance_m:.0f} m, {loud}"
                         + (", muffled" if h.source.muffled else ""))
        return "; ".join(parts)

    def mix(self, heard: list[Estimate], seconds: float = 2.5) -> bytes:
        """Mono WAV of what the robot hears right now (sum of audible sources)."""
        n = int(seconds * SR)
        out = np.zeros(n, dtype=np.float32)
        t = self.elapsed()
        for h in heard:
            clip = load_clip(h.source.clip_url)
            if len(clip) == 0:
                continue
            start = int(max(0.0, t - h.source.start_s - seconds) * SR)
            if h.source.loop:
                idx = (np.arange(n) + start) % len(clip)
                seg = clip[idx]
            else:
                seg = np.zeros(n, dtype=np.float32)
                piece = clip[start:start + n]
                seg[:len(piece)] = piece
            if h.source.muffled:
                seg = audio_synth.muffle(seg)
            out += seg * min(1.0, h.gain * 1.5)
        peak = float(np.max(np.abs(out))) or 1.0
        if peak > 0.95:
            out *= 0.95 / peak
        out += self.rng.normal(0, 0.003, n).astype(np.float32)  # room noise floor
        buf = io.BytesIO()
        sf.write(buf, out, SR, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    # ----- reveals -----
    def due_reveals(self, pose: Pose) -> list[AudioSource]:
        t = self.elapsed()
        due = []
        for s in self.sources:
            if s.reveal is None or s.id in self.revealed or s.start_s > t:
                continue
            bearing, dist = relative(pose, s.position)
            if dist <= s.reveal.radius_m and abs(bearing) <= REVEAL_FACING_DEG:
                self.revealed.add(s.id)
                due.append(s)
        return due
