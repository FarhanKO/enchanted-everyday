"""Production through to the video in Telegram, and the owner's verdict on it. Needs Postgres.

Media is faked (tests/conftest.py, fake_media): voice and frames are free stand-ins and the render
writes placeholder files, so this checks the stages, the bookkeeping and the buttons.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from engine.approval import Refused, decide, posting_kit, prepare_reshoot
from engine.budget import spent
from engine.db.models import Approval, Asset, Render, Run
from engine.db.session import session_scope
from engine.stages import DAILY, PRODUCTION, STAGES, deliver, idea, run_stage
from tests.fakes import FakeEmbedder, FakeLLM

pytestmark = pytest.mark.db
DAY = date(2026, 10, 12)


@pytest.fixture
def produced(db_engine, settings, fake_media, monkeypatch):
    monkeypatch.setattr(deliver, "send_message", lambda *_: None)
    monkeypatch.setattr(deliver, "send_document", lambda *_: None)
    monkeypatch.setattr(idea, "get_embedder", lambda _: FakeEmbedder(keys=["Premise number 0 "]))
    llm = FakeLLM()
    out = {}
    for name in DAILY + PRODUCTION:
        out[name] = run_stage(name, STAGES[name], DAY, engine=db_engine, settings=settings, llm=llm)
    return out


def _assets(db_engine) -> list[Asset]:
    with session_scope(db_engine) as s:
        rows = s.scalars(select(Asset).order_by(Asset.id)).all()
        s.expunge_all()
        return rows


def _render(db_engine, render_id) -> Render:
    with session_scope(db_engine) as s:
        row = s.get_one(Render, render_id)
        s.expunge(row)
        return row


def test_production_ends_with_the_video_and_its_buttons(db_engine, settings, fake_media, produced):
    out = produced
    shots = len(out["images"]["shots"])
    voice_lines = len(out["voice"]["lines"])

    assets = _assets(db_engine)
    kinds = [a.kind for a in assets]
    assert kinds.count("voice") == voice_lines  # every line; nothing is spoken after the landing
    assert kinds.count("image") == shots + 1  # every shot, and the cover
    assert all(a.license and a.script_id == out["package"]["script_id"] for a in assets)

    with session_scope(db_engine) as s:
        run = s.scalars(select(Run)).one()
        assert spent(s, run.id) == run.llm_cost_usd + sum(a.cost_usd for a in assets)

    render_id = out["render"]["render_id"]
    row = _render(db_engine, render_id)
    assert row.status == "ready" and row.ai_generated and row.qc_report["passed"]

    (video,) = fake_media["videos"]
    assert video["buttons"] == [
        [
            {"text": "Approve", "callback_data": f"approve:{render_id}"},
            {"text": "Skip", "callback_data": f"skip:{render_id}"},
        ]
    ]
    assert "/reshoot S03" in video["caption"] and "Spent today: $" in video["caption"]
    assert out["deliver_render"] == {"render_id": render_id, "sent": True, "message_id": 101}


def test_a_retry_pays_for_nothing_twice(db_engine, settings, fake_media, produced):
    before = len(_assets(db_engine))
    with session_scope(db_engine) as s:
        run = s.scalars(select(Run)).one()
        run.stages = {k: v for k, v in run.stages.items() if k not in ("voice", "images")}
    for name in ("voice", "images"):
        run_stage(name, STAGES[name], DAY, engine=db_engine, settings=settings)
    assert len(_assets(db_engine)) == before


def test_approve_once(db_engine, produced):
    render_id = produced["render"]["render_id"]
    d = decide(db_engine, render_id, "approve")
    assert d.decision == "approve" and d.episode.package.title
    assert _render(db_engine, render_id).status == "approved"
    with pytest.raises(Refused, match="already approved"):
        decide(db_engine, render_id, "skip")
    with session_scope(db_engine) as s:
        assert [a.decision for a in s.scalars(select(Approval))] == ["approve"]

    kit = posting_kit(d.episode)
    assert kit[0].startswith("Posting kit:") and "Altered content" in kit[0]
    assert any(m.startswith("YOUTUBE title") for m in kit)
    tags = d.episode.package.platforms.hashtags
    assert all(tags[0] in m for m in kit[2:])  # every caption carries the hashtags


def test_reshoot_redraws_one_frame_and_replaces_the_video(
    db_engine, settings, fake_media, produced
):
    old_render = produced["render"]["render_id"]
    images_before = [a for a in _assets(db_engine) if a.kind == "image"]

    asked = prepare_reshoot(db_engine, DAY, "s03", settings, "warmer light")
    assert asked == {"frame": "S03", "note": "warmer light", "take": 2, "reshoots": 1}
    assert _render(db_engine, old_render).status == "replaced"
    with pytest.raises(Refused, match="replaced"):
        decide(db_engine, old_render, "approve")

    out = {n: run_stage(n, STAGES[n], DAY, engine=db_engine, settings=settings) for n in PRODUCTION}
    images_after = [a for a in _assets(db_engine) if a.kind == "image"]
    assert len(images_after) == len(images_before) + 1  # only S03 was bought again
    assert "warmer light" in images_after[-1].meta["prompt"]
    assert out["render"]["render_id"] != old_render
    assert len(fake_media["videos"]) == 2
    assert decide(db_engine, out["render"]["render_id"], "approve").decision == "approve"
    with pytest.raises(Refused, match="already approved"):
        prepare_reshoot(db_engine, DAY, "S04", settings)


def test_reshoot_refusals(db_engine, settings, fake_media, produced):
    with pytest.raises(Refused, match="No frame S99"):
        prepare_reshoot(db_engine, DAY, "S99", settings)
    with pytest.raises(Refused, match="no video"):
        prepare_reshoot(db_engine, date(2026, 10, 13), "S01", settings)
    settings.daily_spend_cap_usd = float(Decimal("0.01"))
    with pytest.raises(Refused, match="daily spend cap"):
        prepare_reshoot(db_engine, DAY, "thumb", settings)


# ---------------------------------------------------------------- publishing (Phase 3)


class FakePlatform:
    """A publisher that records what it was sent; `fail` makes it turn the post down."""

    def __init__(self, platform, fail=False):
        self.platform, self.fail, self.sent = platform, fail, []

    def publish(self, req):
        from engine.publishers import PublishError, PublishResult

        self.sent.append(req)
        if self.fail:
            raise PublishError(f"{self.platform} said: no")
        return PublishResult(external_id=f"{self.platform}-1", url=f"https://{self.platform}/1")


def _publishing(settings):
    from pydantic import SecretStr

    return settings.model_copy(
        update={
            "dry_run": False,
            "meta_page_id": "555",
            "meta_ig_user_id": "17841",
            "meta_page_access_token": SecretStr("t"),
        }
    )


def test_approve_posts_once_and_a_retry_posts_only_what_failed(db_engine, settings, produced):
    from engine.db.models import Post
    from engine.publish import NothingToPublish, mark_post, publish_render

    render_id = produced["render"]["render_id"]
    live = _publishing(settings)
    with pytest.raises(NothingToPublish):  # not approved yet
        publish_render(db_engine, render_id, live)
    decide(db_engine, render_id, "approve")

    fakes = {
        "instagram": FakePlatform("instagram"),
        "facebook": FakePlatform("facebook", fail=True),
    }
    pick = lambda platform, *_: fakes[platform]  # noqa: E731
    first = publish_render(db_engine, render_id, live, make_publisher=pick)
    assert [(o.platform, o.status) for o in first] == [
        ("instagram", "published"),
        ("facebook", "failed"),
    ]
    assert fakes["instagram"].sent[0].ai_generated

    fakes["facebook"].fail = False
    again = publish_render(db_engine, None, live, make_publisher=pick)  # None: the latest approved
    assert [o.status for o in again] == ["published", "published"]
    assert len(fakes["instagram"].sent) == 1  # already live: not posted twice
    assert len(fakes["facebook"].sent) == 2

    with session_scope(db_engine) as s:
        posts = {p.platform: p for p in s.scalars(select(Post)).all()}
    assert posts["facebook"].attempts == 2 and posts["facebook"].url == "https://facebook/1"
    with pytest.raises(NothingToPublish, match="already has it"):
        mark_post(db_engine, "instagram", "failed")


def test_an_interrupted_post_waits_for_the_owner(db_engine, settings, produced):
    from engine.db.models import Post
    from engine.publish import mark_post, publish_render

    render_id = produced["render"]["render_id"]
    decide(db_engine, render_id, "approve")
    with session_scope(db_engine) as s:
        s.add(Post(render_id=render_id, platform="instagram", status="publishing", attempts=1))
    ig = FakePlatform("instagram")
    pick = lambda *_: ig  # noqa: E731
    live = _publishing(settings)

    out = publish_render(db_engine, render_id, live, platforms=["instagram"], make_publisher=pick)
    assert out[0].status == "unknown" and not ig.sent

    mark_post(db_engine, "instagram", "failed")  # the owner checked: it isn't live
    out = publish_render(db_engine, render_id, live, platforms=["instagram"], make_publisher=pick)
    assert out[0].status == "published" and len(ig.sent) == 1


def test_dry_run_posts_nothing(db_engine, settings, produced):
    from engine.publish import publish_render

    render_id = produced["render"]["render_id"]
    decide(db_engine, render_id, "approve")
    assert publish_render(db_engine, render_id, settings, make_publisher=pytest.fail) == []
