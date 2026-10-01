"""Tests that need Postgres+pgvector. CI provides one; locally set TEST_DATABASE_URL to run them."""

from datetime import date
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from engine.budget import BudgetExceeded, record_llm_cost
from engine.db.models import Base, DiscoveryItem, Idea, Post, Render, Run, Script
from engine.db.session import session_scope
from engine.llm.client import LLMResult
from engine.publishers.base import (
    PublishRequest,
    PublishResult,
    PublishStateUnknown,
    publish_once,
)
from engine.stages.base import run_stage

pytestmark = pytest.mark.db
DAY = date(2026, 10, 12)


def _item(run_id: int) -> DiscoveryItem:
    return DiscoveryItem(run_id=run_id, source="slate", ref="s001", title="t", premise="p")


def _idea(run_id: int, **kw) -> Idea:
    fields = dict(
        title="t", premise="p", pillar="strange_thing", lane="dark_urban", card={}, total_score=30.0
    )
    return Idea(run_id=run_id, **(fields | kw))


def test_migrations_match_models(db_engine):
    with db_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations disagree: {diff}"


def test_finished_stage_is_not_rerun(db_engine, settings):
    calls = []

    def stage(ctx):
        calls.append(1)
        ctx.session.add(_item(ctx.run_id))
        return {"n": 1}

    assert run_stage("discovery", stage, DAY, engine=db_engine, settings=settings) == {"n": 1}
    assert run_stage("discovery", stage, DAY, engine=db_engine, settings=settings) == {"n": 1}
    assert len(calls) == 1


def test_failed_stage_rolls_back_and_retries(db_engine, settings):
    attempts = []

    def flaky(ctx):
        attempts.append(1)
        ctx.session.add(_item(ctx.run_id))
        ctx.session.flush()
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return {}

    with pytest.raises(RuntimeError):
        run_stage("discovery", flaky, DAY, engine=db_engine, settings=settings)
    with session_scope(db_engine) as s:
        run = s.scalars(select(Run)).one()
        assert run.stages["discovery"]["status"] == "failed"
        assert s.scalars(select(DiscoveryItem)).all() == []  # partial write rolled back

    run_stage("discovery", flaky, DAY, engine=db_engine, settings=settings)
    with session_scope(db_engine) as s:
        run = s.scalars(select(Run)).one()
        assert run.stages["discovery"]["status"] == "done"
        assert run.stages["discovery"]["attempts"] == 2
        assert len(s.scalars(select(DiscoveryItem)).all()) == 1


def test_spend_cap_blocks_llm_calls(db_engine, settings):
    class FakeLLM:
        def complete_json(self, **_):
            return LLMResult(
                data={}, model="m", input_tokens=0, output_tokens=0, cost_usd=Decimal("0.60")
            )

    def stage(ctx):
        from pydantic import BaseModel

        class Empty(BaseModel):
            pass

        for _ in range(5):
            ctx.llm_json(system="s", user="u", schema={}, model=Empty)
        return {}

    with pytest.raises(BudgetExceeded):
        run_stage("script", stage, DAY, engine=db_engine, settings=settings, llm=FakeLLM())

    # cost of the calls that ran is kept even though the stage failed
    with session_scope(db_engine) as s:
        assert s.scalars(select(Run)).one().llm_cost_usd == Decimal("0.60")


def test_record_llm_cost_accumulates(db_engine, settings):
    run_stage("discovery", lambda ctx: {}, DAY, engine=db_engine, settings=settings)
    with session_scope(db_engine) as s:
        run_id = s.scalars(select(Run.id)).one()
    record_llm_cost(db_engine, run_id, Decimal("0.1"))
    record_llm_cost(db_engine, run_id, Decimal("0.2"))
    with session_scope(db_engine) as s:
        assert s.get_one(Run, run_id).llm_cost_usd == Decimal("0.3")


def _render(db_engine) -> int:
    with session_scope(db_engine) as s:
        run = Run(run_date=DAY, status="running")
        s.add(run)
        s.flush()
        idea = _idea(run.id)
        s.add(idea)
        s.flush()
        script = Script(idea_id=idea.id, narration="n", script={}, prompt_version="v1")
        s.add(script)
        s.flush()
        render = Render(script_id=script.id, uri="s3://x", duration_s=45, qc_report={})
        s.add(render)
        s.flush()
        return render.id


class FakePublisher:
    platform = "instagram"

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def publish(self, req):
        self.calls += 1
        if self.fail:
            raise RuntimeError("api error")
        return PublishResult(external_id="ig123", url="https://instagram.com/p/ig123")


def _req(render_id):
    return PublishRequest(
        render_id=render_id,
        video_path="/tmp/v.mp4",
        video_url="https://v",
        caption="c",
        title="t",
        ai_generated=False,
    )


def test_publish_is_idempotent(db_engine):
    render_id = _render(db_engine)
    pub = FakePublisher()
    publish_once(db_engine, pub, _req(render_id))
    publish_once(db_engine, pub, _req(render_id))
    assert pub.calls == 1
    with session_scope(db_engine) as s:
        post = s.scalars(select(Post)).one()
        assert (post.status, post.external_id, post.attempts) == ("published", "ig123", 1)


def test_failed_publish_can_retry(db_engine):
    render_id = _render(db_engine)
    with pytest.raises(RuntimeError):
        publish_once(db_engine, FakePublisher(fail=True), _req(render_id))
    publish_once(db_engine, FakePublisher(), _req(render_id))
    with session_scope(db_engine) as s:
        assert s.scalars(select(Post)).one().attempts == 2


def test_interrupted_publish_needs_a_human(db_engine):
    render_id = _render(db_engine)
    with session_scope(db_engine) as s:
        s.add(Post(render_id=render_id, platform="instagram", status="publishing", attempts=1))
    pub = FakePublisher()
    with pytest.raises(PublishStateUnknown):
        publish_once(db_engine, pub, _req(render_id))
    assert pub.calls == 0


def test_discovery_skips_used_slate_stories(db_engine, settings):
    from engine.stages import discovery

    with session_scope(db_engine) as s:
        earlier = Run(run_date=date(2026, 10, 11), status="complete")
        s.add(earlier)
        s.flush()
        s.add(_idea(earlier.id, slate_id="s000", status="published"))

    out = run_stage("discovery", discovery.run, DAY, engine=db_engine, settings=settings)
    assert "s000" not in out["candidates"]
    assert out["preferred_lane"] == "cozy_bedtime"  # 1 of 1 recent picks was dark
    with session_scope(db_engine) as s:
        refs = s.scalars(select(DiscoveryItem.ref)).all()
    assert sorted(refs) == sorted(out["candidates"])
