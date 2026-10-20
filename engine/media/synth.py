"""Sounds made in code, so they are ours outright: no license to track, the same every episode.

Fann's three falling felt-piano notes, Tina's dupatta rustle and her four rising music-box notes
(brand/sound.toml), and the ambience beds (rain, room tone, wind, sea). Everything is 48 kHz mono
float32; the mixer sets the levels.
"""

from __future__ import annotations

import re

import numpy as np

from engine.media.ffmpeg import RATE

LICENSE = "generated in code by content-engine (engine/media/synth.py); owned outright"


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE), dtype=np.float32) / RATE


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)  # seeded: the same sound in every episode


def _shape(noise: np.ndarray, gain_of_freq) -> np.ndarray:
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(noise.size, 1 / RATE)
    out = np.fft.irfft(spec * gain_of_freq(np.maximum(freqs, 1.0)), n=noise.size)
    return out.astype(np.float32)


def _band(noise: np.ndarray, low: float, high: float) -> np.ndarray:
    return _shape(noise, lambda f: ((f >= low) & (f <= high)).astype(np.float32))


def _norm(x: np.ndarray, peak: float = 0.5) -> np.ndarray:
    m = float(np.max(np.abs(x))) if x.size else 0.0
    return (x / m * peak).astype(np.float32) if m > 0 else x


def reverb(x: np.ndarray, seconds: float = 2.4, wet: float = 0.3, seed: int = 7) -> np.ndarray:
    """A soft room: convolution with exponentially decaying noise."""
    t = _t(seconds)
    ir = _rng(seed).standard_normal(t.size).astype(np.float32) * np.exp(-t * 5.5 / seconds)
    ir = _shape(ir, lambda f: 1 / (1 + (f / 4000) ** 2))  # darker tail
    ir /= np.sqrt(np.sum(ir**2))
    n = x.size + ir.size
    tail = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)[:n].astype(np.float32)
    dry = np.concatenate([x, np.zeros(ir.size, np.float32)])
    return dry * (1 - wet) + _norm(tail, float(np.max(np.abs(x)))) * wet


def _felt_piano_note(freq: float, seconds: float) -> np.ndarray:
    t = _t(seconds)
    x = sum(
        (1 / n**1.6)
        * np.sin(2 * np.pi * freq * n * (1 + 0.0004 * n**2) * t)
        * np.exp(-t * (0.9 + 0.7 * n))
        for n in range(1, 7)
    )
    x = x * np.minimum(1, t / 0.012)  # felt: a soft attack
    return _shape(_norm(x), lambda f: 1 / (1 + (f / 1800) ** 4))  # felt: no brightness


def _music_box_note(freq: float, seconds: float) -> np.ndarray:
    t = _t(seconds)
    x = (
        np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.9)
        + 0.35 * np.sin(2 * np.pi * freq * 3.01 * t) * np.exp(-t / 0.35)
        + 0.18 * np.sin(2 * np.pi * freq * 5.93 * t) * np.exp(-t / 0.15)
    )
    return _norm(x * np.minimum(1, t / 0.001))


def _sequence(notes: list[np.ndarray], step_s: float) -> np.ndarray:
    total = int(step_s * RATE) * (len(notes) - 1) + max(n.size for n in notes)
    out = np.zeros(total, np.float32)
    for i, note in enumerate(notes):
        start = int(i * step_s * RATE)
        out[start : start + note.size] += note
    return out


def fann_motif() -> np.ndarray:
    """Low felt piano: the same three falling notes, slow (E4, C#4, A3)."""
    notes = [_felt_piano_note(f, 2.6) for f in (329.63, 277.18, 220.0)]
    return _norm(reverb(_sequence(notes, 0.75), seconds=2.2, wet=0.3))


def tina_motif() -> np.ndarray:
    """A small music box: four rising notes, the answer to Fann's three (A5, C#6, E6, F#6)."""
    notes = [_music_box_note(f, 1.6) for f in (880.0, 1108.73, 1318.51, 1479.98)]
    return _norm(reverb(_sequence(notes, 0.34), seconds=1.8, wet=0.3))


def dupatta_rustle() -> np.ndarray:
    """Soft fabric settling, close to the microphone."""
    t = _t(0.9)
    noise = _band(_rng(3).standard_normal(t.size).astype(np.float32), 900, 7000)
    env = np.sin(np.pi * np.clip(t / 0.9, 0, 1)) ** 2 * (1 + 0.4 * np.sin(2 * np.pi * 9 * t))
    return _norm(noise * env, 0.35)


PRESENCE = {
    "fann_hum": fann_motif,
    "tina_dupatta": lambda: _sequence([dupatta_rustle(), tina_motif()], 0.5),
}


# ---------------------------------------------------------------- ambience


def _pink(seconds: float, seed: int) -> np.ndarray:
    return _shape(
        _rng(seed).standard_normal(int(seconds * RATE)).astype(np.float32), lambda f: 1 / np.sqrt(f)
    )


def rain(seconds: float) -> np.ndarray:
    bed = _shape(_pink(seconds, 11), lambda f: ((f > 300) & (f < 7000)).astype(np.float32))
    drops = np.zeros_like(bed)
    rng = _rng(12)
    for at in rng.uniform(0, seconds, int(seconds * 25)):
        i = int(at * RATE)
        n = min(240, drops.size - i)
        drops[i : i + n] += rng.uniform(0.2, 1) * np.exp(-np.arange(n) / 40) * rng.choice([-1, 1])
    return _norm(_norm(bed) + 0.25 * _band(drops, 1500, 9000))


def room_tone(seconds: float) -> np.ndarray:
    brown = _shape(
        _rng(21).standard_normal(int(seconds * RATE)).astype(np.float32), lambda f: 1 / f
    )
    return _norm(_shape(brown, lambda f: 1 / (1 + (f / 250) ** 2)), 0.3)


def wind(seconds: float) -> np.ndarray:
    t = _t(seconds)
    gust = 0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t) * np.sin(2 * np.pi * 0.023 * t + 1)
    return _norm(_shape(_pink(seconds, 31), lambda f: 1 / (1 + (f / 700) ** 2)) * gust)


def sea(seconds: float) -> np.ndarray:
    t = _t(seconds)
    swell = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 7.5)) ** 2
    return _norm(_shape(_pink(seconds, 41), lambda f: 1 / (1 + (f / 1200) ** 2)) * swell)


BEDS = {"rain": rain, "sea": sea, "wind": wind, "room": room_tone}
_BED_WORDS = (
    ("rain", r"rain|storm|drizzle|wet"),
    ("sea", r"sea|wave|ocean|shore|tide|gull"),
    ("wind", r"wind|breeze|leaves|grass"),
)


def bed_kind(texts: list[str]) -> str:
    """Which bed a shot sits on, from its sfx and overlays: rain, sea, wind, or room tone."""
    text = " ".join(texts).lower()
    return next((kind for kind, pattern in _BED_WORDS if re.search(pattern, text)), "room")


def bed(kind: str, seconds: float) -> np.ndarray:
    """A bed; anything but room tone also carries a faint room tone, so it never sounds empty."""
    out = room_tone(seconds)
    if kind != "room":
        out = out + 0.8 * BEDS[kind](seconds)
    return _norm(out)
