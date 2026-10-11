"""Production, part 2: voice, images, render, and the video to the owner for approval.

Each is its own stage, so a failure resumes where it stopped, and every paid asset is cached and
booked on the assets table the moment it's bought (engine/media/paid.py): a retry never pays
twice, and the daily cap counts everything spent.

deliver_render sends the preview with Approve / Skip buttons (bot/main.py handles the taps). Until
publishing is automated (Phase 3), Approve sends the posting kit: the full-quality file, the cover
and each platform's copy, to post by hand.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, insert, select

from engine.budget import ensure_budget
from engine.config import Settings
from engine.db.models import Asset, Render
from engine.db.session import session_scope
from engine.llm.schemas import Episode
from engine.media.episode import makers, render_episode
from engine.media.images import Frames
from engine.media.voice import VoiceTrack
from engine.notify import TelegramNotConfigured, send_video
from engine.stages.base import StageContext
from engine.stages.deliver import load_episode

log = logging.getLogger(__name__)

LICENSES = {
    "image": "AI-generated through OpenRouter ({provider}); output owned by the operator under the "
    "provider's terms",
    "voice": "ElevenLabs speech through OpenRouter ({provider}), paid API: commercial use allowed "
    "under ElevenLabs' terms; synthetic voice, disclosed on every post",
}


class DbLedger:
    """Checks the daily cap and books each purchase on the assets table, in its own transaction."""

    def __init__(self, engine: Engine, run_id: int, script_id: int, cap_usd: float) -> None:
        self.engine, self.run_id, self.script_id, self.cap = engine, run_id, script_id, cap_usd

    def check(self, estimate_usd: Decimal) -> None:
        with session_scope(self.engine) as s:
            ensure_budget(s, self.run_id, self.cap, estimate_usd)

    def record(self, kind: str, provider: str, cost_usd: Decimal, path: Path, meta: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(Asset).values(
                    script_id=self.script_id,
                    kind=kind,
                    uri=path.as_posix(),
                    provider=provider,
                    license=LICENSES[kind].format(provider=provider),
                    cost_usd=cost_usd,
                    meta=meta,
                )
            )


def day_dir(settings: Settings, ctx: StageContext) -> Path:
    return Path(settings.work_dir) / "runs" / str(ctx.run_date)


def _episode(ctx: StageContext) -> tuple[int, Episode]:
    script_id = ctx.outputs["package"]["script_id"]
    return script_id, load_episode(ctx, script_id)


def _makers(ctx: StageContext, script_id: int):
    ledger = DbLedger(ctx.engine, ctx.run_id, script_id, ctx.settings.daily_spend_cap_usd)
    return makers(ctx.settings, ledger)


def voice(ctx: StageContext) -> dict:
    script_id, ep = _episode(ctx)
    track = _makers(ctx, script_id).voice.make(ep.script, day_dir(ctx.settings, ctx) / "voice.wav")
    return {"script_id": script_id, **track.to_json()}


def reshoots(ctx: StageContext) -> dict:
    """The owner's /reshoot requests for the day: {"notes": {...}, "takes": {...}}."""
    return ctx.outputs.get("reshoot") or {}


def images(ctx: StageContext) -> dict:
    script_id, ep = _episode(ctx)
    asks = reshoots(ctx)
    frames = _makers(ctx, script_id).frames.make(
        ep.storyboard, ep.package.thumbnail, asks.get("notes"), asks.get("takes")
    )
    return {"script_id": script_id, **frames.to_json()}


def recent_music(ctx: StageContext, script_id: int, episodes: int = 6) -> list[str]:
    """Track files heard in the last few other episodes' renders, most recent first."""
    reports = ctx.session.scalars(
        select(Render.qc_report)
        .where(Render.script_id != script_id)
        .order_by(Render.id.desc())
        .limit(episodes)
    )
    out: list[str] = []
    for report in reports:
        heard = (report or {}).get("music") or []
        if isinstance(heard, dict):  # renders before music moods carried one track
            heard = [heard]
        out += [m["file"] for m in heard if m.get("file")]
    return out


def render(ctx: StageContext) -> dict:
    script_id, ep = _episode(ctx)
    track = VoiceTrack.from_json(ctx.outputs["voice"])
    out = ctx.outputs["images"]
    frames = Frames(
        shots={k: Path(v) for k, v in out["shots"].items()},
        thumbnail=Path(out["thumbnail"]) if out.get("thumbnail") else None,
    )
    take = len(reshoots(ctx).get("history", [])) + 1
    out_dir = day_dir(ctx.settings, ctx) / f"render_{take}"
    result = render_episode(ep, track, frames, out_dir, ctx.settings, recent_music(ctx, script_id))
    row = Render(
        script_id=script_id,
        uri=result.path.as_posix(),
        duration_s=result.duration_s,
        qc_report={
            **result.qc,
            "preview": result.preview.as_posix(),
            "thumbnail": result.thumbnail.as_posix() if result.thumbnail else None,
        },
        status="ready" if result.qc["passed"] else "qc_failed",
        ai_generated=True,
    )
    ctx.session.add(row)
    ctx.session.flush()
    return {"script_id": script_id, "render_id": row.id, "qc_passed": result.qc["passed"]}


def render_caption(ep: Episode, row: Render, spent: Decimal | None = None) -> str:
    qc = row.qc_report
    lines = [
        ep.package.title,
        f"{qc['duration_s']:.0f}s · {qc['size_mb']} MB · {qc['lufs']:.1f} LUFS",
    ]
    if qc["issues"]:
        lines.append("QC: " + "; ".join(qc["issues"]))
    lines += [f"Note: {n}" for n in qc["notes"]]
    if spent is not None:
        lines.append(f"Spent today: ${spent:.2f}")
    lines += [
        "",
        "Approve to get the posting kit, or Skip.",
        "Redraw a frame: /reshoot S03 (optionally with a note, e.g. /reshoot S03 warmer light).",
    ]
    return "\n".join(lines)


def buttons(render_id: int) -> list[list[dict]]:
    return [
        [
            {"text": "Approve", "callback_data": f"approve:{render_id}"},
            {"text": "Skip", "callback_data": f"skip:{render_id}"},
        ]
    ]


def deliver_render(ctx: StageContext) -> dict:
    from engine.budget import spent

    script_id, ep = _episode(ctx)
    render_id = ctx.outputs["render"]["render_id"]
    row = ctx.session.get_one(Render, render_id)
    result = {"render_id": render_id, "sent": False}
    try:
        message_id = send_video(
            Path(row.qc_report["preview"]),
            render_caption(ep, row, spent(ctx.session, ctx.run_id)),
            buttons(render_id),
            ctx.settings,
            duration=row.duration_s,
        )
    except TelegramNotConfigured:
        log.warning("render not delivered: Telegram not configured", extra=result)
        return result
    return result | {"sent": True, "message_id": message_id}
