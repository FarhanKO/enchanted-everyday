"""Music: a licensed track for each stretch of the story, matched to its mood, and never the same
track over and over across episodes.

The storyboard gives every shot a music mood (calm, wonder, mystery, tension, sorrow, warm,
playful, or none). Runs of shots with one mood become sections; a run shorter than MIN_SECTION_S
joins its neighbour, so the music never flickers. Each section gets a track from
templates/music/library.toml whose moods include it: first one not heard in recent episodes, then
one marked `prefer` (the owner's chosen sound), then one whose strongest mood it is, then one that
suits the section's look (night or day). A `none`
section is silence, so the voice and the ambience carry it; an episode can have no music at all.

Sections crossfade, each is levelled to the same loudness, the storyboard's cues shape it (thin,
swell, silence, out), it fades out under the ending, and it ducks under every spoken line.
"""

from __future__ import annotations

import hashlib
import logging
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import numpy as np

from engine.llm.schemas import MusicMood, Storyboard
from engine.media import ffmpeg
from engine.media.ffmpeg import RATE
from engine.media.timeline import TimedShot

log = logging.getLogger(__name__)

MOODS = tuple(m for m in get_args(MusicMood) if m != "none")
MIN_SECTION_S = 8.0  # shorter runs join a neighbour
CROSSFADE_S = 2.0
END_FADE_S = 3.0  # the music fades out with the picture, after the closing message
RECENT_USES = 10  # tracks heard this recently (about the last four episodes) are passed over
TARGET_RMS = 0.1  # every section is levelled to this before the mix gain
DUCK = 0.45  # how far the music dips under a spoken line (~5 dB, on top of the mix gain)


@dataclass(frozen=True)
class Track:
    path: Path
    title: str
    moods: tuple[str, ...]
    pole: str
    license: str
    credit: str = ""
    gain_db: float = 0.0
    prefer: bool = False  # the owner's chosen sound: played first when it fits and is fresh


@dataclass(frozen=True)
class Section:
    mood: str
    start_s: float
    end_s: float
    pole: str

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Cue:
    """One section with its track (None: silence)."""

    section: Section
    track: Track | None

    def to_json(self) -> dict:
        out: dict = {
            "mood": self.section.mood,
            "from_s": round(self.section.start_s, 2),
            "to_s": round(self.section.end_s, 2),
        }
        if self.track is not None:
            out |= {
                "file": self.track.path.name,
                "title": self.track.title,
                "license": self.track.license,
                "credit": self.track.credit,
            }
        return out


def library(music_dir: Path) -> list[Track]:
    """The tracks in library.toml that exist and carry a license (no license, no use)."""
    manifest = music_dir / "library.toml"
    if not manifest.exists():
        return []
    with open(manifest, "rb") as f:
        entries = tomllib.load(f).get("track", [])
    tracks = []
    for e in entries:
        path = music_dir / e["file"]
        if not e.get("license"):
            log.warning("music track without a license is skipped", extra={"file": e["file"]})
            continue
        if not path.exists():
            continue
        moods = tuple(e.get("moods") or ("calm",))
        if unknown := set(moods) - set(MOODS):
            log.warning("unknown music moods ignored", extra={"file": e["file"], "moods": unknown})
            moods = tuple(m for m in moods if m in MOODS) or ("calm",)
        tracks.append(
            Track(
                path=path,
                title=e.get("title", path.stem),
                moods=moods,
                pole=e.get("pole", "any"),
                license=e["license"],
                credit=e.get("credit", ""),
                gain_db=float(e.get("gain_db", 0.0)),
                prefer=bool(e.get("prefer", False)),
            )
        )
    return tracks


def sections(board: Storyboard, shots: Sequence[TimedShot]) -> list[Section]:
    """Runs of shots with one mood, on the rendered timeline, short runs folded into a
    neighbour (the first into the next, any other into the one before)."""
    by_id = {s.id: s for s in board.shots}
    runs: list[list] = []  # [mood, start, end, {pole: seconds}]
    for t in shots:
        shot = by_id[t.id]
        if runs and runs[-1][0] == shot.music:
            runs[-1][2] = t.end_s
        else:
            runs.append([shot.music, t.start_s, t.end_s, {}])
        poles = runs[-1][3]
        poles[shot.pole] = poles.get(shot.pole, 0.0) + t.duration_s

    def merge(into: int, other: int) -> None:
        keep, gone = runs[into], runs[other]
        keep[1], keep[2] = min(keep[1], gone[1]), max(keep[2], gone[2])
        for pole, secs in gone[3].items():
            keep[3][pole] = keep[3].get(pole, 0.0) + secs
        del runs[other]

    while len(runs) > 1:
        short = next((i for i, r in enumerate(runs) if r[2] - r[1] < MIN_SECTION_S), None)
        if short is None:
            break
        if short == 0:
            merge(1, 0)
        else:
            merge(short - 1, short)
        # neighbours that now share a mood become one section
        i = 1
        while i < len(runs):
            if runs[i][0] == runs[i - 1][0]:
                merge(i - 1, i)
            else:
                i += 1
    return [Section(m, a, b, max(p, key=p.get)) for m, a, b, p in runs]


