"""The ten tables. Every post traces back to its render, script, prompt version, idea and trends.

Status columns are plain strings (not DB enums) so adding a state is a code change, not a migration.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    """One row per daily run. `stages` holds per-stage state so a retry resumes, not restarts."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    stages: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    llm_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("0"), server_default="0"
    )


class DiscoveryItem(Base):
    """Premise candidates for a run: slate entries now; comments and seasonal moods later."""

    __tablename__ = "discovery_items"
    __table_args__ = (UniqueConstraint("run_id", "source", "ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))  # slate | comment | seasonal | manual
    ref: Mapped[str] = mapped_column(String(64))  # slate id, comment id, ...
    title: Mapped[str] = mapped_column(Text)
    premise: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column()
    fetched_at: Mapped[datetime] = _now()


class Idea(Base):
    __tablename__ = "ideas"
    __table_args__ = (
        # cosine-distance index for the near-duplicate check
        Index(
            "ix_ideas_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    slate_id: Mapped[str | None] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text)
    premise: Mapped[str] = mapped_column(Text)
    universe: Mapped[str] = mapped_column(String(16))  # urban | emotional | bedtime
    card: Mapped[dict[str, Any]] = mapped_column()  # the full StoryCard
    total_score: Mapped[float] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    status: Mapped[str] = mapped_column(String(32), default="candidate")  # picked | backup | ...
    created_at: Mapped[datetime] = _now()


class Script(Base):
    __tablename__ = "scripts"
    __table_args__ = (UniqueConstraint("idea_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    narration: Mapped[str] = mapped_column(Text)  # spoken text, for search and dedupe
    script: Mapped[dict[str, Any]] = mapped_column()  # Script contract
    storyboard: Mapped[dict[str, Any] | None] = mapped_column()  # Storyboard contract
    package: Mapped[dict[str, Any] | None] = mapped_column()  # Package contract
    critic_report: Mapped[dict[str, Any] | None] = mapped_column()
    prompt_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = _now()


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    # voice | timestamps | image | clip | music | sfx | thumbnail
    kind: Mapped[str] = mapped_column(String(32))
    uri: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64))
    license: Mapped[str] = mapped_column(Text)  # required: no asset without a recorded license
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    meta: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = _now()


class Render(Base):
    __tablename__ = "renders"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    uri: Mapped[str] = mapped_column(Text)
    duration_s: Mapped[float] = mapped_column(Float)
    qc_report: Mapped[dict[str, Any]] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="qc_pending")
    ai_generated: Mapped[bool] = mapped_column(default=True)  # drives platform disclosure flags
    created_at: Mapped[datetime] = _now()


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    render_id: Mapped[int] = mapped_column(ForeignKey("renders.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(16))  # approve | redo | skip | timeout
    decided_at: Mapped[datetime] = _now()
    note: Mapped[str | None] = mapped_column(Text)


class Post(Base):
    """One row per platform post. Unique (render_id, platform) makes publishing idempotent."""

    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("render_id", "platform"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    render_id: Mapped[int] = mapped_column(ForeignKey("renders.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16))  # youtube | instagram | facebook | tiktok
    external_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (UniqueConstraint("post_id", "horizon"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    horizon: Mapped[str] = mapped_column(String(8))  # 24h | 7d
    views: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    saves: Mapped[int | None] = mapped_column(Integer)
    avg_view_s: Mapped[float | None] = mapped_column(Float)
    collected_at: Mapped[datetime] = _now()


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    arm: Mapped[str] = mapped_column(String(64))
    reward: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class BibleEntry(Base):
    """The persistent universe: recurring characters, places and props with locked descriptors and
    approved reference images, so the Shopkeeper looks the same in episode 1 and episode 200."""

    __tablename__ = "bible_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # character | location | prop
    name: Mapped[str] = mapped_column(Text)
    descriptor: Mapped[str] = mapped_column(Text)
    reference_uris: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    recurring: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
