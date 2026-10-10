"""/redo: the owner turns down today's story, and the next backup gets written instead.

The idea stage keeps the best two runners-up as backups. A redo marks today's story
owner_rejected (it is never offered again), makes the best remaining backup the day's pick, and
clears the script, critic and delivery stages so the daily run writes, reviews and sends the new
story. Discovery and the idea stage stay done, so no new story cards are paid for. The owner's
note, if they give one, goes to the script writer and the critic, and the day's notes add up
across redos.

Only between the delivered script and production: once a production stage is done, the script
is settled. A redo that fails part-way is picked up by the next /redo instead of skipping
another story.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from sqlalchemy import Engine, select

from engine.budget import BudgetExceeded, ensure_budget
from engine.config import Settings
from engine.db.models import Idea, Run
from engine.db.session import session_scope
from engine.stages import PRODUCTION
from engine.stages.base import LLM_CALL_ESTIMATE_USD
from engine.stages.idea import OWNER_REJECTED

log = logging.getLogger(__name__)

REWRITTEN = ("script", "critic", "deliver_script")
# a script and its review; a revision round or a critic reject costs more, and every call is
# still checked against the cap on its own
REDO_ESTIMATE_USD = 2 * LLM_CALL_ESTIMATE_USD
MAX_NOTE_CHARS = 500


class RedoRefused(RuntimeError):
    """Why a redo can't happen now, worded for the owner."""


def prepare_redo(
    engine: Engine, run_date: date, settings: Settings, note: str | None = None
) -> dict:
    """Swap the day's story for the next backup. The daily run then writes it (flows.daily_run).

    Returns what changed, for the reply to the owner. Raises RedoRefused when it can't.
    """
    with session_scope(engine) as s:
        run = s.scalars(select(Run).where(Run.run_date == run_date).with_for_update()).one_or_none()
        stages = dict(run.stages or {}) if run else {}
        pick = stages.get("idea", {}).get("output")
        if pick is None or stages["idea"].get("status") != "done":
            raise RedoRefused(f"There's no script for {run_date} yet.")
        if any(v.get("status") == "running" for v in stages.values()):
            raise RedoRefused(f"The script for {run_date} is still being written.")
        if any(stages.get(n, {}).get("status") == "done" for n in PRODUCTION):
            raise RedoRefused(f"Production for {run_date} has started, so its script is settled.")

        if stages.get("deliver_script", {}).get("status") != "done":
            if not pick.get("redos"):
                raise RedoRefused(f"There's no script for {run_date} yet.")
            # the last redo stopped part-way; finish it rather than skip another story
            title = s.get_one(Idea, pick["idea_id"]).title
            log.info("resuming an unfinished redo", extra={"run_date": str(run_date)})
            return {"resumed": True, "title": title, "redo": len(pick["redos"])}

        story = stages["critic"]["output"]
        backups = s.scalars(
            select(Idea)
            .where(Idea.run_id == run.id, Idea.status == "backup")
            .order_by(Idea.total_score.desc(), Idea.id)
        ).all()
        if not backups:
            raise RedoRefused(f"No backup stories are left for {run_date}.")
        try:
            ensure_budget(s, run.id, settings.daily_spend_cap_usd, REDO_ESTIMATE_USD)
        except BudgetExceeded:
            raise RedoRefused(
                f"A redo would pass the ${settings.daily_spend_cap_usd:.2f} daily spend cap "
                "(DAILY_SPEND_CAP_USD)."
            ) from None

        rejected = s.get_one(Idea, story["idea_id"])
        rejected.status = OWNER_REJECTED
        chosen, rest = backups[0], backups[1:]
        chosen.status = "picked"

        note = (note or "").strip()[:MAX_NOTE_CHARS] or None
        redos = [
            *pick.get("redos", []),
            {
                "rejected": rejected.id,
                "rejected_script_id": story["script_id"],
                "picked": chosen.id,
                "note": note,
                "at": datetime.now(UTC).isoformat(),
            },
        ]
        # the idea stage's output is the day's current pick; the script stage reads it
        stages["idea"] = {
            **stages["idea"],
            "output": {
                **pick,
                "idea_id": chosen.id,
                "backups": [b.id for b in rest],
                "owner_notes": [*pick.get("owner_notes", []), *([note] if note else [])],
                "redos": redos,
            },
        }
        for name in REWRITTEN:
            stages.pop(name, None)
        run.stages = stages
        run.status = "running"
        run.finished_at = None

        log.info(
            "redo: story turned down",
            extra={"run_date": str(run_date), "rejected": rejected.id, "picked": chosen.id},
        )
        return {
            "resumed": False,
            "rejected_title": rejected.title,
            "title": chosen.title,
            "redo": len(redos),
            "backups_left": len(rest),
        }
