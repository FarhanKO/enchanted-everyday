"""Stage 2: turn today's candidates into scored story cards, drop near-repeats, pick one.

The story architect writes one card per discovery candidate (plus original premises when the slate
runs low). Each card is embedded locally and compared with every story already picked or
published, or turned down by the owner; anything too close is marked a duplicate. The best
remaining card is picked, and the next two are kept as backups for the critic stage and /redo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from engine.canon import load as load_canon
from engine.canon import next_lead, recent_mix
from engine.db.models import DiscoveryItem, Idea
from engine.embeddings import get_embedder
from engine.llm.schemas import StoryCard
from engine.notify import alert
from engine.stages.base import StageContext
from engine.studio import Candidate, Studio

log = logging.getLogger(__name__)

# Cosine similarity of title + premise (all-MiniLM-L6-v2). Distinct slate stories top out at 0.63;
# close retellings of the same story score ~0.8 (measured 2026-10-09). Retune in week 2.
DUPLICATE_SIMILARITY = 0.75
BACKUPS = 2
MIN_CARDS = 1 + BACKUPS  # top up with original premises below this
RECENT_TITLES = 30
USED = ("picked", "published")  # ideas that count as already told
OWNER_REJECTED = "owner_rejected"  # turned down with /redo (engine/redo.py); never offered again
NOT_AGAIN = (*USED, OWNER_REJECTED)


@dataclass
class Scored:
    ref: str
    slate_id: str | None
    card: StoryCard
    similar_to: str | None = None  # title of the past story it repeats
    similarity: float | None = None
    status: str = "candidate"


def embed_text(card: StoryCard) -> str:
    return f"{card.title}. {card.premise}"


def assign(scored: list[Scored]) -> list[Scored]:
    """Mark duplicates, then pick the top-scoring card and the next BACKUPS as backups."""
    for s in scored:
        if s.similarity is not None and s.similarity >= DUPLICATE_SIMILARITY:
            s.status = "duplicate"
    fresh = sorted(
        (s for s in scored if s.status != "duplicate"),
        key=lambda s: s.card.total_score,
        reverse=True,
    )
    for rank, s in enumerate(fresh):
        s.status = "picked" if rank == 0 else "backup" if rank <= BACKUPS else "candidate"
    return scored


def _candidates(ctx: StageContext) -> list[Candidate]:
    items = ctx.session.scalars(
        select(DiscoveryItem).where(DiscoveryItem.run_id == ctx.run_id).order_by(DiscoveryItem.id)
    ).all()
    return [
        Candidate(
            ref=i.ref,
            title=i.title,
            premise=i.premise,
            universe=(i.meta or {}).get("universe", "urban"),
            recurring=(i.meta or {}).get("recurring", []),
        )
        for i in items
    ]


def _nearest(ctx: StageContext, vector: list[float]) -> tuple[str, float] | None:
    distance = Idea.embedding.cosine_distance(vector)
    row = ctx.session.execute(
        select(Idea.title, distance)
        .where(Idea.status.in_(NOT_AGAIN), Idea.embedding.is_not(None), Idea.run_id != ctx.run_id)
        .order_by(distance)
        .limit(1)
    ).first()
    return (row[0], 1 - row[1]) if row else None


def _embed(ctx: StageContext, cards: list[Scored]) -> list[list[float]] | None:
    try:
        return get_embedder(ctx.settings).embed([embed_text(s.card) for s in cards])
    except Exception as e:
        # Slate ids still stop exact repeats; don't lose the day over the safety net.
        log.exception("embedding failed; skipping the duplicate check")
        alert(f"Duplicate-story check skipped on {ctx.run_date}: {e!r}"[:500], ctx.settings)
        return None


def run(ctx: StageContext) -> dict:
    candidates = _candidates(ctx)
    universe = ctx.outputs.get("discovery", {}).get("preferred_universe", "urban")
    recent = ctx.session.scalars(
        select(Idea.title)
        .where(Idea.status.in_(USED))
        .order_by(Idea.created_at.desc())
        .limit(RECENT_TITLES)
    ).all()

    brand_dir = Path(ctx.settings.brand_dir)
    studio = Studio(ctx.llm_json, brand_dir)
    cards = studio.cards(
        candidates,
        new=max(0, MIN_CARDS - len(candidates)),
        universe=universe,
        recent_titles=recent,
        canon=load_canon(ctx.session, brand_dir),
        mix=recent_mix(ctx.session),
        lead=next_lead(ctx.session),
    )

    by_ref = {c.ref: c for c in candidates}
    scored = []
    for cc in cards:
        source = by_ref.get(cc.ref)
        card = cc.card
        if source and card.universe != source.universe:
            # the slate decides the universe: discovery balances the mix on it
            card = card.model_copy(update={"universe": source.universe})
        scored.append(Scored(ref=cc.ref, slate_id=source.ref if source else None, card=card))

    vectors = _embed(ctx, scored)
    if vectors:
        for s, v in zip(scored, vectors, strict=True):
            if hit := _nearest(ctx, v):
                s.similar_to, s.similarity = hit
    assign(scored)

    rows = []
    for i, s in enumerate(scored):
        idea = Idea(
            run_id=ctx.run_id,
            slate_id=s.slate_id,
            title=s.card.title,
            premise=s.card.premise,
            universe=s.card.universe,
            card=s.card.model_dump(mode="json"),
            total_score=s.card.total_score,
            embedding=vectors[i] if vectors else None,
            status=s.status,
        )
        ctx.session.add(idea)
        rows.append(idea)
    ctx.session.flush()

    picked = [r.id for r, s in zip(rows, scored, strict=True) if s.status == "picked"]
    if not picked:
        dupes = [f"{s.card.title} ~ {s.similar_to}" for s in scored]
        raise RuntimeError(f"every story card repeats a past story: {dupes}")

    ranked = sorted(
        zip(rows, scored, strict=True), key=lambda rs: rs[1].card.total_score, reverse=True
    )
    return {
        "idea_id": picked[0],
        "backups": [r.id for r, s in ranked if s.status == "backup"],
        "cards": len(scored),
        "duplicates": [
            {"title": s.card.title, "similar_to": s.similar_to, "similarity": round(sim, 3)}
            for s in scored
            if s.status == "duplicate" and (sim := s.similarity) is not None
        ],
        "dedupe": "on" if vectors else "skipped",
    }
