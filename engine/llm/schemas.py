"""Episode contracts: what each story agent must return, and the rules a JSON schema can't express.

The chain mirrors the brief's studio: story architect -> script writer -> storyboard/visual director
-> packaging, with a critic between steps. Each step returns one contract; together they form an
`Episode`, the single document that render, approval and publishing work from.

The API constrains output shape with `api_schema(Model)`. The Pydantic model then re-validates
everything the API can't check: beat order, timing, word counts, references between shots and
characters, the AI-clip budget, and banned style terms.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# --- brand constants (see brand/story_bible.md and brand/production_style.md)
PACE_WPM = 120  # bedtime narration pace
MIN_DURATION_S, MAX_DURATION_S = 45, 90
MIN_WORDS, MAX_WORDS = 80, 190
MAX_HOOK_WORDS = 12
MAX_AI_CLIPS = 2
DURATION_TOLERANCE_S = 10  # storyboard length vs. estimated narration length
BEAT_ORDER = ("hook", "mystery", "connection", "cost", "reveal", "landing")
BANNED_STYLE_TERMS = (
    "ghibli",
    "miyazaki",
    "shinkai",
    "pixar",
    "disney",
    "dreamworks",
    "kyoto animation",
    "rutkowski",
    "artstation",
    "in the style of",
)

Pillar = Literal["strange_thing", "never_said", "price_of_wish", "before_sleep", "nowhere_places"]
Lane = Literal["dark_urban", "cozy_bedtime"]
Pole = Literal["night", "day"]
BeatName = Literal["hook", "mystery", "connection", "cost", "reveal", "landing"]
Camera = Literal[
    "push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "parallax", "static"
]
Motion = Literal["still_drift", "ai_clip"]
Overlay = Literal[
    "rain_glass", "rain", "fireflies", "dust_motes", "steam", "film_grain", "light_leak"
]
CueAction = Literal["enter", "swell", "thin", "silence", "resolve", "out"]

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]
Score = Annotated[float, Field(ge=0, le=10)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def _no_banned_terms(text: str) -> str:
    lowered = text.lower()
    hits = [t for t in BANNED_STYLE_TERMS if t in lowered]
    if hits:
        raise ValueError(f"prompt names a protected style or artist: {hits}")
    return text


# ============================================================ 1. story card (story architect)


class StoryScores(_Strict):
    hook: Score = Field(description="Would a stranger stop scrolling at the first line? 0-10")
    emotion: Score = Field(description="Is there a true, recognisable human feeling? 0-10")
    visual: Score = Field(description="Does it have a memorable image or object? 0-10")
    brand_fit: Score = Field(description="Does it obey the story bible's twelve rules? 0-10")


class StoryCard(_Strict):
    title: str = Field(min_length=3, max_length=80)
    pillar: Pillar
    lane: Lane
    premise: str = Field(description="One sentence: ordinary person + impossible element + stakes")
    human_emotion: str = Field(description="The feeling the story is really about")
    magical_element: str = Field(description="The impossible thing, and what it reveals about them")
    visual_anchor: str = Field(description="The one object or place viewers will remember")
    recurring: list[Slug] = Field(
        description="Recurring universe entities used, e.g. midnight_shop"
    )
    ending_image: str = Field(description="The final image, choice or line")
    scores: StoryScores

    @property
    def total_score(self) -> float:
        s = self.scores
        return s.hook + s.emotion + s.visual + s.brand_fit


class StoryCards(_Strict):
    cards: list[StoryCard] = Field(min_length=1)


# ============================================================ 2. script (script writer)


class Line(_Strict):
    text: str = Field(min_length=1, description="Exactly what the narrator says")
    delivery: str = Field(description="How to say it: e.g. 'hushed, slower, slight smile'")
    pause_after_s: float = Field(ge=0, le=3, description="Silence after the line, in seconds")


class Beat(_Strict):
    name: BeatName
    lines: list[Line] = Field(min_length=1)


class Script(_Strict):
    title: str
    narration_direction: str = Field(description="Overall voice direction for this episode")
    beats: list[Beat] = Field(description="Exactly six beats, in formula order")

    @property
    def lines(self) -> list[Line]:
        return [line for b in self.beats for line in b.lines]

    @property
    def spoken_text(self) -> str:
        return " ".join(line.text for line in self.lines)

    @property
    def word_count(self) -> int:
        return word_count(self.spoken_text)

    @property
    def estimated_duration_s(self) -> float:
        return self.word_count / PACE_WPM * 60 + sum(line.pause_after_s for line in self.lines)

    @model_validator(mode="after")
    def _formula(self) -> Script:
        names = tuple(b.name for b in self.beats)
        if names != BEAT_ORDER:
            raise ValueError(f"beats must be {BEAT_ORDER}, got {names}")
        hook_words = word_count(" ".join(line.text for line in self.beats[0].lines))
        if hook_words > MAX_HOOK_WORDS:
            raise ValueError(f"hook is {hook_words} words; max {MAX_HOOK_WORDS}")
        if not MIN_WORDS <= self.word_count <= MAX_WORDS:
            raise ValueError(f"script is {self.word_count} words; need {MIN_WORDS}-{MAX_WORDS}")
        dur = self.estimated_duration_s
        if not MIN_DURATION_S <= dur <= MAX_DURATION_S:
            raise ValueError(
                f"estimated {dur:.0f}s at {PACE_WPM} wpm; need {MIN_DURATION_S}-{MAX_DURATION_S}s"
            )
        return self


# ============================================================ 3. storyboard (visual director)


class Character(_Strict):
    id: Slug
    name: str
    role: str
    descriptor: str = Field(
        min_length=60,
        description="Locked visual description inserted verbatim in every prompt showing them: "
        "age, build, hair, face, wardrobe, colour anchor",
    )
    signature: str = Field(description="Colour item + prop that identify them in silhouette")
    recurring: bool = Field(description="True if part of the shared universe (e.g. the Shopkeeper)")


class Location(_Strict):
    id: Slug
    name: str
    pole: Pole
    descriptor: str = Field(min_length=40, description="Locked description of the place")
    lighting: str


class Shot(_Strict):
    id: str = Field(pattern=r"^S\d{2}$")
    beat: BeatName
    start_s: float = Field(ge=0)
    duration_s: float = Field(ge=1.5, le=15)
    description: str = Field(description="What the viewer sees and why it matters")
    camera: Camera
    pole: Pole
    location: Slug
    characters: list[Slug]
    image_prompt: str = Field(
        description="Shot-specific content only: framing, action, emotion, key props. Refer to "
        "characters by name; code appends their locked descriptors, location and style block"
    )
    motion: Motion
    video_prompt: str = Field(
        description="Environment and subtle body motion for an image-to-video model; code adds the "
        "camera move and the locked motion suffix"
    )
    overlays: list[Overlay]
    sfx: list[str]

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    @field_validator("image_prompt", "video_prompt")
    @classmethod
    def _style_terms(cls, v: str) -> str:
        return _no_banned_terms(v)


class MusicCue(_Strict):
    at_s: float = Field(ge=0)
    action: CueAction
    note: str


class Sound(_Strict):
    music_palette: str = Field(description="Instruments, tempo and feel of the music bed")
    cues: list[MusicCue]
    ambience: list[str]


class Storyboard(_Strict):
    characters: list[Character]
    locations: list[Location] = Field(min_length=1)
    shots: list[Shot] = Field(min_length=5, max_length=14)
    sound: Sound

    @property
    def duration_s(self) -> float:
        return self.shots[-1].end_s

    @model_validator(mode="after")
    def _consistency(self) -> Storyboard:
        chars = {c.id for c in self.characters}
        locs = {loc.id for loc in self.locations}
        if len(chars) != len(self.characters) or len(locs) != len(self.locations):
            raise ValueError("character and location ids must be unique")

        t = 0.0
        for shot in self.shots:
            if abs(shot.start_s - t) > 0.25:
                raise ValueError(
                    f"{shot.id} starts at {shot.start_s}s; expected {t:.2f}s (gap/overlap)"
                )
            if shot.location not in locs:
                raise ValueError(f"{shot.id} uses unknown location '{shot.location}'")
            if unknown := set(shot.characters) - chars:
                raise ValueError(f"{shot.id} uses unknown characters {sorted(unknown)}")
            t = shot.end_s

        order = [BEAT_ORDER.index(s.beat) for s in self.shots]
        if order != sorted(order) or set(order) != set(range(len(BEAT_ORDER))):
            raise ValueError("shots must cover every beat, in formula order")

        clips = sum(s.motion == "ai_clip" for s in self.shots)
        if clips > MAX_AI_CLIPS:
            raise ValueError(f"{clips} ai_clip shots; budget is {MAX_AI_CLIPS}")
        if any(c.at_s > self.duration_s for c in self.sound.cues):
            raise ValueError("a music cue falls after the last shot")
        return self


# ============================================================ 4. package (publishing)


class Thumbnail(_Strict):
    concept: str = Field(description="One face or object, one emotion, one contrast")
    text: str = Field(description="0-4 words, or empty")
    pole: Pole
    location: Slug
    characters: list[Slug]
    image_prompt: str = Field(description="Shot-specific content only, as for shots")

    @field_validator("text")
    @classmethod
    def _short(cls, v: str) -> str:
        if word_count(v) > 4:
            raise ValueError("thumbnail text is at most 4 words")
        return v

    @field_validator("image_prompt")
    @classmethod
    def _style_terms(cls, v: str) -> str:
        return _no_banned_terms(v)


class PlatformCopy(_Strict):
    youtube_title: str = Field(min_length=1, max_length=100)
    youtube_description: str
    tiktok_caption: str = Field(max_length=2200)
    instagram_caption: str = Field(max_length=2200)
    facebook_caption: str
    hashtags: list[str] = Field(min_length=3, max_length=8)

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, tags: list[str]) -> list[str]:
        return [t if t.startswith("#") else f"#{t}" for t in (t.strip() for t in tags) if t]


class Package(_Strict):
    title: str = Field(max_length=60, description="Simple premise + unanswered question")
    alt_titles: list[str] = Field(min_length=2, max_length=3, description="For A/B tests")
    thumbnail: Thumbnail
    platforms: PlatformCopy
    comment_prompt: str = Field(description="One gentle question that extends the story")
    long_form_path: str = Field(description="Which long-form collection this story belongs in")


# ============================================================ critic


class CriticIssue(_Strict):
    area: Literal["story", "script", "visual", "sound", "package", "policy"]
    rule: int = Field(ge=0, le=12, description="Story bible rule number, or 0")
    problem: str
    fix: str
    severity: Literal["low", "high"]


class CriticReport(_Strict):
    verdict: Literal["pass", "revise", "reject"]
    issues: list[CriticIssue]

    @property
    def blocking(self) -> bool:
        return self.verdict != "pass" or any(i.severity == "high" for i in self.issues)


# ============================================================ the whole episode


class Episode(_Strict):
    id: str
    slate_id: str | None = None
    card: StoryCard
    script: Script
    storyboard: Storyboard
    package: Package

    @model_validator(mode="after")
    def _fits(self) -> Episode:
        thumb = self.package.thumbnail
        if thumb.location not in {loc.id for loc in self.storyboard.locations}:
            raise ValueError(f"thumbnail uses unknown location '{thumb.location}'")
        if unknown := set(thumb.characters) - {c.id for c in self.storyboard.characters}:
            raise ValueError(f"thumbnail uses unknown characters {sorted(unknown)}")

        gap = abs(self.storyboard.duration_s - self.script.estimated_duration_s)
        if gap > DURATION_TOLERANCE_S:
            raise ValueError(
                f"storyboard runs {self.storyboard.duration_s:.0f}s but narration needs "
                f"~{self.script.estimated_duration_s:.0f}s"
            )
        return self


# ============================================================ API schema

_UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "default",
    "title",
}


def api_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema, reduced to what structured outputs accept.

    Dropped constraints are still enforced when the response is re-validated with the model.
    """

    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(v) for v in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("properties", "$defs"):
                out[key] = {name: clean(sub) for name, sub in value.items()}
            elif key not in _UNSUPPORTED:
                out[key] = clean(value)
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out

    return clean(model.model_json_schema())
