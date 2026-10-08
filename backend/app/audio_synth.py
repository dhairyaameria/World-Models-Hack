"""Procedural sound effects (no licensing questions). Swap for recorded CC0 clips later if wanted.

All functions return float32 mono in [-1, 1] at SR Hz.
"""

from __future__ import annotations

import numpy as np

SR = 16000
_rng = np.random.default_rng(7)


def _norm(x: np.ndarray, peak: float = 0.8) -> np.ndarray:
    m = np.max(np.abs(x)) or 1.0
    return (x / m * peak).astype(np.float32)


def _lowpass(x: np.ndarray, alpha: float) -> np.ndarray:
    """One-pole low-pass. alpha in (0,1]: smaller = darker."""
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += alpha * (v - acc)
        y[i] = acc
    return y


def _fade(x: np.ndarray, ms: float = 30) -> np.ndarray:
    n = int(SR * ms / 1000)
    if n and len(x) > 2 * n:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def gas_hiss(seconds: float = 4.0) -> np.ndarray:
    white = _rng.standard_normal(int(SR * seconds))
    hiss = white - _lowpass(white, 0.3)  # keep the high band
    wobble = 1 + 0.15 * np.sin(np.linspace(0, 2 * np.pi * 1.3 * seconds, len(hiss)))
    return _fade(_norm(hiss * wobble, 0.5))


def rushing_water(seconds: float = 4.0) -> np.ndarray:
    brown = np.cumsum(_rng.standard_normal(int(SR * seconds)))
    brown -= _lowpass(brown, 0.001)  # remove drift
    gurgle = 1 + 0.4 * np.abs(np.sin(np.linspace(0, 2 * np.pi * 3 * seconds, len(brown))))
    return _fade(_norm(_lowpass(brown, 0.2) * gurgle, 0.7))


def structural_creak(seconds: float = 4.0) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    out = np.zeros_like(t)
    for start in (0.2, 1.6, 2.7):
        dur = 0.9
        m = (t >= start) & (t < start + dur)
        tt = t[m] - start
        f = 70 + 40 * np.sin(2 * np.pi * 0.7 * tt) + 25 * tt  # slowly bending pitch
        phase = 2 * np.pi * np.cumsum(f) / SR
        saw = 2 * (phase / (2 * np.pi) % 1) - 1
        stick = (np.sin(2 * np.pi * 9 * tt) > 0.2).astype(float)  # stick-slip stutter
        env = np.sin(np.pi * tt / dur)
        out[m] += saw * (0.5 + 0.5 * stick) * env
    out += 0.05 * _rng.standard_normal(len(t))
    return _fade(_norm(_lowpass(out, 0.35), 0.8))


def sos_knock(seconds: float = 6.0) -> np.ndarray:
    """... --- ... knocked on metal, repeated."""
    out = np.zeros(int(SR * seconds), dtype=np.float32)
    pattern = [0.18] * 3 + [0.45] * 3 + [0.18] * 3  # gaps between knocks
    t = 0.3
    while t < seconds - 2.5:
        for gap in pattern:
            i = int(t * SR)
            n = int(0.06 * SR)
            if i + n >= len(out):
                break
            tt = np.arange(n) / SR
            knock = np.sin(2 * np.pi * 420 * tt) * np.exp(-tt * 60) + 0.6 * np.sin(2 * np.pi * 1130 * tt) * np.exp(-tt * 90)
            out[i:i + n] += knock
            t += gap
        t += 1.2
    return _norm(out, 0.8)


def fire_crackle(seconds: float = 4.0) -> np.ndarray:
    n = int(SR * seconds)
    roar = _lowpass(np.cumsum(_rng.standard_normal(n)) * 0.02, 0.05)
    roar -= _lowpass(roar, 0.002)
    pops = np.zeros(n)
    for i in _rng.integers(0, n - 200, size=int(25 * seconds)):
        pops[i:i + 120] += _rng.standard_normal(120) * np.exp(-np.arange(120) / 15) * _rng.uniform(0.3, 1)
    return _fade(_norm(_norm(roar, 0.5) + pops, 0.8))


def fire_alarm(seconds: float = 4.0) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    tone = np.where((t * 2) % 1 < 0.5, np.sin(2 * np.pi * 960 * t), np.sin(2 * np.pi * 770 * t))
    return _fade(_norm(np.sign(tone) * 0.3 + tone * 0.7, 0.6))


EFFECTS = {
    "gas_hiss": gas_hiss,
    "rushing_water": rushing_water,
    "creak": structural_creak,
    "sos_knock": sos_knock,
    "fire_crackle": fire_crackle,
    "fire_alarm": fire_alarm,
}


def muffle(x: np.ndarray) -> np.ndarray:
    """Behind a wall / under rubble: strong low-pass + quieter."""
    return (_lowpass(_lowpass(x, 0.08), 0.08) * 0.6).astype(np.float32)
