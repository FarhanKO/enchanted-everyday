"""Publisher contract and the idempotency guard every platform goes through.

`publish_once` checks the posts table before uploading, so a retried run never double-posts.
Platform modules (youtube, instagram, facebook, tiktok) arrive in Phase 3 and only implement
`Publisher.publish`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert

from engine.db.models import Post
from engine.db.session import session_scope

log = logging.getLogger(__name__)


class PublishStateUnknown(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishRequest:
    render_id: int
    video_path: str  # local file, for platforms that take an upload
    video_url: str  # public R2 URL, for platforms that fetch (Meta)
    caption: str
    title: str
    ai_generated: bool  # sets containsSyntheticMedia / is_ai_generated


@dataclass(frozen=True)
class PublishResult:
    external_id: str
    url: str | None = None


class Publisher(Protocol):
    platform: str

    def publish(self, req: PublishRequest) -> PublishResult: ...


def publish_once(engine: Engine, publisher: Publisher, req: PublishRequest) -> Post:
    """Publish unless this render is already live on this platform. Errors are logged on the row."""
    with session_scope(engine) as s:
        s.execute(
            insert(Post)
            .values(
                render_id=req.render_id, platform=publisher.platform, status="pending", attempts=0
            )
            .on_conflict_do_nothing(index_elements=["render_id", "platform"])
        )
        post = s.scalars(
            select(Post)
            .where(Post.render_id == req.render_id, Post.platform == publisher.platform)
            .with_for_update()
        ).one()
        if post.status == "published":
            log.info("already published; skipping", extra={"platform": publisher.platform})
            return post
        if post.status == "publishing":
            # A previous attempt died mid-upload: the post may or may not be live. Retrying could
            # double-post, so a human checks the platform and resets the row.
            raise PublishStateUnknown(
                f"post {post.id} ({publisher.platform}) was interrupted mid-upload; "
                "check the platform, then set status to 'published' or 'failed'"
            )
        post.status = "publishing"
        post.attempts += 1
        post_id = post.id

    try:
        result = publisher.publish(req)
    except Exception as e:
        with session_scope(engine) as s:
            post = s.get_one(Post, post_id)
            post.status = "failed"
            post.last_error = repr(e)[:2000]
        raise

    with session_scope(engine) as s:
        post = s.get_one(Post, post_id)
        post.status = "published"
        post.external_id = result.external_id
        post.url = result.url
        post.last_error = None
        post.published_at = datetime.now(UTC)
        return post
