"""The owner's verdict on a rendered video, and the frame redraws before it.

Approve or Skip (the bot's buttons) is recorded once per render on the approvals table. Until
publishing is automated (Phase 3), Approve answers with the posting kit: the full-quality file,
the cover and each platform's copy, with where to switch on each platform's AI label. Every copy
carries the credit line of each music track the render used (CC BY needs it).

/reshoot S03 [note] redraws one frame (or the thumbnail) and re-renders: the note joins that
frame's prompt, and without a note it's simply drawn again. Every other frame comes back from the
cache, so a reshoot costs one image. The video it replaces can no longer be approved.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import Engine, select

from engine.budget import BudgetExceeded, ensure_budget
from engine.config import Settings
from engine.db.models import Approval, Render, Run
from engine.db.session import session_scope
from engine.llm.schemas import Episode
from engine.media.openrouter import image_estimate
from engine.stages import RESHOOT
from engine.stages.deliver import episode_from_db

log = logging.getLogger(__name__)

MAX_NOTE_CHARS = 300
DOCUMENT_LIMIT_MB = 49  # the Bot API's upload limit is 50 MB


class Refused(RuntimeError):
    """Why the owner's request can't be done now, worded for them."""


# ---------------------------------------------------------------- approve / skip


@dataclass
class Decision:
    decision: str
    render_id: int
    video: Path
    thumbnail: Path | None
    size_mb: float
    episode: Episode
    music_credits: list[str] = field(default_factory=list)


def decide(engine: Engine, render_id: int, decision: str, note: str | None = None) -> Decision:
    if decision not in ("approve", "skip"):
        raise ValueError(decision)
    with session_scope(engine) as s:
        row = s.scalars(
            select(Render).where(Render.id == render_id).with_for_update()
        ).one_or_none()
        if row is None:
            raise Refused("That video no longer exists.")
        if row.status == "replaced":
            raise Refused(
                "That video was replaced by a newer one after a /reshoot. Use its buttons."
            )
        if row.status in ("approved", "skipped"):
            raise Refused(f"That video was already {row.status}.")
        s.add(Approval(render_id=render_id, decision=decision, note=note))
        row.status = "approved" if decision == "approve" else "skipped"
        thumb = row.qc_report.get("thumbnail")
        return Decision(
            decision=decision,
            render_id=render_id,
            video=Path(row.uri),
            thumbnail=Path(thumb) if thumb else None,
            size_mb=float(row.qc_report.get("size_mb", 0)),
            episode=episode_from_db(s, row.script_id),
            music_credits=list(row.qc_report.get("music_credits") or []),
        )


AI_LABELS = (
    "Switch on each platform's AI label when you post:\n"
    "- YouTube: Details > Altered content > Yes\n"
    "- Instagram: Advanced settings > Add AI label\n"
    "- Facebook: the AI info toggle in the post settings\n"
    "- TikTok: More options > AI-generated content"
)


def post_copy(text: str, hashtags: list[str], credits: Sequence[str] = ()) -> str:
    """A platform's copy as posted: the text, the music credits, then any hashtags it lacks."""
    if credits:
        text = f"{text}\n\n" + "\n".join(credits)
    missing = [t for t in hashtags if t.lower() not in text.lower()]
    return f"{text}\n\n{' '.join(missing)}" if missing else text


def posting_kit(ep: Episode, credits: Sequence[str] = ()) -> list[str]:
    """The copy to paste, one message per platform so each is easy to copy on a phone."""
    p = ep.package.platforms
    return [
        f"Posting kit: {ep.package.title}\n\n{AI_LABELS}\n\n"
        f"Pin as the first comment: {ep.package.comment_prompt}",
        f"YOUTUBE title\n{p.youtube_title}",
        f"YOUTUBE description\n{post_copy(p.youtube_description, p.hashtags, credits)}",
        f"INSTAGRAM caption\n{post_copy(p.instagram_caption, p.hashtags, credits)}",
        f"FACEBOOK caption\n{post_copy(p.facebook_caption, p.hashtags, credits)}",
        f"TIKTOK caption\n{post_copy(p.tiktok_caption, p.hashtags, credits)}",
    ]


# ---------------------------------------------------------------- reshoot


def prepare_reshoot(
    engine: Engine, run_date: date, frame: str, settings: Settings, note: str | None = None
) -> dict:
    """Queue a redraw of one frame and clear the stages that follow; the production flow then
    redraws, re-renders and re-sends. Raises Refused when it can't."""
    frame = frame.strip()
    frame = "thumbnail" if frame.lower() in ("thumb", "thumbnail", "cover") else frame.upper()
    with session_scope(engine) as s:
        run = s.scalars(select(Run).where(Run.run_date == run_date).with_for_update()).one_or_none()
        stages = dict(run.stages or {}) if run else {}
        if any(v.get("status") == "running" for v in stages.values()):
            raise Refused(f"Production for {run_date} is still running; wait for the video.")
        if stages.get("images", {}).get("status") != "done":
            raise Refused(f"There's no video for {run_date} yet. Send /produce first.")
        render_id = stages.get("render", {}).get("output", {}).get("render_id")
        current = s.get(Render, render_id) if render_id else None
        if current is not None and current.status == "approved":
            raise Refused(f"The video for {run_date} is already approved.")

        shots = stages["images"]["output"]["shots"]
        if frame != "thumbnail" and frame not in shots:
            raise Refused(f"No frame {frame}. Frames are {', '.join(shots)} and thumbnail.")
        try:
            ensure_budget(
                s, run.id, settings.daily_spend_cap_usd, image_estimate(settings.image_model)
            )
        except BudgetExceeded:
            raise Refused(
                f"A redraw would pass the ${settings.daily_spend_cap_usd:.2f} daily spend cap "
                "(DAILY_SPEND_CAP_USD)."
            ) from None

        asks = dict(stages.get("reshoot", {}).get("output") or {})
        notes, takes = dict(asks.get("notes", {})), dict(asks.get("takes", {}))
        note = (note or "").strip()[:MAX_NOTE_CHARS] or None
        if note:
            notes[frame] = note
        takes[frame] = takes.get(frame, 1) + 1
        history = [
            *asks.get("history", []),
            {"frame": frame, "note": note, "at": datetime.now(UTC).isoformat()},
        ]
        stages["reshoot"] = {
            "status": "done",
            "output": {"notes": notes, "takes": takes, "history": history},
        }
        for name in RESHOOT:
            stages.pop(name, None)
        run.stages = stages
        if current is not None and current.status in ("ready", "qc_failed"):
            current.status = "replaced"
        log.info("reshoot queued", extra={"run_date": str(run_date), "frame": frame})
        return {"frame": frame, "note": note, "take": takes[frame], "reshoots": len(history)}
