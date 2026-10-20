"""The studio's agents, repair loop and script revision, against scripted answers."""

import copy
from pathlib import Path

import pytest

from engine.canon import Canon, OpenThread
from engine.llm.client import LLMOutputInvalid
from engine.llm.schemas import CriticReport, Script, Storyboard, StoryCard
from engine.studio import MAX_ATTEMPTS, Candidate, Studio, revision_notes
from tests.fakes import FakeCall, golden, report

BRAND = Path(__file__).parent.parent / "brand"


@pytest.fixture
def ep():
    return golden()


def studio(*answers) -> tuple[Studio, FakeCall]:
    call = FakeCall(*answers)
    return Studio(call, BRAND), call


def test_broken_answer_is_repaired_with_its_errors(ep):
    bad = copy.deepcopy(ep["script"])
    bad["beats"][0]["lines"][0]["text"] = "one two three four five six seven eight nine ten"
    s, call = studio(bad, ep["script"])

    out = s.script(StoryCard.model_validate(ep["card"]))

    assert out == Script.model_validate(ep["script"])
    assert s.repairs == 1
    retry = call.prompts[1]["user"]
    assert "<previous_answer>" in retry and "one two three" in retry
    assert "3-second rule" in retry  # the validation error is passed back
    assert retry.startswith(call.prompts[0]["user"])  # same task, plus the repair


def test_gives_up_after_max_attempts(ep):
    bad = copy.deepcopy(ep["script"])
    bad["beats"].pop()
    s, call = studio(*[bad] * MAX_ATTEMPTS)
    with pytest.raises(LLMOutputInvalid, match="beats must be"):
        s.script(StoryCard.model_validate(ep["card"]))
    assert len(call.prompts) == MAX_ATTEMPTS


def test_every_call_names_its_agent_role(ep):
    s, call = studio(ep["script"], report("pass"))
    card = StoryCard.model_validate(ep["card"])
    s.review(card, s.script(card))
    assert [p["role"] for p in call.prompts] == ["script_writer", "critic"]


def test_storyboard_must_match_the_narration_length(ep):
    script = copy.deepcopy(ep["script"])
    for beat in script["beats"]:
        for line in beat["lines"]:
            line["pause_after_s"] = 0  # ~74 s of narration vs an 87 s storyboard
    s, call = studio(ep["storyboard"], ep["storyboard"], ep["storyboard"])
    with pytest.raises(LLMOutputInvalid, match="retime the shots"):
        s.storyboard(StoryCard.model_validate(ep["card"]), Script.model_validate(script))
    assert "must end between" in call.prompts[0]["user"]


def test_package_must_fit_the_storyboard(ep):
    bad = copy.deepcopy(ep["package"])
    bad["thumbnail"]["location"] = "nowhere"
    s, _ = studio(bad, ep["package"])
    out = s.package(
        StoryCard.model_validate(ep["card"]),
        Script.model_validate(ep["script"]),
        Storyboard.model_validate(ep["storyboard"]),
    )
    assert out.thumbnail.location == "midnight_shop"
    assert s.repairs == 1


def test_cards_need_one_per_candidate(ep):
    one = {"cards": [{"ref": "s001", "card": ep["card"]}]}
    both = {"cards": [{"ref": "s001", "card": ep["card"]}, {"ref": "s002", "card": ep["card"]}]}
    s, call = studio(one, both)
    cands = [Candidate("s001", "A", "a", "urban"), Candidate("s002", "B", "b", "emotional")]
    out = s.cards(cands, recent_titles=["The Man Who Sold His Dreams"])
    assert [c.ref for c in out] == ["s001", "s002"]
    first = call.prompts[0]["user"]
    assert "- ref s001 (urban): A. a" in first
    assert "The Man Who Sold His Dreams" in first


