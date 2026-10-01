from pathlib import Path

import pytest

from engine.stages.discovery import (
    OTHER_COUNT,
    PREFERRED_COUNT,
    UNIVERSE_TARGET,
    choose,
    load_slate,
    rank_universes,
)

SLATE = Path(__file__).parent.parent / "brand" / "slate.toml"


def test_slate_covers_all_three_universes():
    slate = load_slate(SLATE)
    assert len(slate) >= 30
    assert {s.universe for s in slate} == set(UNIVERSE_TARGET)


def test_targets_keep_the_brief_70_30_split():
    assert UNIVERSE_TARGET["urban"] + UNIVERSE_TARGET["emotional"] == pytest.approx(0.7)
    assert sum(UNIVERSE_TARGET.values()) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("recent", "first"),
    [
        ([], "urban"),  # nothing yet: start with the largest share
        (["urban"] * 4 + ["emotional"] * 3 + ["bedtime"] * 3, "urban"),  # on target: tie -> largest
        (["urban"] * 6 + ["emotional"] * 4, "bedtime"),
        (["bedtime"] * 5 + ["urban"] * 5, "emotional"),
    ],
)
def test_rank_universes_favours_the_one_behind(recent, first):
    assert rank_universes(recent)[0] == first


def test_choose_skips_used_and_adds_a_wildcard():
    slate = load_slate(SLATE)
    used = {"s001", "s003"}
    ranked = ["urban", "emotional", "bedtime"]
    picked = choose(slate, used, ranked)
    assert not {s.id for s in picked} & used
    assert [s.universe for s in picked] == ["urban"] * PREFERRED_COUNT + ["emotional"] * OTHER_COUNT


def test_wildcard_falls_through_when_a_universe_is_exhausted():
    slate = load_slate(SLATE)
    used = {s.id for s in slate if s.universe == "emotional"}
    picked = choose(slate, used, ["urban", "emotional", "bedtime"])
    assert picked[-1].universe == "bedtime"


def test_choose_returns_nothing_when_exhausted():
    slate = load_slate(SLATE)
    assert choose(slate, {s.id for s in slate}, ["urban", "emotional", "bedtime"]) == []


def test_duplicate_slate_ids_rejected(tmp_path):
    bad = tmp_path / "slate.toml"
    entry = 'id = "x"\ntitle = "t"\npremise = "p"\nuniverse = "urban"\n'
    bad.write_text(f"[[story]]\n{entry}\n[[story]]\n{entry}", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_slate(bad)