def choose(
    secs: Sequence[Section], tracks: Sequence[Track], recent: Sequence[str], seed: str
) -> list[Cue]:
    """A track per section. `recent`: file names heard in earlier episodes, most recent first."""
    recent = list(recent)[:RECENT_USES]
    used: set[str] = set()
    out = []
    for sec in secs:
        if sec.mood == "none":
            out.append(Cue(sec, None))
            continue
        fitting = [t for t in tracks if sec.mood in t.moods]
        fresh = [t for t in fitting if t.path.name not in used] or fitting

        def rank(t: Track, sec: Section = sec) -> tuple:
            name = t.path.name
            heard = RECENT_USES - recent.index(name) if name in recent else 0
            return (
                heard,  # not heard lately first; otherwise the one heard longest ago
                0 if t.prefer else 1,  # then the owner's preferred sound
                t.moods.index(sec.mood),  # the track's strongest mood first
                0 if t.pole in (sec.pole, "any") else 1,
                hashlib.sha256(f"{seed}:{name}".encode()).hexdigest(),  # varied, reproducible
            )

        pick = min(fresh, key=rank) if fresh else None
        if pick is None:
            log.warning("no music track for a mood", extra={"mood": sec.mood})
        else:
            used.add(pick.path.name)
        out.append(Cue(sec, pick))
    return out


def _fade(n: int, rising: bool) -> np.ndarray:
    ramp = np.sin(np.linspace(0, np.pi / 2, max(n, 1), dtype=np.float32)) ** 2
    return ramp if rising else ramp[::-1]


def _segment(audio: np.ndarray, n: int, gain_db: float) -> np.ndarray:
    """`n` samples from the top of a track (looped if short), levelled to TARGET_RMS."""
    audio = ffmpeg.trim_silence(audio, threshold_db=-50.0)
    if audio.size == 0 or n <= 0:
        return np.zeros(max(n, 0), np.float32)
    seg = np.tile(audio, -(-n // audio.size))[:n]
    rms = float(np.sqrt(np.mean(seg**2)))
    if rms > 0:
        seg = seg * (TARGET_RMS / rms)
    peak = float(np.max(np.abs(seg)))
    if peak > 0.9:
        seg = seg * (0.9 / peak)
    return (seg * 10 ** (gain_db / 20)).astype(np.float32)


def planned_to_actual(board: Storyboard, shots: Sequence[TimedShot]) -> Callable[[float], float]:
    """Map a time on the storyboard's plan to the rendered timeline (for the music cues)."""
    xp = [0.0] + [s.end_s for s in board.shots]
    fp = [0.0] + [s.end_s for s in shots]
    return lambda t: float(np.interp(t, xp, fp))


def _shape(env: np.ndarray, board: Storyboard, shots: Sequence[TimedShot]) -> None:
    """The storyboard's cues, on the rendered timeline."""
    total = env.size
    to_actual = planned_to_actual(board, shots)
    for cue in board.sound.cues:
        at = min(total, int(to_actual(cue.at_s) * RATE))
        if cue.action == "silence":
            n, ramp = int(2.5 * RATE), RATE // 2
            env[at : at + n] = 0
            before = env[max(0, at - ramp) : at]
            before *= _fade(before.size, False)
            after = env[at + n : at + n + ramp]
            after *= _fade(after.size, True)
        elif cue.action == "thin":
            env[at:] *= 0.6
        elif cue.action == "swell":
            env[at : at + 6 * RATE] *= 1.25
        elif cue.action == "out":
            n = min(total - at, 3 * RATE)
            env[at : at + n] *= _fade(n, False)
            env[at + n :] = 0


def bed(
    cues: Sequence[Cue],
    board: Storyboard,
    shots: Sequence[TimedShot],
    voice: np.ndarray,
    decode: Callable[[Path], np.ndarray] = ffmpeg.decode,
) -> np.ndarray:
    """The music under the whole episode, before the mix gain."""
    total = voice.size
    out = np.zeros(total, np.float32)
    xf = int(CROSSFADE_S * RATE)
    decoded: dict[Path, np.ndarray] = {}
    for i, cue in enumerate(cues):
        if cue.track is None:
            continue
        first, last = i == 0, i == len(cues) - 1
        # each section reaches half a crossfade into its neighbours, so they overlap
        a = 0 if first else max(0, int(cue.section.start_s * RATE) - xf // 2)
        b = total if last else min(total, int(cue.section.end_s * RATE) + xf // 2)
        if b <= a:
            continue
        if cue.track.path not in decoded:
            decoded[cue.track.path] = decode(cue.track.path)
        seg = _segment(decoded[cue.track.path], b - a, cue.track.gain_db)
        k_in = min(2 * RATE if first else xf, seg.size // 2)
        seg[:k_in] *= _fade(k_in, True)
        if not last:
            k_out = min(xf, seg.size // 2)
            seg[-k_out:] *= _fade(k_out, False)
        out[a:b] += seg

    env = np.ones(total, np.float32)
    _shape(env, board, shots)
    tail = min(total, int(END_FADE_S * RATE))
    env[total - tail :] *= _fade(tail, False)

    # duck under the voice: a smoothed envelope of the speech pulls the music down
    level = np.convolve(np.abs(voice), np.ones(RATE // 5) / (RATE // 5), mode="same")
    duck = 1 - DUCK * np.clip(level / 0.05, 0, 1)
    return out * env * duck.astype(np.float32)


def credits(cues: Sequence[Cue]) -> list[str]:
    """The attribution lines to post with the episode, once per track, in the order heard."""
    seen: list[str] = []
    for cue in cues:
        if cue.track is not None and cue.track.credit and cue.track.credit not in seen:
            seen.append(cue.track.credit)
    return seen