def test_new_cards_requested_when_the_slate_is_low(ep):
    s, call = studio({"cards": [{"ref": "new", "card": ep["card"]}] * 3})
    assert len(s.cards([], new=3, universe="bedtime")) == 3
    assert "3 new, original premise(s) in the bedtime universe" in call.prompts[0]["user"]


@pytest.mark.parametrize(
    ("issues", "kept"),
    [
        ([("script", "high"), ("story", "low")], ["script"]),  # high issues take priority
        ([("script", "low"), ("story", "low")], ["script", "story"]),  # else all of them
        ([], []),
    ],
)
def test_revision_notes(issues, kept):
    notes = revision_notes(CriticReport.model_validate(report("revise", *issues)))
    assert [n.area for n in notes] == kept


def test_revision_sees_the_last_draft_and_the_notes(ep):
    s, call = studio(ep["script"])
    card = StoryCard.model_validate(ep["card"])
    critique = CriticReport.model_validate(report("revise", ("script", "high"), ("story", "low")))

    s.revise_script(card, Script.model_validate(ep["script"]), critique)

    user = call.prompts[0]["user"]
    assert "<previous_draft>" in user and "Revise your previous draft" in user
    assert "script problem" in user and "story problem" not in user


def test_owner_notes_reach_the_writer_and_the_critic(ep):
    s, call = studio(ep["script"], report("pass"), ep["script"])
    card = StoryCard.model_validate(ep["card"])
    draft = Script.model_validate(ep["script"])
    notes = ["less sad", "keep it short"]

    s.script(card, owner_notes=notes)
    s.review(card, draft, notes)
    s.revise_script(card, draft, CriticReport.model_validate(report("revise")), notes)

    for prompt in call.prompts:
        assert "<owner_notes>\n- less sad\n- keep it short\n</owner_notes>" in prompt["user"]
    assert "Check that this script answers them" in call.prompts[1]["user"]


def test_no_owner_notes_no_section(ep):
    s, call = studio(ep["script"])
    s.script(StoryCard.model_validate(ep["card"]))
    assert "owner_notes" not in call.prompts[0]["user"]


def test_review_sees_only_the_story(ep):
    s, call = studio(report("pass"))
    s.review(StoryCard.model_validate(ep["card"]), Script.model_validate(ep["script"]))
    user, system = call.prompts[0]["user"], call.prompts[0]["system"]
    assert "<script>" in user and "<storyboard>" not in user
    assert system.startswith("# Role: critic")
    assert "<production_style>" not in system  # the critic doesn't need the visual rulebook


def test_a_script_that_breaks_its_mode_is_repaired(ep):
    card = StoryCard.model_validate({**ep["card"], "mode": "mixed"})
    narrated = copy.deepcopy(ep["script"])
    for beat in narrated["beats"]:
        for line in beat["lines"]:
            line["speaker"] = "narrator"
    s, call = studio(narrated, ep["script"])  # first answer: narrator only

    out = s.script(card)

    assert out.lines[0].speaker == "narrator" and "fann" in {line.speaker for line in out.lines}
    assert s.repairs == 1
    assert "mode is mixed" in call.prompts[1]["user"]


def test_story_so_far_reaches_every_story_agent(ep):
    canon = Canon(episodes=["The Man Who Sold His Dreams: Fann kept his oldest dream."])
    card = StoryCard.model_validate(ep["card"])
    draft = Script.model_validate(ep["script"])
    cards = {"cards": [{"ref": "a", "card": ep["card"]}]}
    s, call = studio(cards, ep["script"], report("pass"))

    s.cards([Candidate("a", "t", "p", "urban")], canon=canon, mix="Last 3 picks: ...")
    s.script(card, canon=canon)
    s.review(card, draft, canon=canon)

    for prompt in call.prompts:
        assert "<story_so_far>\n- The Man Who Sold His Dreams" in prompt["user"]
    assert "<recent_mix>" in call.prompts[0]["user"]


THREAD = OpenThread("T3.1", "The Lamp That Kept Time", "Who wound the lamp?")


