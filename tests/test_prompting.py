import json

from engine import prompting
from engine.episode_doc import to_markdown
from engine.llm.schemas import Episode
from tests.conftest import GOLDEN_EPISODE


def _episode() -> Episode:
    return Episode.model_validate(json.loads(GOLDEN_EPISODE.read_text(encoding="utf-8")))


def test_locked_descriptors_are_inserted_verbatim():
    ep = _episode()
    board = ep.storyboard
    theo = next(c for c in board.characters if c.id == "theo")
    for shot in board.shots:
        prompt = prompting.image_prompt(shot, board).prompt
        assert (theo.descriptor in prompt) == ("theo" in shot.characters)
        assert prompting.style()["style"][shot.pole] in prompt


def test_night_and_day_poles_use_their_own_style():
    ep = _episode()
    by_pole = {s.pole: s for s in ep.storyboard.shots}
    night = prompting.image_prompt(by_pole["night"], ep.storyboard).prompt
    day = prompting.image_prompt(by_pole["day"], ep.storyboard).prompt
    assert "midnight-blue" in night and "cobalt-blue sky" not in night
    assert "cobalt-blue sky" in day


def test_video_prompt_has_camera_and_suffix():
    shot = _episode().storyboard.shots[0]
    vp = prompting.video_prompt(shot)
    assert vp.startswith("very slow push-in")
    assert vp.endswith("painterly texture preserved")


def test_markdown_package_has_all_eleven_sections():
    md = to_markdown(_episode())
    for n in range(1, 12):
        assert f"## {n}. " in md
    assert "Theo sold his first dream" in md
