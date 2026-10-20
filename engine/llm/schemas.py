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
PACE_WPM = 120  # bedtime narration pace; the voice stage slows each line to it (voices.toml)
# the script's own length; the voice's breaths and the signature ending add ~6 s, so the video stays
# within 90 s (Facebook's Reels API takes 3-90 s)
MIN_DURATION_S, MAX_DURATION_S = 45, 84
MIN_WORDS, MAX_WORDS = 80, 170
MAX_HOOK_WORDS = 8  # ~3-4 s spoken; the first frame carries the image from 0 s (rule 4)
MAX_AI_CLIPS = 2
MAX_SPEAKERS = 3  # characters with spoken lines in one episode, besides the narrator
MIN_MIXED_CHARACTER_LINES = 2  # a mixed episode lets the characters really be heard
MIN_SHOTS, MAX_SHOTS = 5, 16  # a picture for every event (2026-10-12)
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
# Rule 6: endings that state a lesson instead of leaving an image
MORAL_PATTERNS = (
    r"\bthe (moral|lesson)\b",
    r"\b(we|you) should (always|never)\b",
    r"\bthat'?s why (we|you)\b",
    r"\balways remember\b",
    r"\bnever forget (that|to)\b",
    r"\b(learned|learnt) (that|to)\b",
    r"\bremember,? (kids|friends|everyone)\b",
)

Universe = Literal["urban", "emotional", "bedtime"]
StoryType = Literal["fable", "daily"]
Mode = Literal["narrated", "dialogue", "mixed"]
Lead = Literal["", "fann", "tina", "both"]  # "": cards from before leads were assigned
# who says a line: the narrator, a fixed cast id, or a voice role for anyone else (voices.toml)
Speaker = Literal[
    "narrator",
    "fann",
    "tina",
    "shopkeeper",
    "child_girl",
    "child_boy",
    "old_man",
    "woman",
    "young_man",
    "stranger",
    "spirit",
]
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
# the music under a shot; the render picks a licensed track per run of shots with one mood
# (templates/music/library.toml) and never the same one twice in a row across episodes
MusicMood = Literal["none", "calm", "wonder", "mystery", "tension", "sorrow", "warm", "playful"]
# every episode opens out of black; the close dissolves into one of these, matched to the ending
FadeOut = Literal["black", "white", "glow", "sunray"]

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
    brand_fit: Score = Field(description="Does it obey the story bible's rules? 0-10")


class StoryCard(_Strict):
    title: str = Field(min_length=3, max_length=80)
    universe: Universe = Field(
        description="urban: a strange event intrudes on one ordinary city life (hook: what is "
        "happening?). emotional: an impossible offer, rule or what-if with a personal cost "
        "(hook: what would you do?). bedtime: gentle, warm, nature or sky, no threat"
    )
    story_type: StoryType = Field(
        description="fable: a short story whose message lives in its final image or choice, never "
        "stated. daily: a small magical moment in Fann's or Tina's ordinary day, fairytale "
        "aesthetics, no big cost or twist"
    )
    mode: Mode = Field(
        description="Who speaks. narrated: the story is an event as a whole; only the narrator. "
        "dialogue: a small moment of characters interacting; only the characters. mixed: the "
        "narrator carries the story and characters speak their key lines"
    )
    lead: Lead = Field(
        default="",
        description="Who leads the episode: the lead given in <lead> (fann, tina, or both "
        "sharing the story). Bedtime fables too, with the lead as the storyteller or the one it "
        "happens to",
    )
    premise: str = Field(description="One sentence: ordinary person + impossible element + stakes")
    human_emotion: str = Field(description="The feeling the story is really about (rule 1)")
    magical_element: str = Field(
        description="The impossible thing, and how it embodies or amplifies that emotion (rule 2)"
    )
    visual_anchor: str = Field(description="The one object or place viewers will remember")
    recurring: list[Slug] = Field(
        description="Recurring universe entities used, e.g. midnight_shop"
    )
    ending_image: str = Field(description="The final image, choice or line, never a moral")
    lingering_question: str = Field(
        description="What the viewer is left thinking about afterwards (rule 7)"
    )
    connection: str = Field(
        description="How this episode touches the shared world: a callback to an earlier "
        "episode, a trace of the other lead, or a step in Fann's lost-dreams thread. The episode "
        "must still make complete sense without it"
    )
    advances_dreams_thread: bool = Field(
        description="True if this episode moves Fann's lost-dreams storyline forward"
    )
    dreams_step: str = Field(
        default="",  # cards written before the season plan have none
        description="When advances_dreams_thread is true: the id of the step this episode tells, "
        "from dreams_thread (e.g. D3). Empty otherwise",
    )
    scores: StoryScores

    @property
    def total_score(self) -> float:
        s = self.scores
        return s.hook + s.emotion + s.visual + s.brand_fit