def _canon(next_step: str | None = "D2") -> Canon:
    told = 'Told so far: D1 "Three falling notes" in "Kettle".'
    today = f"Next step: {next_step}." if next_step else "The thread moved in the latest pick."
    return Canon(
        threads=[THREAD],
        dreams=f"{told}\n{today}",
        next_step=next_step,
        thread_ids=frozenset({THREAD.id}),
    )


def _cards(ep, **card):
    return {"cards": [{"ref": "a", "card": {**ep["card"], **card}}]}


def test_open_threads_and_the_dreams_thread_reach_the_architect(ep):
    s, call = studio(_cards(ep, advances_dreams_thread=False, dreams_step=""))
    s.cards([Candidate("a", "t", "p", "urban")], canon=_canon())
    user = call.prompts[0]["user"]
    assert "<open_threads>\n- T3.1 (The Lamp That Kept Time): Who wound the lamp?" in user
    assert "<dreams_thread_so_far>\nTold so far: D1" in user
    assert "<story_so_far>" not in user  # empty sections are left out
    assert "<dreams_thread>" in call.prompts[0]["system"]  # the season plan itself


def test_a_card_that_moves_the_thread_tells_todays_step(ep):
    s, call = studio(
        _cards(ep, advances_dreams_thread=True, dreams_step="D5"),
        _cards(ep, advances_dreams_thread=True, dreams_step="D2"),
    )
    out = s.cards([Candidate("a", "t", "p", "urban")], canon=_canon("D2"))
    assert out[0].card.dreams_step == "D2"
    assert s.repairs == 1
    assert "tells step D2; got dreams_step 'D5'" in call.prompts[1]["user"]


def test_the_thread_rests_the_day_after_it_moves(ep):
    s, call = studio(
        _cards(ep, advances_dreams_thread=True, dreams_step="D2"),
        _cards(ep, advances_dreams_thread=False, dreams_step=""),
    )
    out = s.cards([Candidate("a", "t", "p", "urban")], canon=_canon(None))
    assert not out[0].card.advances_dreams_thread
    assert "the thread rests today" in call.prompts[1]["user"]


def test_the_packager_closes_only_open_threads(ep):
    def pkg(*closes):
        p = copy.deepcopy(ep["package"])
        p["canon"]["closes"] = list(closes)
        return p

    s, call = studio(pkg("T9.9"), pkg("T3.1"))
    out = s.package(
        StoryCard.model_validate(ep["card"]),
        Script.model_validate(ep["script"]),
        Storyboard.model_validate(ep["storyboard"]),
        _canon(),
    )
    assert out.canon.closes == ["T3.1"]
    assert "<open_threads>\n- T3.1" in call.prompts[0]["user"]
    assert "threads that aren't open: ['T9.9']" in call.prompts[1]["user"]


def test_every_card_takes_todays_lead(ep):
    s, call = studio(_cards(ep, lead="fann"), _cards(ep, lead="tina"))
    out = s.cards([Candidate("a", "t", "p", "urban")], lead=("tina", "Today's lead: tina."))
    assert out[0].card.lead == "tina"
    assert "<lead>\nToday's lead: tina." in call.prompts[0]["user"]
    assert "must have lead 'tina' (see <lead>); got 'fann'" in call.prompts[1]["user"]


def test_the_episode_where_they_meet_is_led_by_both(ep):
    meeting = {"advances_dreams_thread": True, "dreams_step": "D10"}
    s, call = studio(_cards(ep, lead="tina", **meeting), _cards(ep, lead="both", **meeting))
    out = s.cards(
        [Candidate("a", "t", "p", "urban")],
        canon=_canon("D10"),
        lead=("tina", "Today's lead: tina."),
    )
    assert out[0].card.lead == "both"
    assert "must have lead 'both' (it tells D10, where they meet)" in call.prompts[1]["user"]
