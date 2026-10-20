"""The voice track: every script line in its speaker's voice, the scripted pauses as real silence,
and a quiet hold at the end.

Each line is voiced on its own, so its exact start and end are known: shots and captions are timed
to the real audio, not to an estimate. A line's delivery note picks the Eleven v4 audio tag it is
spoken with ([softly], [whispers], ...); children's voices are pitch-lifted locally
(brand/voices.toml). After the landing the last image holds in silence while the script's closing
line, the story's message, appears in italics (render); nothing more is spoken.

Pace: Eleven v4 reads faster than a story told at 2 AM, and OpenRouter can't slow it. So each line
is measured and, when it runs faster than its speaker's `pace_wpm`, slowed locally with the pitch
kept (ffmpeg rubberband), never below `min_tempo`; then every sentence break inside a line is
given at least `sentence_pause_s` of silence.
"""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import numpy as np

from engine.llm.schemas import PACE_WPM, Script, word_count
from engine.media import ffmpeg
from engine.media.ffmpeg import RATE
from engine.media.openrouter import MediaError, speech_cost
from engine.media.paid import Ledger, cache_key

log = logging.getLogger(__name__)

MIN_GAP_S = 0.12  # a breath between lines even when the script asks for no pause
SENTENCE_GAP_S = 0.22  # a silence inside a line at least this long is a sentence break
# the closing message: it fades in a beat after the last line, stays long enough to read slowly,
# and the video ends a moment after it (the picture fades out over that moment)
MESSAGE_DELAY_S = 0.6
MESSAGE_BASE_S, MESSAGE_PER_WORD_S = 1.6, 0.3
MESSAGE_MIN_S, MESSAGE_MAX_S = 3.0, 4.5
TAIL_S = 1.2
HOLD_S = 2.5  # the ending's length when a script has no closing line (written before they existed)

# delivery-note words -> Eleven v4 audio tag; the first match in the note wins, plus [slowly]
_TAGS = (
    (r"\bwhisper", "[whispers]"),
    (r"\bsigh", "[sighs]"),
    (r"\bhesitat", "[hesitates]"),
    (r"\b(hush|soft|gentle|quiet|tender|warm|low\b|secret|intimate)", "[softly]"),  # not "slower"
)
_SLOW = re.compile(r"\bslow", re.IGNORECASE)


class Speaker(Protocol):
    def __call__(self, text: str, model: str, voice: str) -> bytes: ...


@dataclass(frozen=True)
class VoiceLine:
    index: int
    beat: str
    speaker: str
    text: str
    start_s: float
    end_s: float
    pause_s: float


@dataclass(frozen=True)
class VoiceTrack:
    path: Path
    lines: list[VoiceLine]
    story_end_s: float  # the last line and its pause are over; the ending holds from here
    message_start_s: float  # the closing message on screen (start == end: none)
    message_end_s: float
    duration_s: float
    cost_usd: Decimal

    def to_json(self) -> dict:
        return {
            "path": str(self.path),
            "lines": [asdict(line) for line in self.lines],
            "story_end_s": self.story_end_s,
            "message_start_s": self.message_start_s,
            "message_end_s": self.message_end_s,
            "duration_s": self.duration_s,
            "cost_usd": str(self.cost_usd),
        }

    @classmethod
    def from_json(cls, data: dict) -> VoiceTrack:
        return cls(
            path=Path(data["path"]),
            lines=[VoiceLine(**line) for line in data["lines"]],
            # tracks voiced before 2026-10-20 ended on a bell and a spoken line instead
            story_end_s=data.get("story_end_s", data.get("bell_at_s")),
            message_start_s=data.get("message_start_s", data.get("signature_start_s")),
            message_end_s=data.get("message_end_s", data.get("signature_end_s")),
            duration_s=data["duration_s"],
            cost_usd=Decimal(data["cost_usd"]),
        )


def tagged(text: str, delivery: str, slow: bool = False) -> str:
    """'Fann sold his first dream at midnight.' + 'hushed, slower' -> '[softly] [slowly] Fann...'

    `slow`: the speaker always speaks [slowly] (voices.toml), whatever the note says."""
    tags = [tag for pattern, tag in _TAGS if re.search(pattern, delivery, re.IGNORECASE)][:1]
    if slow or _SLOW.search(delivery):
        tags.append("[slowly]")
    return " ".join([*tags, text])


def tempo_for(words: int, seconds: float, target_wpm: float, min_tempo: float) -> float:
    """How much to slow a line read at words/seconds to reach target_wpm (1.0: leave it)."""
    if words < 3 or seconds <= 0:  # too short to measure a pace
        return 1.0
    wpm = words / seconds * 60
    return 1.0 if wpm <= target_wpm * 1.02 else max(min_tempo, target_wpm / wpm)


