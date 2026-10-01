"""Stage 1: gather premise candidates for today's story.

Sources now: the slate (brand/slate.toml), filtered to stories not yet used and balanced across
the three universes (urban, emotional, bedtime). Audience comments and seasonal moods join in
Phase 4. The idea stage expands these into scored story cards.
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

# urban + emotional = the brief's 70% darker stories; bedtime = its 30% cozy ones
UNIVERSE_TARGET = {"urban": 0.4, "emotional": 0.3, "bedtime": 0.3}
RECENT_WINDOW = 10  # how many past picks the mix is balanced over
PREFERRED_COUNT = 4  # candidates from the universe furthest behind its target
OTHER_COUNT = 1  # plus a wildcard from the next one


@dataclass(frozen=True)
class SlateStory:
    id: str
    title: str
    premise: str
    universe: str
    recurring: list[str] = field(default_factory=list)


def load_slate(path: Path) -> list[SlateStory]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    stories = [SlateStory(**s) for s in data.get("story", [])]
    ids = [s.id for s in stories]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate slate ids in {path}")
    bad = [s.id for s in stories if s.universe not in UNIVERSE_TARGET]
    if bad:
        raise ValueError(f"unknown universe in slate entries {bad}")
    return stories


def rank_universes(recent: list[str]) -> list[str]:
    """Universes ordered by how far each is below its target share over the recent window."""
    window = recent[-RECENT_WINDOW:]
    share = {u: (window.count(u) / len(window) if window else 0.0) for u in UNIVERSE_TARGET}
    # ties go to the universe with the larger target
    return sorted(
        UNIVERSE_TARGET, key=lambda u: (share[u] - UNIVERSE_TARGET[u], -UNIVERSE_TARGET[u])
    )


def choose(slate: list[SlateStory], used: set[str], ranked: list[str]) -> list[SlateStory]:
    fresh = [s for s in slate if s.id not in used]
    preferred = [s for s in fresh if s.universe == ranked[0]][:PREFERRED_COUNT]
    wildcard = next(([s] for u in ranked[1:] for s in fresh if s.universe == u), [])[:OTHER_COUNT]
    return preferred + wildcard


def run(ctx: StageContext) -> dict:
    slate = load_slate(Path(ctx.settings.brand_dir) / "slate.toml")

    picked = ctx.session.execute(
        select(Idea.slate_id, Idea.universe)
        .where(Idea.status.in_(("picked", "published")))
        .order_by(Idea.created_at)
    ).all()
    used = {slate_id for slate_id, _ in picked if slate_id}
    ranked = rank_universes([universe for _, universe in picked])
    candidates = choose(slate, used, ranked)

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
                        "meta": {"universe": s.universe, "recurring": s.recurring},
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
        "preferred_universe": ranked[0],
        "slate_remaining": len(slate) - len(used),
    }
