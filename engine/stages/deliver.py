"""Send the owner what they need on Telegram, at each hand-off.

deliver_script (end of the daily run): the reviewed script, with delivery notes and pauses for
recording, and the critic's verdict. The owner then asks for production with /produce (Phase 2:
their voice note does it), or for another story with /redo.

deliver_package (end of production): the full production package, episode.md, as a file.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from engine.db.models import Idea
from engine.db.models import Script as ScriptRow
from engine.episode_doc import to_markdown
from engine.llm.schemas import (
    CriticReport,
    Episode,
    Package,
    Script,
    Storyboard,
    StoryCard,
    speaker_label,
)
from engine.notify import TelegramNotConfigured, send_document, send_message
from engine.stages.base import StageContext

log = logging.getLogger(__name__)


def script_message(
    card: StoryCard,
    script: Script,
    report: CriticReport,
    day: date,
    *,
    redo: int = 0,
    backups_left: int = 0,
) -> str:
    out = [
        f"Today's story, {day:%a %d %b}" + (f" (redo {redo})" if redo else ""),
        card.title,
        f"{card.universe} · {card.story_type} · {card.mode} · {script.word_count} words · "
        f"~{script.estimated_duration_s:.0f}s",
        "",
        card.premise,
        "",
        f"Voice: {script.narration_direction}",
        "",
    ]
    for beat in script.beats:
        out.append(beat.name.upper())
        for line in beat.lines:
            pause = f" [pause {line.pause_after_s:g}s]" if line.pause_after_s >= 0.5 else ""
            who = "" if line.speaker == "narrator" else f"{speaker_label(line.speaker)}: "
            out.append(f"{who}{line.text}  ({line.delivery}){pause}")
        out.append("")

    high = [i for i in report.issues if i.severity == "high"]
    verdict = f"Critic: {report.verdict}"
    if report.issues:
        verdict += f" ({len(high)} high, {len(report.issues) - len(high)} low)"
    out.append(verdict)
    for i in high or report.issues[:3]:
        out.append(f"- {i.area}{f', rule {i.rule}' if i.rule else ''}: {i.problem}")
    out += ["", "Send /produce to build the storyboard and production package."]
    if backups_left:
        out.append(f"Or /redo for another story ({backups_left} left), with a note if you like.")
    else:
        out.append("No backup stories left for /redo today.")
    return "\n".join(out)


def load_episode(ctx: StageContext, script_id: int) -> Episode:
    return episode_from_db(ctx.session, script_id)


def episode_from_db(session: Session, script_id: int) -> Episode:
    row = session.get_one(ScriptRow, script_id)
    idea = session.get_one(Idea, row.idea_id)
    return Episode(
        id=f"ep{idea.id:04d}",
        slate_id=idea.slate_id,
        card=StoryCard.model_validate(idea.card),
        script=Script.model_validate(row.script),
        storyboard=Storyboard.model_validate(row.storyboard),
        package=Package.model_validate(row.package),
    )


def deliver_script(ctx: StageContext) -> dict:
    script_id = ctx.outputs["critic"]["script_id"]
    row = ctx.session.get_one(ScriptRow, script_id)
    card = StoryCard.model_validate(ctx.session.get_one(Idea, row.idea_id).card)
    backups_left = ctx.session.scalar(
        select(func.count()).where(Idea.run_id == ctx.run_id, Idea.status == "backup")
    )
    text = script_message(
        card,
        Script.model_validate(row.script),
        CriticReport.model_validate(row.critic_report),
        ctx.run_date,
        redo=len(ctx.outputs["idea"].get("redos", [])),
        backups_left=backups_left,
    )
    result = {"script_id": script_id, "sent": False}
    try:
        send_message(text, ctx.settings)
    except TelegramNotConfigured:
        log.warning("script not delivered: Telegram not configured", extra=result)
        return result
    return result | {"sent": True}


def deliver_package(ctx: StageContext) -> dict:
    script_id = ctx.outputs["package"]["script_id"]
    ep = load_episode(ctx, script_id)
    result = {"episode_id": ep.id, "script_id": script_id, "sent": False}
    try:
        send_document(
            f"{ep.id}.md",
            to_markdown(ep).encode("utf-8"),
            f"Production package: {ep.package.title}",
            ctx.settings,
        )
    except TelegramNotConfigured:
        log.warning("package not delivered: Telegram not configured", extra=result)
        return result
    return result | {"sent": True}
