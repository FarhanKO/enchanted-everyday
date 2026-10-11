"""Timing: shots fitted to the real voice track, and phrase-level captions.

The storyboard plans shot lengths from a words-per-minute estimate. Once the voice exists, each
beat's shots are stretched or squeezed, in proportion, to fill exactly the time that beat's lines
take, so a cut never lands mid-sentence in the wrong beat. The last shot holds through the
signature ending.

Captions follow production_style.md §6: 2-6 words cut at natural phrase breaks, at most 2 lines
of 26 characters, timed within each line in proportion to its characters. Pauses show no caption.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine.llm.schemas import BEAT_ORDER, Storyboard
from engine.media.voice import VoiceTrack

MAX_WORDS, MIN_WORDS = 6, 2
LINE_CHARS, MAX_LINES = 26, 2
MIN_CAPTION_S = 0.7


@dataclass(frozen=True)
class TimedShot:
    id: str
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Caption:
    start_s: float
    end_s: float
    lines: list[str]


def fit_shots(board: Storyboard, voice: VoiceTrack) -> list[TimedShot]:
    spans: dict[str, list[float]] = {}
    for line in voice.lines:
        span = spans.setdefault(line.beat, [line.start_s, line.end_s + line.pause_s])
        span[1] = line.end_s + line.pause_s
    # beats tile the track: each starts where the previous ended; the first at 0, the last runs
    # through the bell and the signature line to the end
    bounds: dict[str, tuple[float, float]] = {}
    t = 0.0
    for i, beat in enumerate(BEAT_ORDER):
        end = voice.duration_s if i == len(BEAT_ORDER) - 1 else spans[beat][1]
        bounds[beat] = (t, end)
        t = end

    out: list[TimedShot] = []
    for beat in BEAT_ORDER:
        shots = [s for s in board.shots if s.beat == beat]
        start, end = bounds[beat]
        planned = sum(s.duration_s for s in shots)
        t = start
        for i, shot in enumerate(shots):
            stop = end if i == len(shots) - 1 else t + (end - start) * shot.duration_s / planned
            out.append(TimedShot(shot.id, round(t, 3), round(stop, 3)))
            t = stop
    return out


# ---------------------------------------------------------------- captions


def wrap(words: list[str]) -> list[str] | None:
    """One line if it fits, else two lines as even as possible ("Letters he was / afraid to
    open.", never "Letters he was afraid to / open."); None if two lines can't hold it."""
    one = " ".join(words)
    if len(one) <= LINE_CHARS:
        return [one]
    best: list[str] | None = None
    for i in range(1, len(words)):
        top, bottom = " ".join(words[:i]), " ".join(words[i:])
        if len(top) > LINE_CHARS or len(bottom) > LINE_CHARS:
            continue
        # the most even pair; on a tie, the longer line on top
        if best is None or (max(len(top), len(bottom)), -len(top)) < (
            max(len(best[0]), len(best[1])),
            -len(best[0]),
        ):
            best = [top, bottom]
    return best


def _fits(words: list[str]) -> bool:
    return len(words) <= MAX_WORDS and wrap(words) is not None


# a caption reads best when the next one starts on one of these
BREAK_BEFORE = frozenset(
    [
        "and",
        "but",
        "or",
        "so",
        "as",
        "at",
        "in",
        "on",
        "of",
        "for",
        "to",
        "with",
        "from",
        "into",
        "than",
        "that",
        "which",
        "who",
        "when",
        "where",
        "while",
        "because",
        "if",
        "then",
        "like",
        "until",
        "between",
        "after",
        "before",
        "behind",
        "under",
        "over",
        "across",
        "beneath",
        "through",
        "toward",
        "towards",
    ]
)


def _split(words: list[str]) -> list[list[str]]:
    """A phrase too long for one caption, cut where it reads naturally, into pieces that fit."""
    if _fits(words) or len(words) < 2:
        return [words]

    def score(i: int) -> float:
        left, right = words[:i], words[i:]
        s = -abs(len(left) - len(right)) * 0.5
        s += 2.5 if right[0].lower().strip("\"'“‘") in BREAK_BEFORE else 0
        s -= 2 if left[-1].lower() in BREAK_BEFORE else 0  # never leave "as" dangling
        s += 3 if _fits(left) and _fits(right) else 0
        return s

    i = max(range(1, len(words)), key=lambda i: (score(i), i))  # ties: the longer first line
    return _split(words[:i]) + _split(words[i:])


def phrases(text: str) -> list[list[str]]:
    """Caption chunks for one spoken line: break after punctuation, split long phrases, and fold
    a lone word into its neighbour when they fit together."""
    groups: list[list[str]] = [[]]
    for word in text.split():
        groups[-1].append(word)
        if re.search(r"[,.;:!?…—]['\"”’)]*$", word):
            groups.append([])
    chunks = [piece for g in groups if g for piece in _split(g)]
    merged: list[list[str]] = []
    for chunk in chunks:
        short = merged and (
            len(chunk) < MIN_WORDS
            or len(merged[-1]) < MIN_WORDS
            or len(chunk) + len(merged[-1]) <= 4  # "This one," / she said,
        )
        if short and _fits(merged[-1] + chunk):
            merged[-1] = merged[-1] + chunk
        else:
            merged.append(chunk)
    return merged


def captions(voice: VoiceTrack, signature_line: str) -> list[Caption]:
    timed = [(line.start_s, line.end_s, line.text) for line in voice.lines]
    timed.append((voice.signature_start_s, voice.signature_end_s, signature_line))
    out: list[Caption] = []
    for start, end, text in timed:
        chunks = phrases(text)
        weights = [sum(len(w) for w in c) + 2 * len(c) for c in chunks]
        total = sum(weights)
        t = start
        for chunk, weight in zip(chunks, weights, strict=True):
            stop = t + (end - start) * weight / total
            out.append(Caption(t, max(stop, t + MIN_CAPTION_S), wrap(chunk) or [" ".join(chunk)]))
            t = stop
    # a caption held to its minimum must not run into the next one
    for i in range(len(out) - 1):
        if out[i].end_s > out[i + 1].start_s:
            out[i] = Caption(out[i].start_s, out[i + 1].start_s, out[i].lines)
    return out
