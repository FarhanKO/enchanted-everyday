"""Thin wrappers around the ffmpeg and ffprobe binaries, and 48 kHz mono audio as numpy arrays."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

RATE = 48_000  # every audio buffer in the pipeline: 48 kHz mono float32 in [-1, 1]


class FFmpegError(RuntimeError):
    pass


def _bin(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FFmpegError(f"{name} is not on PATH")
    return path


def run(args: list[str], timeout: float = 1800) -> str:
    """Run ffmpeg with `args`; return stderr (where ffmpeg reports). Raises with its tail."""
    proc = subprocess.run(  # noqa: S603 - arguments are built by this package, never by an LLM
        [_bin("ffmpeg"), "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-1500:]}")
    return proc.stderr


def probe(path: Path) -> dict:
    proc = subprocess.run(  # noqa: S603 - fixed arguments
        [_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format",
         "-show_streams", str(path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path.name}: {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def filter_path(path: Path) -> str:
    """A path as a filtergraph option value: forward slashes, ':' and quotes escaped (Windows)."""
    p = path.resolve().as_posix()
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def decode(src: Path, extra_filters: str = "") -> np.ndarray:
    """Any audio file -> 48 kHz mono float32, through ffmpeg (optionally with an audio filter)."""
    dest = src.with_suffix(".decoded.wav")
    args = ["-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(RATE)]
    if extra_filters:
        args += ["-af", extra_filters]
    run([*args, "-c:a", "pcm_s16le", str(dest)])
    try:
        return read_wav(dest)
    finally:
        dest.unlink(missing_ok=True)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise FFmpegError(f"{path.name}: expected 16-bit mono")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: Path, audio: np.ndarray, rate: int = RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def trim_silence(
    audio: np.ndarray, threshold_db: float = -45.0, keep_s: float = 0.04
) -> np.ndarray:
    """Cut the leading and trailing silence TTS adds, so scripted pauses are the only pauses."""
    if audio.size == 0:
        return audio
    level = 10 ** (threshold_db / 20)
    window = max(1, int(0.01 * RATE))
    env = np.convolve(np.abs(audio), np.ones(window) / window, mode="same")
    loud = np.nonzero(env > level)[0]
    if loud.size == 0:
        return audio[:0]
    keep = int(keep_s * RATE)
    return audio[max(0, loud[0] - keep) : min(audio.size, loud[-1] + keep)]
