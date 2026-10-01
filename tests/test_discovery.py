from pathlib import Path

import pytest

from engine.stages.discovery import (
    OTHER_COUNT,
    PREFERRED_COUNT,
    choose,
    load_slate,
    pick_lane,
)

SLATE = Path(__file__).parent.parent / "brand" / "slate.toml"


def test_slate_loads_and_is_balanced_enough():
    slate = load_slate(SLATE)
    assert len(slate) >= 20
    assert {s.lane for s in slate} == {"dark_urban", "cozy_bedtime"}


@pytest.mark.parametrize(
    ("recent", "expected"),
    [
        ([], "dark_urban"),
        (["dark_urban"] * 7 + ["cozy_bedtime"] * 3, "dark_urban"),  # on target: tie -> larger lane
        (["dark_urban"] * 10, "cozy_bedtime"),
        (["cozy_bedtime"] * 5, "dark_urban"),
    ],
)
def test_pick_lane_keeps_the_70_30_mix(recent, expected):
    assert pick_lane(recent) == expected


def test_choose_skips_used_and_mixes_lanes():
    slate = load_slate(SLATE)
    used = {"s000", "s001"}
    picked = choose(slate, used, "dark_urban")
    assert not {s.id for s in picked} & used
    assert [s.lane for s in picked] == ["dark_urban"] * PREFERRED_COUNT + [
        "cozy_bedtime"
    ] * OTHER_COUNT


def test_choose_returns_nothing_when_exhausted():
    slate = load_slate(SLATE)
    assert choose(slate, {s.id for s in slate}, "dark_urban") == []


def test_duplicate_slate_ids_rejected(tmp_path):
    bad = tmp_path / "slate.toml"
    entry = 'id = "x"\ntitle = "t"\npremise = "p"\nlane = "dark_urban"\npillar = "strange_thing"\n'
    bad.write_text(f"[[story]]\n{entry}\n[[story]]\n{entry}", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_slate(bad)
