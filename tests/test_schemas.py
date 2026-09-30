import pytest
from pydantic import ValidationError

from engine.llm.schemas import (
    MAX_WORDS,
    MIN_WORDS,
    CriticReport,
    IdeaList,
    ScriptDraft,
    unsourced_claims,
    word_count,
)

SRC = "https://example.com/article"


def make_script(words_per_beat: int = 30, beats: int = 4, claims=None) -> dict:
    return {
        "hook": "Here is something you did not know about budgets.",
        "beats": [
            {
                "narration": " ".join(["word"] * words_per_beat),
                "visual": "stock: city at night",
                "claims": claims if claims is not None and i == 0 else [],
            }
            for i in range(beats)
        ],
        "captions": {
            "youtube_title": "A title",
            "youtube_description": "desc",
            "instagram": "ig",
            "facebook": "fb",
            "tiktok": "tt",
            "hashtags": ["money", "#tips"],
        },
    }


def test_valid_script_passes():
    s = ScriptDraft.model_validate(make_script(claims=[{"text": "x", "source_url": SRC}]))
    assert MIN_WORDS <= word_count(s.spoken_text) <= MAX_WORDS
    assert s.captions.hashtags == ["#money", "#tips"]
    assert len(s.claims) == 1


@pytest.mark.parametrize("per_beat", [10, 50])
def test_word_count_enforced(per_beat):
    with pytest.raises(ValidationError, match="words"):
        ScriptDraft.model_validate(make_script(words_per_beat=per_beat))


def test_claim_needs_a_real_url():
    with pytest.raises(ValidationError):
        ScriptDraft.model_validate(make_script(claims=[{"text": "x", "source_url": "trust me"}]))


def test_too_few_beats_rejected():
    with pytest.raises(ValidationError):
        ScriptDraft.model_validate(make_script(words_per_beat=60, beats=2))


def test_unsourced_claims_flags_invented_sources():
    s = ScriptDraft.model_validate(
        make_script(
            claims=[
                {"text": "a", "source_url": SRC},
                {"text": "b", "source_url": "https://made-up.example.org/"},
            ]
        )
    )
    bad = unsourced_claims(s, {SRC + "/"})
    assert [c.text for c in bad] == ["b"]


def test_critic_blocking():
    assert not CriticReport(verdict="pass", issues=[]).blocking
    assert CriticReport(verdict="revise").blocking
    assert CriticReport(
        verdict="pass", issues=[{"beat_index": 0, "problem": "unsupported", "severity": "high"}]
    ).blocking


def test_idea_scores_bounded():
    with pytest.raises(ValidationError):
        IdeaList.model_validate(
            {
                "ideas": [
                    {
                        "title": "t",
                        "angle": "a",
                        "fit": 11,
                        "timeliness": 1,
                        "value": 1,
                        "source_urls": [SRC],
                    }
                ]
            }
        )
