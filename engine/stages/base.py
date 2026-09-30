"""Stage runner: every stage is keyed on (run_date, stage name) and safe to retry.

A stage's database writes and its "done" marker commit in one transaction, so a crash leaves
either both or neither. A retry of a finished stage returns its saved output without running again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from engine.budget import ensure_budget, record_llm_cost
from engine.config import Settings
from engine.db.models import Run
from engine.db.session import session_scope
from engine.llm.client import LLMProvider, parse_as

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

# Rough upper bound for one call, checked before calling so the cap is never overshot by much.
LLM_CALL_ESTIMATE_USD = Decimal("0.25")


@dataclass
class StageContext:
    run_id: int
    run_date: date
    session: Session
    settings: Settings
    engine: Engine
    outputs: dict[str, Any] = field(default_factory=dict)  # outputs of finished earlier stages
    llm: LLMProvider | None = None

    def llm_json(self, *, system: str, user: str, schema: dict, model: type[M]) -> M:
        if self.llm is None:
            raise RuntimeError("no LLM provider configured for this stage")
        ensure_budget(
            self.session, self.run_id, self.settings.daily_spend_cap_usd, LLM_CALL_ESTIMATE_USD
        )
        result = self.llm.complete_json(system=system, user=user, schema=schema)
        record_llm_cost(self.engine, self.run_id, result.cost_usd)
        return parse_as(result, model)


StageFn = Callable[[StageContext], dict[str, Any] | None]


def get_or_create_run(session: Session, run_date: date) -> Run:
    session.execute(
        insert(Run)
        .values(run_date=run_date, status="running")
        .on_conflict_do_nothing(index_elements=[Run.run_date])
    )
    return session.scalars(select(Run).where(Run.run_date == run_date)).one()


def _set_stage(run: Run, name: str, **state: Any) -> None:
    stages = dict(run.stages or {})
    stages[name] = {**stages.get(name, {}), **state}
    run.stages = stages  # reassign so SQLAlchemy sees the JSONB change


def _now() -> str:
    return datetime.now(UTC).isoformat()


def run_stage(
    name: str,
    fn: StageFn,
    run_date: date,
    *,
    engine: Engine,
    settings: Settings,
    llm: LLMProvider | None = None,
) -> dict[str, Any]:
    with session_scope(engine) as s:
        run = get_or_create_run(s, run_date)
        run_id = run.id
        state = (run.stages or {}).get(name, {})
        if state.get("status") == "done":
            log.info("stage already done; skipping", extra={"stage": name, "run_date": run_date})
            return state.get("output") or {}
        _set_stage(
            run, name, status="running", started_at=_now(), attempts=state.get("attempts", 0) + 1
        )

    log.info("stage start", extra={"stage": name, "run_date": str(run_date)})
    try:
        with session_scope(engine) as s:
            run = s.get_one(Run, run_id)
            outputs = {
                k: v.get("output") or {}
                for k, v in (run.stages or {}).items()
                if v.get("status") == "done"
            }
            ctx = StageContext(
                run_id=run_id,
                run_date=run_date,
                session=s,
                settings=settings,
                engine=engine,
                outputs=outputs,
                llm=llm,
            )
            output = fn(ctx) or {}
            _set_stage(run, name, status="done", finished_at=_now(), output=output, error=None)
    except Exception as e:
        with session_scope(engine) as s:
            run = s.get_one(Run, run_id)
            _set_stage(run, name, status="failed", finished_at=_now(), error=repr(e)[:2000])
        log.exception("stage failed", extra={"stage": name, "run_date": str(run_date)})
        raise

    log.info("stage done", extra={"stage": name, "run_date": str(run_date)})
    return output
