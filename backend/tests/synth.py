"""Deterministic synthetic audio for tests. All at 16 kHz mono float64 in [-1, 1]."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import parselmouth
from scipy.io import wavfile
from scipy.signal import lfilter

SR = 16000


def _t(dur_s: float) -> np.ndarray:
    return np.arange(int(round(dur_s * SR))) / SR


def tone(f0_hz: float, dur_s: float, amp: float = 0.3) -> np.ndarray:
    return amp * np.sin(2 * np.pi * f0_hz * _t(dur_s))


def tone_with_tail(f0_hz: float, dur_s: float, tail_s: float, tail_st: float, amp: float = 0.3) -> np.ndarray:
    """Sine at f0 whose final `tail_s` seconds shift by `tail_st` semitones, phase-continuous."""
    n = int(round(dur_s * SR))
    n_tail = int(round(tail_s * SR))
    freq = np.full(n, f0_hz, dtype=float)
    freq[n - n_tail :] = f0_hz * 2 ** (tail_st / 12)
    phase = np.cumsum(2 * np.pi * freq / SR)
    return amp * np.sin(phase)


def silence(dur_s: float) -> np.ndarray:
    return np.zeros(int(round(dur_s * SR)))


def concat(*parts: np.ndarray) -> np.ndarray:
    return np.concatenate(parts)


def vowel(f1_hz: float, f2_hz: float, f0_hz: float, dur_s: float, amp: float = 0.3) -> np.ndarray:
    """Source-filter vowel: impulse train through two resonators (80 Hz and 90 Hz bandwidth)."""
    n = int(round(dur_s * SR))
    period = int(round(SR / f0_hz))
    src = np.zeros(n)
    src[::period] = 1.0
    y = src
    for f, bw in ((f1_hz, 80.0), (f2_hz, 90.0)):
        r = np.exp(-np.pi * bw / SR)
        theta = 2 * np.pi * f / SR
        a = [1.0, -2 * r * np.cos(theta), r * r]
        y = lfilter([1.0], a, y)
    return amp * y / np.max(np.abs(y))


def am(x: np.ndarray, rate_hz: float) -> np.ndarray:
    """Amplitude-modulate with a raised cosine so troughs reach zero."""
    t = np.arange(len(x)) / SR
    env = 0.5 * (1 - np.cos(2 * np.pi * rate_hz * t))
    return x * env


def attenuate_tail(x: np.ndarray, tail_s: float, db: float) -> np.ndarray:
    y = x.copy()
    n_tail = int(round(tail_s * SR))
    y[len(y) - n_tail :] *= 10 ** (-db / 20)
    return y


def with_noise_floor(x: np.ndarray, level: float = 1e-4) -> np.ndarray:
    """Add seeded low-level noise so digital silence has a finite intensity."""
    rng = np.random.default_rng(0)
    return x + level * rng.standard_normal(len(x))


def to_sound(x: np.ndarray) -> parselmouth.Sound:
    return parselmouth.Sound(x.astype(np.float64), sampling_frequency=SR)


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    pcm = np.clip(x, -1, 1)
    wavfile.write(path, sr, (pcm * 32767).astype(np.int16))
    return path
