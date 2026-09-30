"""Hard daily spending cap. A bad prompt loop hits this wall instead of the credit card."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from engine.db.models import Asset, Idea, Run, Script


class BudgetExceeded(RuntimeError):
    pass


def spent(session: Session, run_id: int) -> Decimal:
    """LLM spend plus paid assets for one run date."""
    llm = session.scalar(select(Run.llm_cost_usd).where(Run.id == run_id))
    assets = session.scalar(
        select(func.coalesce(func.sum(Asset.cost_usd), 0))
        .join(Script, Asset.script_id == Script.id)
        .join(Idea, Script.idea_id == Idea.id)
        .where(Idea.run_id == run_id)
    )
    return Decimal(llm or 0) + Decimal(assets or 0)


def ensure_budget(
    session: Session, run_id: int, cap_usd: float, planned_usd: Decimal = Decimal(0)
) -> None:
    total = spent(session, run_id) + planned_usd
    if total > Decimal(str(cap_usd)):
        raise BudgetExceeded(f"run {run_id}: ${total:.4f} would exceed cap ${cap_usd:.2f}")


def record_llm_cost(engine: Engine, run_id: int, cost: Decimal) -> None:
    """Commit spend in its own transaction, so it counts even if the calling stage later fails."""
    with engine.begin() as conn:
        conn.execute(
            update(Run).where(Run.id == run_id).values(llm_cost_usd=Run.llm_cost_usd + cost)
        )
