"""The episode contracts, exercised against the golden episode and targeted breakages of it."""

import copy
import json

import pytest
from pydantic import ValidationError

from engine.llm.schemas import (
    BEAT_ORDER,
    MAX_DURATION_S,
    MIN_DURATION_S,
    CriticReport,
    Episode,
    Script,
    Storyboard,
    StoryCards,
    api_schema,
)
from tests.conftest import GOLDEN_EPISODE


@pytest.fixture
def golden() -> dict:
    return json.loads(GOLDEN_EPISODE.read_text(encoding="utf-8"))


def test_golden_episode_is_valid(golden):
    ep = Episode.model_validate(golden)
    assert [b.name for b in ep.script.beats] == list(BEAT_ORDER)
    assert MIN_DURATION_S <= ep.script.estimated_duration_s <= MAX_DURATION_S
    assert ep.package.platforms.hashtags[0] == "#shortstory"  # normalised


def test_beats_must_follow_the_formula(golden):
    beats = golden["script"]["beats"]
    beats[1], beats[2] = beats[2], beats[1]
    with pytest.raises(ValidationError, match="beats must be"):
        Script.model_validate(golden["script"])


def test_long_hook_rejected(golden):
    golden["script"]["beats"][0]["lines"][0]["text"] = " ".join(["word"] * 13)
    with pytest.raises(ValidationError, match="hook"):
        Script.model_validate(golden["script"])


def test_script_too_long_for_short_form(golden):
    golden["script"]["beats"][3]["lines"][0]["text"] += " and" * 40
    with pytest.raises(ValidationError):
        Script.model_validate(golden["script"])


def test_shot_gap_rejected(golden):
    golden["storyboard"]["shots"][3]["start_s"] += 2
    with pytest.raises(ValidationError, match="gap/overlap"):
        Storyboard.model_validate(golden["storyboard"])


def test_unknown_character_rejected(golden):
    golden["storyboard"]["shots"][0]["characters"].append("ghost")
    with pytest.raises(ValidationError, match="unknown characters"):
        Storyboard.model_validate(golden["storyboard"])


def test_ai_clip_budget(golden):
    for shot in golden["storyboard"]["shots"][:3]:
        shot["motion"] = "ai_clip"
    with pytest.raises(ValidationError, match="ai_clip"):
        Storyboard.model_validate(golden["storyboard"])


@pytest.mark.parametrize("term", ["in the style of Studio Ghibli", "Makoto Shinkai lighting"])
def test_protected_styles_rejected(golden, term):
    golden["storyboard"]["shots"][0]["image_prompt"] += f", {term}"
    with pytest.raises(ValidationError, match="protected style"):
        Storyboard.model_validate(golden["storyboard"])


def test_thumbnail_text_limit(golden):
    golden["package"]["thumbnail"]["text"] = "THE LAST DREAM HE SOLD"
    with pytest.raises(ValidationError, match="4 words"):
        Episode.model_validate(golden)


def test_storyboard_must_match_narration_length(golden):
    shots = golden["storyboard"]["shots"]
    shots[-1]["duration_s"] = 15
    shots[-2]["duration_s"] = 15
    shots[-1]["start_s"] = shots[-2]["start_s"] + 15
    with pytest.raises(ValidationError, match="narration needs"):
        Episode.model_validate(golden)


def test_critic_blocking():
    assert not CriticReport(verdict="pass", issues=[]).blocking
    assert CriticReport(verdict="revise", issues=[]).blocking
    issue = {
        "area": "story",
        "rule": 6,
        "problem": "moral pasted on",
        "fix": "cut it",
        "severity": "high",
    }
    assert CriticReport(verdict="pass", issues=[issue]).blocking


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


@pytest.mark.parametrize("model", [StoryCards, Script, Storyboard, Episode, CriticReport])
def test_api_schema_is_structured_output_safe(model):
    schema = api_schema(model)
    unsupported = {
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
    }
    for node in _walk(schema):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        assert not (unsupported & set(node) - {"properties"})


def test_api_schema_keeps_fields_named_like_keywords():
    # StoryCard has a field literally called "title"; stripping JSON-schema titles must not drop it
    card = api_schema(StoryCards)["$defs"]["StoryCard"]
    assert "title" in card["properties"]


def test_api_schema_does_not_mutate_between_calls():
    first = copy.deepcopy(api_schema(Episode))
    assert api_schema(Episode) == first
