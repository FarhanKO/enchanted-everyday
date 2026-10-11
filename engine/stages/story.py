"""The story and production stages, all on one `scripts` row per draft.

Story (the daily run): script, then critic. The critic reviews the card and script before any
money goes into visuals. On 'revise' the script writer revises with its notes, as a new version,
and the critic reviews once more. On 'reject' the idea is dropped for the first backup, which gets
its own script and review. Either way the final script goes to the owner, report attached: the
critic advises, the owner decides.

Production (after the owner has the script): storyboard, then package, filled into the same row.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select

from engine.canon import Canon
from engine.canon import load as load_canon
from engine.db.models import Idea
from engine.db.models import Script as ScriptRow
from engine.llm.prompts import PROMPT_VERSION
from engine.llm.schemas import CriticReport, Script, Storyboard, StoryCard
from engine.stages.base import StageContext
from engine.studio import Studio

log = logging.getLogger(__name__)

MAX_REVISIONS = 1  # critic rounds after the first; each costs a rewrite and a review


def _studio(ctx: StageContext) -> Studio:
    return Studio(ctx.llm_json, Path(ctx.settings.brand_dir))


def _canon(ctx: StageContext) -> Canon:
    return load_canon(ctx.session, Path(ctx.settings.brand_dir))


def _card(ctx: StageContext, idea_id: int) -> StoryCard:
    return StoryCard.model_validate(ctx.session.get_one(Idea, idea_id).card)


def _row(ctx: StageContext, stage: str) -> ScriptRow:
    if stage not in ctx.outputs:
        raise RuntimeError(f"stage '{stage}' hasn't finished for {ctx.run_date}")
    return ctx.session.get_one(ScriptRow, ctx.outputs[stage]["script_id"])


def _new_row(
    ctx: StageContext, idea_id: int, script: Script, report: CriticReport | None = None
) -> ScriptRow:
    latest = ctx.session.scalar(
        select(func.coalesce(func.max(ScriptRow.version), 0)).where(ScriptRow.idea_id == idea_id)
    )
    row = ScriptRow(
        idea_id=idea_id,
        version=latest + 1,
        narration=script.spoken_text,
        script=script.model_dump(mode="json"),
        critic_report=report.model_dump(mode="json") if report else None,
        prompt_version=PROMPT_VERSION,
    )
    ctx.session.add(row)
    ctx.session.flush()
    return row


# ---------------------------------------------------------------- story


def _owner_notes(ctx: StageContext) -> list[str]:
    """The owner's notes from today's /redo requests (engine/redo.py)."""
    return ctx.outputs["idea"].get("owner_notes", [])


def script(ctx: StageContext) -> dict:
    idea_id = ctx.outputs["idea"]["idea_id"]
    written = _studio(ctx).script(
        _card(ctx, idea_id), owner_notes=_owner_notes(ctx), canon=_canon(ctx)
    )
    row = _new_row(ctx, idea_id, written)
    return {
        "script_id": row.id,
        "words": written.word_count,
        "seconds": round(written.estimated_duration_s),
    }


def critic(ctx: StageContext) -> dict:
    studio = _studio(ctx)
    row = _row(ctx, "script")
    idea_id = row.idea_id
    card = _card(ctx, idea_id)
    draft = Script.model_validate(row.script)
    owner_notes = _owner_notes(ctx)
    canon = _canon(ctx)

    report = studio.review(card, draft, owner_notes, canon)
    row.critic_report = report.model_dump(mode="json")
    history = [report.verdict]

    if report.verdict == "reject" and (backups := ctx.outputs["idea"].get("backups")):
        ctx.session.get_one(Idea, idea_id).status = "rejected"
        idea_id = backups[0]
        ctx.session.get_one(Idea, idea_id).status = "picked"
        log.info("critic rejected the story; writing the backup", extra={"idea_id": idea_id})
        card = _card(ctx, idea_id)
        draft = studio.script(card, owner_notes=owner_notes, canon=canon)
        report = studio.review(card, draft, owner_notes, canon)
        row = _new_row(ctx, idea_id, draft, report)
        history.append(report.verdict)

    for _ in range(MAX_REVISIONS):
        if report.verdict != "revise":
            break
        draft = studio.revise_script(card, draft, report, owner_notes, canon)
        report = studio.review(card, draft, owner_notes, canon)
        row = _new_row(ctx, idea_id, draft, report)
        history.append(report.verdict)

    return {
        "script_id": row.id,
        "idea_id": idea_id,
        "verdict": report.verdict,
        "history": history,
        "high_issues": sum(i.severity == "high" for i in report.issues),
        "repairs": studio.repairs,
    }


# ---------------------------------------------------------------- production


def storyboard(ctx: StageContext) -> dict:
    row = _row(ctx, "critic")
    board = _studio(ctx).storyboard(_card(ctx, row.idea_id), Script.model_validate(row.script))
    row.storyboard = board.model_dump(mode="json")
    return {"script_id": row.id, "shots": len(board.shots)}


def package(ctx: StageContext) -> dict:
    row = _row(ctx, "storyboard")
    pkg = _studio(ctx).package(
        _card(ctx, row.idea_id),
        Script.model_validate(row.script),
        Storyboard.model_validate(row.storyboard),
        _canon(ctx),
    )
    row.package = pkg.model_dump(mode="json")
    return {"script_id": row.id, "title": pkg.title}