def breathe(audio: np.ndarray, min_pause_s: float, threshold_db: float = -45.0) -> np.ndarray:
    """Every sentence break inside a line (a pause of at least SENTENCE_GAP_S between words)
    lasts at least `min_pause_s`, so two sentences never run together. Longer pauses, like the
    ones Eleven's [slowly] already makes, are left alone."""
    if min_pause_s <= 0 or audio.size == 0:
        return audio
    window = max(1, int(0.01 * RATE))
    env = np.convolve(np.abs(audio), np.ones(window) / window, mode="same")
    quiet = np.concatenate([[False], env < 10 ** (threshold_db / 20), [False]]).astype(np.int8)
    starts = np.flatnonzero(np.diff(quiet) == 1)  # each quiet run: audio[start:stop]
    stops = np.flatnonzero(np.diff(quiet) == -1)
    pieces, last = [], 0
    for start, stop in zip(starts, stops, strict=True):
        gap = stop - start
        if start == 0 or stop == audio.size or gap < SENTENCE_GAP_S * RATE:
            continue  # the clip's own edges, or a comma-sized gap
        extra = int(min_pause_s * RATE) - gap
        if extra <= 0:
            continue
        middle = (start + stop) // 2
        pieces += [audio[last:middle], np.zeros(extra, np.float32)]
        last = middle
    return np.concatenate([*pieces, audio[last:]]) if pieces else audio


def load_cast(brand_dir: Path) -> dict:
    with open(brand_dir / "voices.toml", "rb") as f:
        return tomllib.load(f)


def message_span(story_end_s: float, closing_line: str) -> tuple[float, float, float]:
    """(message start, message end, video end) for the ending after story_end_s."""
    words = word_count(closing_line)
    if not words:
        return story_end_s, story_end_s, story_end_s + HOLD_S
    start = story_end_s + MESSAGE_DELAY_S
    on = min(MESSAGE_MAX_S, max(MESSAGE_MIN_S, MESSAGE_BASE_S + MESSAGE_PER_WORD_S * words))
    return start, start + on, start + on + TAIL_S


class VoiceMaker:
    def __init__(self, speak: Speaker, ledger: Ledger, brand_dir: Path, cache_dir: Path) -> None:
        self.speak = speak
        self.ledger = ledger
        self.cast = load_cast(brand_dir)
        self.cache_dir = cache_dir
        self.spent = Decimal(0)

    def _role(self, speaker: str) -> dict:
        role = self.cast.get(speaker)
        if not isinstance(role, dict):
            raise MediaError(f"no voice for speaker '{speaker}' in voices.toml")
        return role

    def _mp3(self, text: str, voice: str) -> Path:
        """The line's audio, from the cache or paid for once (falling back to the older model)."""
        models = [self.cast["model"], self.cast.get("fallback_model")]
        key = cache_key(models[0], voice, text)
        path = self.cache_dir / f"{key}.mp3"
        if path.exists():
            return path
        cost = speech_cost(models[0], text)
        self.ledger.check(cost)
        last: Exception | None = None
        for model in filter(None, models):
            try:
                audio = self.speak(text, model, voice)
            except MediaError as e:
                if e.status is not None and e.status >= 500:
                    raise  # an outage, not a voice/model problem: the fallback won't help
                last = e
                log.warning("speech failed; trying the fallback", extra={"model": model})
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
            self.ledger.record("voice", model, cost, path, {"voice": voice, "text": text})
            self.spent += cost
            return path
        raise MediaError(f"no speech model could voice '{voice}': {last}")

    def _line_audio(self, speaker: str, text: str, delivery: str) -> np.ndarray:
        role = self._role(speaker)
        mp3 = self._mp3(tagged(text, delivery, bool(role.get("slow"))), role["voice"])
        audio = ffmpeg.trim_silence(ffmpeg.decode(mp3))
        target = float(role.get("pace_wpm", self.cast.get("pace_wpm", PACE_WPM)))
        min_tempo = float(self.cast.get("min_tempo", 0.8))
        tempo = tempo_for(word_count(text), audio.size / RATE, target, min_tempo)
        semis = role.get("pitch_semitones")
        stretch = []
        if tempo < 1.0:
            stretch.append(f"tempo={tempo:.4f}")
        if semis:
            stretch.append(f"pitch={2 ** (semis / 12):.4f}:formant=shifted")
        if stretch:
            audio = ffmpeg.trim_silence(ffmpeg.decode(mp3, "rubberband=" + ":".join(stretch)))
        return breathe(audio, float(self.cast.get("sentence_pause_s", 0.0)))

    def make(self, script: Script, out: Path) -> VoiceTrack:
        pieces: list[np.ndarray] = []
        lines: list[VoiceLine] = []
        t = 0.0
        index = 0
        for beat in script.beats:
            for line in beat.lines:
                audio = self._line_audio(line.speaker, line.text, line.delivery)
                length = audio.size / RATE
                pause = max(line.pause_after_s, MIN_GAP_S)
                lines.append(
                    VoiceLine(index, beat.name, line.speaker, line.text, t, t + length, pause)
                )
                pieces += [audio, np.zeros(int(pause * RATE), np.float32)]
                t += length + pause
                index += 1

        msg_start, msg_end, end = message_span(t, script.closing_line)
        pieces.append(np.zeros(int((end - t) * RATE), np.float32))

        track = np.concatenate(pieces)
        ffmpeg.write_wav(out, track)
        return VoiceTrack(
            path=out,
            lines=lines,
            story_end_s=t,
            message_start_s=msg_start,
            message_end_s=msg_end,
            duration_s=track.size / RATE,
            cost_usd=self.spent,
        )
