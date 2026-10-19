"""Phase 3: post an approved video to every platform that posts automatically.

Approve in the bot calls `publish_render`. Instagram and Facebook post when their Meta settings
are filled in; YouTube once YOUTUBE_UPLOAD_ENABLED is on (after the API audit); TikTok stays manual.
DRY_RUN=true posts nothing anywhere: every platform gets the posting kit instead.

Each platform goes through `publish_once`, so a retry (/publish) posts only where the last attempt
failed. A post interrupted mid-upload is left for the owner to check: /posted marks it live, and
/publish <platform> tries it again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import Engine, select

from engine.approval import post_copy
from engine.config import Settings, get_settings
from engine.db.models import Post, Render
from engine.db.session import session_scope
from engine.llm.schemas import Episode
from engine.publishers import (
    Publisher,
    PublishError,
    PublishRequest,
    PublishStateUnknown,
    publish_once,
)
from engine.publishers.meta import FacebookPublisher, InstagramPublisher
from engine.publishers.youtube import YouTubePublisher
from engine.stages.deliver import episode_from_db

log = logging.getLogger(__name__)

PLATFORMS = ("youtube", "instagram", "facebook", "tiktok")  # the posting kit's order
LABELS = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "tiktok": "TikTok",
}


class NothingToPublish(RuntimeError):
    """Why there's nothing to post, worded for the owner."""


@dataclass(frozen=True)
class Outcome:
    platform: str
    status: str  # published | failed | unknown
    url: str | None = None
    error: str | None = None


def auto_platforms(settings: Settings) -> list[str]:
    """The platforms that post on Approve, in posting order. None while DRY_RUN is on."""
    if settings.dry_run:
        return []
    out = []
    if settings.meta_page_access_token and settings.meta_ig_user_id:
        out.append("instagram")
    if settings.meta_page_access_token and settings.meta_page_id:
        out.append("facebook")
    if (
        settings.youtube_upload_enabled
        and settings.youtube_client_id
        and settings.youtube_client_secret
        and settings.youtube_refresh_token
    ):
        out.append("youtube")
    return out


def manual_platforms(settings: Settings) -> list[str]:
    auto = auto_platforms(settings)
    return [p for p in PLATFORMS if p not in auto]


def build_publisher(platform: str, settings: Settings, http: httpx.Client) -> Publisher:
    if platform in ("instagram", "facebook"):
        assert settings.meta_page_access_token
        token = settings.meta_page_access_token.get_secret_value()
        if platform == "instagram":
            return InstagramPublisher(settings.meta_ig_user_id, token, http)
        return FacebookPublisher(settings.meta_page_id, token, http)
    if platform == "youtube":
        assert settings.youtube_client_secret and settings.youtube_refresh_token
        return YouTubePublisher(
            settings.youtube_client_id,
            settings.youtube_client_secret.get_secret_value(),
            settings.youtube_refresh_token.get_secret_value(),
            http,
        )
    raise ValueError(f"{platform} doesn't post automatically")


def request_for(
    platform: str,
    ep: Episode,
    render_id: int,
    video: Path,
    credits: Sequence[str] = (),
    ai_generated: bool = True,
) -> PublishRequest:
    p = ep.package.platforms
    caption = {
        "youtube": p.youtube_description,
        "instagram": p.instagram_caption,
        "facebook": p.facebook_caption,
        "tiktok": p.tiktok_caption,
    }[platform]
    return PublishRequest(
        render_id=render_id,
        video_path=str(video),
        caption=post_copy(caption, p.hashtags, credits),
        title=p.youtube_title if platform == "youtube" else ep.package.title,
        ai_generated=ai_generated,
    )


@dataclass
class _Approved:
    render_id: int
    video: Path
    episode: Episode
    credits: list[str]
    ai_generated: bool


