from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from engine.config import Settings

ROOT = Path(__file__).parent.parent
GOLDEN_EPISODE = ROOT / "stories" / "s000-the-man-who-sold-his-dreams" / "episode.json"


@pytest.fixture
def settings(tmp_path) -> Settings:
    # _env_file=None: tests never read a developer's real .env; work files go to a temp folder
    return Settings(_env_file=None, daily_spend_cap_usd=1.0, work_dir=str(tmp_path / "work"))


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


@pytest.fixture
def fake_media(monkeypatch, tmp_path, settings):
    """Production's media stages with free, offline stand-ins: fake voice and frames, a render
    that only writes placeholder files, and Telegram videos captured instead of sent."""
    from decimal import Decimal

    from engine.media.episode import Makers
    from engine.media.images import FrameMaker
    from engine.media.render import RenderResult
    from engine.media.voice import VoiceMaker
    from engine.stages import media
    from tests.fakes_media import fake_image, fake_speech

    settings.work_dir = str(tmp_path / "work")
    brand = ROOT / "brand"
    cache = tmp_path / "work" / "cache"

    def makers(_settings, ledger, client=None):
        return Makers(
            VoiceMaker(fake_speech, ledger, brand, cache / "voice"),
            FrameMaker(
                fake_image, ledger, brand, cache / "images", "google/gemini-nano-banana-2.1"
            ),
        )

    def render_episode(ep, voice, frames, out_dir, _settings, _recent_music=()):
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("episode.mp4", "preview.mp4", "thumbnail.jpg"):
            (out_dir / name).write_bytes(b"x")
        qc = {"passed": True, "issues": [], "notes": [], "duration_s": voice.duration_s,
              "lufs": -14.0, "true_peak_db": -1.5, "size_mb": 30.0}  # fmt: skip
        return RenderResult(
            out_dir / "episode.mp4", out_dir / "preview.mp4", out_dir / "thumbnail.jpg",
            voice.duration_s, qc,
        )  # fmt: skip

    videos: list[dict] = []

    def send_video(path, caption="", buttons=None, _settings=None, **_):
        videos.append({"path": path, "caption": caption, "buttons": buttons})
        return 100 + len(videos)

    monkeypatch.setattr(media, "makers", makers)
    monkeypatch.setattr(media, "render_episode", render_episode)
    monkeypatch.setattr(media, "send_video", send_video)
    return {"videos": videos, "cost_per_image": Decimal("0.04")}
