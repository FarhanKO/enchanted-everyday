"""Prefect flows; each stage is retried on its own.

daily_run   (scheduled) discovery to the reviewed script in Telegram; after a /redo
            (engine/redo.py) it writes, reviews and sends the next backup story
produce     (on the owner's request) storyboard and package for a day's script
token_check (scheduled) Meta and YouTube login health; fix-it steps to Telegram
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from cronsim import CronSim
from prefect import flow, task
from sqlalchemy import Engine

from engine.config import Settings, get_settings
from engine.db.models import Run
from engine.db.session import get_engine, session_scope
from engine.llm import AnthropicProvider, LLMProvider, OpenRouterProvider
from engine.notify import alert, ping_healthcheck
from engine.stages import DAILY, PRODUCTION, STAGES, run_stage
from engine.stages.base import get_or_create_run

log = logging.getLogger(__name__)


def build_llm(settings: Settings) -> LLMProvider | None:
    if settings.openrouter_api_key:
        provider, key = OpenRouterProvider, settings.openrouter_api_key
    elif settings.anthropic_api_key:
        provider, key = AnthropicProvider, settings.anthropic_api_key
    else:
        return None
    return provider(
        api_key=key.get_secret_value(),
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
        STAGES[name],
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
        for name in DAILY:
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


@flow(name="produce")
def produce(run_date: str | None = None) -> dict:
    settings = get_settings()
    day = date.fromisoformat(run_date) if run_date else today(settings)
    results: dict[str, dict] = {}
    try:
        for name in PRODUCTION:
            results[name] = stage_task(name, day)
    except Exception as e:
        alert(f"Production for {day} failed at stage '{name}': {e!r}"[:1000])
        raise
    log.info("production complete", extra={"run_date": str(day), "results": results})
    return results


@flow(name="token-check")
def token_check() -> list[str]:
    from engine.tokens import check_tokens

    messages = check_tokens()
    for message in messages:
        alert(message)
    log.info("token check complete", extra={"warnings": len(messages)})
    return messages


def missed_daily_run(
    settings: Settings, now: datetime | None = None, engine: Engine | None = None
) -> date | None:
    """Today, when today's DAILY_RUN_CRON time has passed and the day never got going: the machine
    was off or asleep at run time (a PC that was shut down, a server that was down), or it stopped
    mid-run. A run that finished or failed is left alone; a failure has already sent its alert."""
    now = now or datetime.now(settings.tz)
    last = next(iter(CronSim(settings.daily_run_cron, now.astimezone(settings.tz), reverse=True)))
    if last.date() != now.astimezone(settings.tz).date():
        return None
    with session_scope(engine) as s:
        run = s.query(Run).filter(Run.run_date == last.date()).one_or_none()
        if run is not None and run.status not in ("pending", "running"):
            return None
    return last.date()


def run_status(run_date: date) -> dict | None:
    with session_scope() as s:
        run = s.query(Run).filter(Run.run_date == run_date).one_or_none()
        if run is None:
            return None
        pick = (run.stages or {}).get("idea", {}).get("output") or {}
        return {
            "status": run.status,
            "stages": run.stages,
            "llm_cost_usd": str(run.llm_cost_usd),
            "redos": len(pick.get("redos", [])),
        }
