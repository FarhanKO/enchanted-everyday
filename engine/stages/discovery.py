"""Stage 1: gather premise candidates for today's story.

Sources now: the slate (brand/slate.toml), filtered to stories not yet used and balanced to the
brand's 70/30 mix of dark urban tales to cozy bedtime fantasy. Audience comments and seasonal
moods join in Phase 4. The idea stage expands these into scored story cards.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from engine.db.models import DiscoveryItem, Idea
from engine.stages.base import StageContext

log = logging.getLogger(__name__)

LANE_TARGET = {"dark_urban": 0.7, "cozy_bedtime": 0.3}
RECENT_WINDOW = 10  # how many past picks the mix is balanced over
PREFERRED_COUNT = 4  # candidates from the lane that is behind its target
OTHER_COUNT = 1  # plus a wildcard from the other lane


@dataclass(frozen=True)
class SlateStory:
    id: str
    title: str
    premise: str
    lane: str
    pillar: str
    recurring: list[str] = field(default_factory=list)


def load_slate(path: Path) -> list[SlateStory]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    stories = [SlateStory(**s) for s in data.get("story", [])]
    ids = [s.id for s in stories]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate slate ids in {path}")
    bad = [s.id for s in stories if s.lane not in LANE_TARGET]
    if bad:
        raise ValueError(f"unknown lane in slate entries {bad}")
    return stories


def pick_lane(recent_lanes: list[str]) -> str:
    """The lane furthest below its target share over the recent window."""
    window = recent_lanes[-RECENT_WINDOW:]
    if not window:
        return max(LANE_TARGET, key=LANE_TARGET.get)
    share = {lane: window.count(lane) / len(window) for lane in LANE_TARGET}
    return max(LANE_TARGET, key=lambda lane: LANE_TARGET[lane] - share[lane])


def choose(slate: list[SlateStory], used: set[str], lane: str) -> list[SlateStory]:
    fresh = [s for s in slate if s.id not in used]
    preferred = [s for s in fresh if s.lane == lane][:PREFERRED_COUNT]
    other = [s for s in fresh if s.lane != lane][:OTHER_COUNT]
    return preferred + other


def run(ctx: StageContext) -> dict:
    slate = load_slate(Path(ctx.settings.brand_dir) / "slate.toml")

    picked = ctx.session.execute(
        select(Idea.slate_id, Idea.lane)
        .where(Idea.status.in_(("picked", "published")))
        .order_by(Idea.created_at)
    ).all()
    used = {slate_id for slate_id, _ in picked if slate_id}
    lane = pick_lane([lane for _, lane in picked])
    candidates = choose(slate, used, lane)

    if candidates:
        ctx.session.execute(
            insert(DiscoveryItem)
            .values(
                [
                    {
                        "run_id": ctx.run_id,
                        "source": "slate",
                        "ref": s.id,
                        "title": s.title,
                        "premise": s.premise,
                        "meta": {"lane": s.lane, "pillar": s.pillar, "recurring": s.recurring},
                    }
                    for s in candidates
                ]
            )
            .on_conflict_do_nothing(index_elements=["run_id", "source", "ref"])
        )
    else:
        # Not fatal: the idea stage writes fresh premises from the bible when the slate runs dry.
        log.warning("slate exhausted", extra={"used": len(used), "slate": len(slate)})

    return {
        "candidates": [s.id for s in candidates],
        "preferred_lane": lane,
        "slate_remaining": len(slate) - len(used),
    }
