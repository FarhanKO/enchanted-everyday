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
    fann = next(c for c in board.characters if c.id == "fann")
    for shot in board.shots:
        prompt = prompting.image_prompt(shot, board).prompt
        assert (fann.descriptor in prompt) == ("fann" in shot.characters)
        assert prompting.style()["style"][shot.pole] in prompt


def test_cast_descriptor_overrides_the_storyboard():
    board = _episode().storyboard.model_copy(deep=True)
    fann = next(c for c in board.characters if c.id == "fann")
    fann.descriptor = (
        "Fann, paraphrased by an agent: a man with a different coat and different hair"
    )
    shot = next(s for s in board.shots if "fann" in s.characters)
    prompt = prompting.image_prompt(shot, board).prompt
    assert prompting.cast()["fann"]["descriptor"] in prompt
    assert "paraphrased" not in prompt


def test_cast_references_exist_and_golden_episode_matches_cast():
    for cid, entry in prompting.cast().items():
        for ref in entry["references"]:
            assert (prompting.BRAND_DIR / ref).is_file(), f"{cid}: missing {ref}"
    for c in _episode().storyboard.characters:
        if c.id in prompting.cast():
            assert c.descriptor == prompting.cast()[c.id]["descriptor"]


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
    assert "They say a shop buys dreams at midnight." in md
