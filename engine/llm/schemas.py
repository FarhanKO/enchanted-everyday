"""LLM output contracts.

Each contract has two halves:
- a JSON schema sent to the API as `output_config.format`, so the model can only return that shape;
- a Pydantic model that re-validates the result and enforces the rules a schema can't express
  (word counts, a source on every claim, sources limited to what we actually fetched).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

MIN_WORDS, MAX_WORDS = 110, 150
PLATFORMS = ("youtube", "instagram", "facebook", "tiktok")


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


_STR = {"type": "string"}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


# ---------------------------------------------------------------- script

SCRIPT_JSON_SCHEMA = _obj(
    {
        "hook": _STR,
        "beats": _arr(
            _obj(
                {
                    "narration": _STR,
                    "visual": _STR,
                    "claims": _arr(_obj({"text": _STR, "source_url": _STR})),
                }
            )
        ),
        "captions": _obj(
            {
                "youtube_title": _STR,
                "youtube_description": _STR,
                "instagram": _STR,
                "facebook": _STR,
                "tiktok": _STR,
                "hashtags": _arr(_STR),
            }
        ),
    }
)


class Claim(BaseModel):
    text: str = Field(min_length=1)
    source_url: HttpUrl


class Beat(BaseModel):
    narration: str = Field(min_length=1)
    visual: str = Field(min_length=1)  # what's on screen: stock query, card text, or chart spec
    claims: list[Claim] = []


class Captions(BaseModel):
    youtube_title: str = Field(min_length=1, max_length=100)  # YouTube's hard limit
    youtube_description: str
    instagram: str = Field(max_length=2200)
    facebook: str
    tiktok: str = Field(max_length=2200)
    hashtags: list[str] = Field(max_length=8)

    @field_validator("hashtags")
    @classmethod
    def _clean_tags(cls, tags: list[str]) -> list[str]:
        return [t if t.startswith("#") else f"#{t}" for t in (t.strip() for t in tags) if t]


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


class ScriptDraft(BaseModel):
    hook: str = Field(min_length=1)
    beats: list[Beat] = Field(min_length=3, max_length=8)
    captions: Captions

    @property
    def spoken_text(self) -> str:
        return " ".join([self.hook, *(b.narration for b in self.beats)])

    @property
    def claims(self) -> list[Claim]:
        return [c for b in self.beats for c in b.claims]

    @model_validator(mode="after")
    def _length(self) -> ScriptDraft:
        n = word_count(self.spoken_text)
        if not MIN_WORDS <= n <= MAX_WORDS:
            raise ValueError(f"spoken text is {n} words; need {MIN_WORDS}-{MAX_WORDS}")
        return self


def unsourced_claims(script: ScriptDraft, allowed_urls: set[str]) -> list[Claim]:
    """Claims whose source isn't one of the pages we fetched: the model may have invented it."""
    allowed = {_norm(u) for u in allowed_urls}
    return [c for c in script.claims if _norm(str(c.source_url)) not in allowed]


def _norm(url: str) -> str:
    return url.strip().rstrip("/").lower()


# ---------------------------------------------------------------- critic

CRITIC_JSON_SCHEMA = _obj(
    {
        "verdict": {"type": "string", "enum": ["pass", "revise", "reject"]},
        "issues": _arr(
            _obj(
                {
                    "beat_index": {"type": "integer"},
                    "problem": _STR,
                    "severity": {"type": "string", "enum": ["low", "high"]},
                }
            )
        ),
    }
)


class CriticIssue(BaseModel):
    beat_index: int
    problem: str
    severity: Literal["low", "high"]


class CriticReport(BaseModel):
    verdict: Literal["pass", "revise", "reject"]
    issues: list[CriticIssue] = []

    @property
    def blocking(self) -> bool:
        return self.verdict != "pass" or any(i.severity == "high" for i in self.issues)


# ---------------------------------------------------------------- idea scoring

IDEAS_JSON_SCHEMA = _obj(
    {
        "ideas": _arr(
            _obj(
                {
                    "title": _STR,
                    "angle": _STR,
                    "fit": {"type": "number"},
                    "timeliness": {"type": "number"},
                    "value": {"type": "number"},
                    "source_urls": _arr(_STR),
                }
            )
        )
    }
)


class ScoredIdea(BaseModel):
    title: str
    angle: str
    fit: float = Field(ge=0, le=10)
    timeliness: float = Field(ge=0, le=10)
    value: float = Field(ge=0, le=10)
    source_urls: list[HttpUrl] = Field(min_length=1)

    @property
    def score(self) -> float:
        return self.fit + self.timeliness + self.value


class IdeaList(BaseModel):
    ideas: list[ScoredIdea] = Field(min_length=1)