def _approved(engine: Engine, render_id: int | None) -> _Approved:
    """The given render, or the latest approved one; it must be approved."""
    with session_scope(engine) as s:
        if render_id is None:
            row = s.scalars(
                select(Render).where(Render.status == "approved").order_by(Render.id.desc())
            ).first()
            if row is None:
                raise NothingToPublish("No approved video yet. Approve one first.")
        else:
            row = s.get(Render, render_id)
            if row is None or row.status != "approved":
                raise NothingToPublish("That video isn't approved, so nothing was posted.")
        return _Approved(
            render_id=row.id,
            video=Path(row.uri),
            episode=episode_from_db(s, row.script_id),
            credits=list(row.qc_report.get("music_credits") or []),
            ai_generated=row.ai_generated,
        )


def publish_render(
    engine: Engine,
    render_id: int | None = None,
    settings: Settings | None = None,
    platforms: Sequence[str] | None = None,
    http: httpx.Client | None = None,
    make_publisher: Callable[[str, Settings, httpx.Client], Publisher] = build_publisher,
) -> list[Outcome]:
    """Post the render everywhere it posts automatically (or only `platforms`), in order.

    One platform failing never stops the next. Returns one outcome per platform tried.
    """
    s = settings or get_settings()
    approved = _approved(engine, render_id)
    targets = [p for p in auto_platforms(s) if platforms is None or p in platforms]
    client = http or httpx.Client()
    outcomes = []
    try:
        for platform in targets:
            req = request_for(
                platform,
                approved.episode,
                approved.render_id,
                approved.video,
                approved.credits,
                approved.ai_generated,
            )
            try:
                post = publish_once(engine, make_publisher(platform, s, client), req)
                outcomes.append(Outcome(platform, "published", url=post.url))
            except PublishStateUnknown:
                outcomes.append(Outcome(platform, "unknown"))
            except PublishError as e:
                outcomes.append(Outcome(platform, "failed", error=str(e)))
            except Exception as e:  # a bug, not the platform: keep going, but keep the trace
                log.exception("publishing failed", extra={"platform": platform})
                outcomes.append(Outcome(platform, "failed", error=f"{type(e).__name__}: {e}"[:300]))
    finally:
        if http is None:
            client.close()
    log.info(
        "published",
        extra={"render_id": approved.render_id, "outcomes": [o.status for o in outcomes]},
    )
    return outcomes


def mark_post(engine: Engine, platform: str, status: str, render_id: int | None = None) -> int:
    """Settle a post interrupted mid-upload, after the owner checked the platform.

    status 'published': it's live, never post it again. 'failed': it isn't, so /publish may
    retry. Returns the render id. Raises NothingToPublish when there's nothing to settle.
    """
    if status not in ("published", "failed"):
        raise ValueError(status)
    approved = _approved(engine, render_id)
    with session_scope(engine) as s:
        post = s.scalars(
            select(Post)
            .where(Post.render_id == approved.render_id, Post.platform == platform)
            .with_for_update()
        ).one_or_none()
        if post is None:
            if status == "published":
                s.add(Post(render_id=approved.render_id, platform=platform, status="published"))
            # 'failed' with no attempt yet: nothing to reset
        elif post.status == "published" and status == "failed":
            raise NothingToPublish(f"{LABELS[platform]} already has it. Nothing to retry.")
        else:
            post.status = status
            post.last_error = None if status == "published" else "reset by the owner"
    return approved.render_id


def report(outcomes: Sequence[Outcome]) -> str:
    """The outcomes as one Telegram message."""
    lines = []
    for o in outcomes:
        name = LABELS[o.platform]
        if o.status == "published":
            lines.append(f"Posted to {name}" + (f": {o.url}" if o.url else "."))
        elif o.status == "unknown":
            lines.append(
                f"{name}: an earlier attempt stopped mid-upload, so it may already be live. "
                f"Check {name}. If the Reel is there, send /posted {o.platform}. If not, send "
                f"/publish {o.platform} to post it again."
            )
        else:
            lines.append(f"{name} failed: {o.error}")
    if any(o.status == "failed" for o in outcomes):
        lines.append("Send /publish to try the failed ones again, or post by hand from the kit.")
    return "\n\n".join(lines)
