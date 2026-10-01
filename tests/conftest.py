from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from engine.config import Settings

ROOT = Path(__file__).parent.parent
GOLDEN_EPISODE = ROOT / "stories" / "s000-the-man-who-sold-his-dreams" / "episode.json"


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests never read a developer's real .env
    return Settings(_env_file=None, daily_spend_cap_usd=1.0)


@pytest.fixture
def db_engine():
    """Fresh, migrated Postgres+pgvector schema. Skipped unless TEST_DATABASE_URL is set (CI)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")

    from alembic import command
    from alembic.config import Config

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))

    cfg = Config()
    cfg.set_main_option("script_location", "engine/db/migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    yield engine
    engine.dispose()
