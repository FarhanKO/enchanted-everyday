"""Prefect flows. `daily_run` calls each stage in order; each stage is retried on its own."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from prefect import flow, task

from engine.config import Settings, get_settings
from engine.db.models import Run
from engine.db.session import get_engine, session_scope
from engine.llm import AnthropicProvider, LLMProvider
from engine.notify import alert, ping_healthcheck
from engine.stages import PIPELINE, run_stage
from engine.stages.base import get_or_create_run

log = logging.getLogger(__name__)


def build_llm(settings: Settings) -> LLMProvider | None:
    if not settings.anthropic_api_key:
        return None
    return AnthropicProvider(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.llm_model,
        effort=settings.llm_effort,
    )


def today(settings: Settings) -> date:
    return datetime.now(settings.tz).date()


@task(retries=2, retry_delay_seconds=[60, 300], task_run_name="{name}")
def stage_task(name: str, run_date: date) -> dict:
    settings = get_settings()
    return run_stage(
        name,
        PIPELINE[name],
        run_date,
        engine=get_engine(),
        settings=settings,
        llm=build_llm(settings),
    )


def _finish(run_date: date, status: str, error: str | None = None) -> None:
    with session_scope() as s:
        run = get_or_create_run(s, run_date)
        run.status = status
        run.error = error
        run.finished_at = datetime.now(UTC)


@flow(name="daily-run")
def daily_run(run_date: str | None = None) -> dict:
    settings = get_settings()
    day = date.fromisoformat(run_date) if run_date else today(settings)
    ping_healthcheck("/start")

    results: dict[str, dict] = {}
    try:
        for name in PIPELINE:
            results[name] = stage_task(name, day)
    except Exception as e:
        _finish(day, "failed", repr(e)[:2000])
        alert(f"Daily run {day} failed at stage '{name}': {e!r}"[:1000])
        ping_healthcheck("/fail")
        raise

    _finish(day, "complete")
    ping_healthcheck()
    log.info("daily run complete", extra={"run_date": str(day), "results": results})
    return results


def run_status(run_date: date) -> dict | None:
    with session_scope() as s:
        run = s.query(Run).filter(Run.run_date == run_date).one_or_none()
        if run is None:
            return None
        return {"status": run.status, "stages": run.stages, "llm_cost_usd": str(run.llm_cost_usd)}