class CandidateCard(_Strict):
    ref: str = Field(description="The candidate's ref, or 'new' for an original premise")
    card: StoryCard


class StoryCards(_Strict):
    cards: list[CandidateCard] = Field(min_length=1)


# ============================================================ 2. script (script writer)


class Line(_Strict):
    speaker: Speaker = Field(
        description="Who says it: narrator, a fixed cast id, or a voice role for anyone else"
    )
    text: str = Field(min_length=1, description="Exactly what is said")
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
        hook_words = word_count(self.beats[0].lines[0].text)
        if hook_words > MAX_HOOK_WORDS:
            raise ValueError(
                f"hook line is {hook_words} words; max {MAX_HOOK_WORDS} (3-second rule)"
            )
        for line in self.lines:
            for pattern in MORAL_PATTERNS:
                if re.search(pattern, line.text, re.IGNORECASE):
                    raise ValueError(f"moral-of-the-story line (rule 6): {line.text!r}")
        if not MIN_WORDS <= self.word_count <= MAX_WORDS:
            raise ValueError(f"script is {self.word_count} words; need {MIN_WORDS}-{MAX_WORDS}")
        dur = self.estimated_duration_s
        if not MIN_DURATION_S <= dur <= MAX_DURATION_S:
            raise ValueError(
                f"estimated {dur:.0f}s at {PACE_WPM} wpm; need {MIN_DURATION_S}-{MAX_DURATION_S}s"
            )
        return self


def speaker_label(speaker: str) -> str:
    """'tina' -> 'TINA', 'child_girl' -> 'CHILD GIRL'."""
    return speaker.replace("_", " ").upper()


def check_speakers(mode: str, script: Script) -> None:
    """The card's mode decides who may speak. Raises ValueError with what to fix."""
    speakers = [line.speaker for line in script.lines]
    narrator = speakers.count("narrator")
    characters = set(speakers) - {"narrator"}
    if mode == "narrated" and characters:
        raise ValueError(
            f"mode is narrated, so only the narrator speaks; found {sorted(characters)}"
        )
    if mode == "dialogue" and narrator:
        raise ValueError(f"mode is dialogue, so the narrator has no lines; found {narrator}")
    if mode == "mixed" and not (narrator and characters):
        raise ValueError("mode is mixed: both the narrator and at least one character speak")
    if len(characters) > MAX_SPEAKERS:
        raise ValueError(
            f"{len(characters)} characters speak ({sorted(characters)}); max {MAX_SPEAKERS}"
        )


# a narrator line quoting someone: "This one," she said
_QUOTE = re.compile(r"[\"“”][^\"“”]{2,}[\"“”]")


