"""initial schema: eleven tables + pgvector

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384


def _ts(name: str, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _fk(name: str, target: str) -> sa.Column:
    return sa.Column(name, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_date", sa.Date, nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        _ts("started_at"),
        _ts("finished_at", nullable=True),
        sa.Column("error", sa.Text),
        sa.Column("stages", JSONB, server_default="{}", nullable=False),
        sa.Column("llm_cost_usd", sa.Numeric(10, 4), server_default="0", nullable=False),
    )

    op.create_table(
        "discovery_items",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("run_id", "runs.id"),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("premise", sa.Text, nullable=False),
        sa.Column("meta", JSONB),
        _ts("fetched_at"),
        sa.UniqueConstraint("run_id", "source", "ref"),
    )
    op.create_index("ix_discovery_items_run_id", "discovery_items", ["run_id"])

    op.create_table(
        "ideas",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("run_id", "runs.id"),
        sa.Column("slate_id", sa.String(16)),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("premise", sa.Text, nullable=False),
        sa.Column("universe", sa.String(16), nullable=False),
        sa.Column("card", JSONB, nullable=False),
        sa.Column("total_score", sa.Float, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.Column("status", sa.String(32), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_ideas_run_id", "ideas", ["run_id"])
    op.create_index("ix_ideas_slate_id", "ideas", ["slate_id"])
    # cosine-distance index for the near-duplicate check
    op.execute(
        "CREATE INDEX ix_ideas_embedding_hnsw ON ideas USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "scripts",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("idea_id", "ideas.id"),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("narration", sa.Text, nullable=False),
        sa.Column("script", JSONB, nullable=False),
        sa.Column("storyboard", JSONB),
        sa.Column("package", JSONB),
        sa.Column("critic_report", JSONB),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("idea_id", "version"),
    )
    op.create_index("ix_scripts_idea_id", "scripts", ["idea_id"])

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("script_id", "scripts.id"),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("uri", sa.Text, nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("license", sa.Text, nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("meta", JSONB),
        _ts("created_at"),
    )
    op.create_index("ix_assets_script_id", "assets", ["script_id"])

    op.create_table(
        "renders",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("script_id", "scripts.id"),
        sa.Column("uri", sa.Text, nullable=False),
        sa.Column("duration_s", sa.Float, nullable=False),
        sa.Column("qc_report", JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("ai_generated", sa.Boolean, nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_renders_script_id", "renders", ["script_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("render_id", "renders.id"),
        sa.Column("decision", sa.String(16), nullable=False),
        _ts("decided_at"),
        sa.Column("note", sa.Text),
    )
    op.create_index("ix_approvals_render_id", "approvals", ["render_id"])

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("render_id", "renders.id"),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("external_id", sa.Text),
        sa.Column("url", sa.Text),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("last_error", sa.Text),
        _ts("published_at", nullable=True),
        sa.UniqueConstraint("render_id", "platform"),
    )
    op.create_index("ix_posts_render_id", "posts", ["render_id"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("post_id", "posts.id"),
        sa.Column("horizon", sa.String(8), nullable=False),
        sa.Column("views", sa.Integer),
        sa.Column("likes", sa.Integer),
        sa.Column("comments", sa.Integer),
        sa.Column("shares", sa.Integer),
        sa.Column("saves", sa.Integer),
        sa.Column("avg_view_s", sa.Float),
        _ts("collected_at"),
        sa.UniqueConstraint("post_id", "horizon"),
    )
    op.create_index("ix_metrics_post_id", "metrics", ["post_id"])

    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("run_id", "runs.id"),
        sa.Column("arm", sa.String(64), nullable=False),
        sa.Column("reward", sa.Float),
        sa.Column("model_version", sa.String(64)),
        _ts("created_at"),
    )
    op.create_index("ix_experiments_run_id", "experiments", ["run_id"])

    op.create_table(
        "bible_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("descriptor", sa.Text, nullable=False),
        sa.Column("reference_uris", JSONB, server_default="[]", nullable=False),
        sa.Column("recurring", sa.Boolean, nullable=False),
        sa.Column("notes", sa.Text),
        _ts("created_at"),
        _ts("updated_at"),
    )


def downgrade() -> None:
    for table in (
        "bible_entries",
        "experiments",
        "metrics",
        "posts",
        "approvals",
        "renders",
        "assets",
        "scripts",
        "ideas",
        "discovery_items",
        "runs",
    ):
        op.drop_table(table)