def check_voicing(mode: str, script: Script) -> None:
    """Characters are heard in their own voices: the narrator never quotes them, and a mixed
    episode gives them enough lines to be heard. Checked on new scripts only, so older episodes
    still load. Raises ValueError with what to fix."""
    if mode != "narrated":
        for line in script.lines:
            if line.speaker == "narrator" and _QUOTE.search(line.text):
                raise ValueError(
                    f"the narrator quotes a character in {line.text!r}: give the quoted words "
                    "their own line, spoken by that character, and keep the narration around it"
                )
    if mode == "mixed":
        said = sum(line.speaker != "narrator" for line in script.lines)
        if said < MIN_MIXED_CHARACTER_LINES:
            raise ValueError(
                f"mode is mixed but characters speak {said} line(s); give them at least "
                f"{MIN_MIXED_CHARACTER_LINES}, at the moments that matter most"
            )


# ============================================================ 3. storyboard (visual director)


class Character(_Strict):
    id: Slug = Field(
        description="Fixed cast (brand/cast.toml) keep their cast id: fann, tina, shopkeeper"
    )
    name: str
    role: str
    descriptor: str = Field(
        min_length=60,
        description="Locked visual description inserted verbatim in every prompt showing them: "
        "age, build, hair, face, wardrobe, colour anchor. For the fixed cast, copy cast.toml; "
        "for anyone else, make them clearly distinct from the leads",
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
    music: MusicMood = Field(
        default="calm",  # storyboards written before music moods have none
        description="The music under this shot: calm (setting the scene, quiet nights), wonder "
        "(discovery, magic, sunlit dreams), mystery (the strange thing appears), tension "
        "(consequences piling up), sorrow (loss, longing), warm (the ending, hope), playful "
        "(light bedtime moments), or none (silence: the voice and ambience carry it)",
    )

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
    shots: list[Shot] = Field(min_length=MIN_SHOTS, max_length=MAX_SHOTS)
    sound: Sound
    fade_out: FadeOut = Field(
        default="black",  # storyboards written before fade-outs have none
        description="How the last frame leaves the screen (the video always opens out of black): "
        "black (a quiet night, a sorrowful or open ending), white (a dream, a memory, waking "
        "up), glow (warm magic: a jar, a lantern, the moon bell lingering), or sunray (a "
        "morning, hope, sunlight breaking through)",
    )

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

    @field_validator(
        "youtube_description", "tiktok_caption", "instagram_caption", "facebook_caption"
    )
    @classmethod
    def _no_disclosure_line(cls, v: str) -> str:
        # Post copy relies on each platform's AI label; no disclosure line anywhere.
        v = re.sub(
            r"[ \t]*(Story and direction by [^.\n]*\.|Illustrated with AI-assisted artwork\.?)",
            "",
            v,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\n{3,}", "\n\n", v).strip()


class CanonNote(_Strict):
    """What this episode adds to the story so far, read by every later episode's writers."""

    summary: str = Field(description="Two or three sentences: what happened, to whom")
    changes: list[str] = Field(
        description="What is now true in the world: objects someone now has, places visited, "
        "who has glimpsed whom. Facts later episodes must not contradict"
    )
    open_threads: list[str] = Field(
        description="Questions left open that a later episode could pick up"
    )
    closes: list[str] = Field(
        default_factory=list,  # notes written before the open-threads list have none
        description="Ids of earlier open threads (e.g. T12.1) this episode answers. A thread it "
        "only touches stays open",
    )


class Package(_Strict):
    title: str = Field(max_length=60, description="Simple premise + unanswered question")
    alt_titles: list[str] = Field(min_length=2, max_length=3, description="For A/B tests")
    thumbnail: Thumbnail
    platforms: PlatformCopy
    comment_prompt: str = Field(description="One gentle question that extends the story")
    long_form_path: str = Field(description="Which long-form collection this story belongs in")
    canon: CanonNote


# ============================================================ critic


class CriticIssue(_Strict):
    area: Literal["story", "script", "visual", "sound", "package", "policy"]
    rule: int = Field(ge=0, le=14, description="Story bible rule: 1-7 core, 8-14 craft, 0 for none")
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

        check_speakers(self.card.mode, self.script)
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
