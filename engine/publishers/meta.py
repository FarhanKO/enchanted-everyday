"""Instagram and Facebook Reels through the Graph API, with the Page token (scripts/meta_tokens.py).

Both upload the rendered file straight to Meta (resumable upload to rupload.facebook.com), so no
public video URL is needed. Both set Meta's AI label (`is_ai_generated`) when the render calls for
it. The token rides in the Authorization header, never in a URL, so an error that quotes its URL
can be logged and shown safely.

Instagram: create a REELS container, upload, wait for Meta to process it, publish. Nothing is live
until media_publish succeeds. Facebook: start an upload session, upload, finish with
video_state=PUBLISHED. The Page publishes it after processing; a processing error Meta reports
means it never went live.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from engine.publishers.base import PublishError, PublishRequest, PublishResult

log = logging.getLogger(__name__)

VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
RUPLOAD = "https://rupload.facebook.com"
POLL_S = 5.0
MAX_WAIT_S = 600.0  # Meta processes a 90 s Reel in well under a minute; give it ten
UPLOAD_TIMEOUT_S = 600.0


class _Graph:
    def __init__(
        self, token: str, http: httpx.Client, platform: str, sleep: Callable[[float], None]
    ) -> None:
        self.token = token
        self.http = http
        self.platform = platform
        self.sleep = sleep

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"OAuth {self.token}"}

    def call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            resp = self.http.request(
                method, f"{GRAPH}/{path}", headers=self._auth, timeout=60, **kw
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PublishError(f"couldn't reach {self.platform} ({type(e).__name__})") from e
        if isinstance(data, dict) and "error" in data:
            raise PublishError(f"{self.platform} said: {_meta_error(data['error'])}")
        if resp.status_code >= 400:
            raise PublishError(f"{self.platform} answered HTTP {resp.status_code}")
        return data

    def upload(self, kind: str, upload_id: str, video: Path) -> None:
        """kind: 'ig-api-upload' (Instagram) or 'video-upload' (Facebook)."""
        body = video.read_bytes()
        headers = {**self._auth, "offset": "0", "file_size": str(len(body))}
        url = f"{RUPLOAD}/{kind}/{VERSION}/{upload_id}"
        try:
            resp = self.http.post(url, headers=headers, content=body, timeout=UPLOAD_TIMEOUT_S)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PublishError(f"the upload to {self.platform} failed ({type(e).__name__})") from e
        if not (isinstance(data, dict) and data.get("success")):
            err = data.get("debug_info") or data.get("error") if isinstance(data, dict) else data
            raise PublishError(f"the upload to {self.platform} failed: {_meta_error(err)}")


def _meta_error(err: Any) -> str:
    if not isinstance(err, dict):
        return str(err)[:300]
    text = err.get("error_user_msg") or err.get("message") or err.get("type") or "unknown error"
    code = err.get("code")
    return f"{text} (code {code})" if code else str(text)


def _video(req: PublishRequest) -> Path:
    path = Path(req.video_path)
    if not path.exists():
        raise PublishError(f"the video file is missing: {path}")
    return path


class InstagramPublisher:
    platform = "instagram"

    def __init__(
        self,
        ig_user_id: str,
        token: str,
        http: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user = ig_user_id
        self.graph = _Graph(token, http, "Instagram", sleep)

    def publish(self, req: PublishRequest) -> PublishResult:
        video = _video(req)
        container = self.graph.call(
            "POST",
            f"{self.user}/media",
            data={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": req.caption,
                "share_to_feed": "true",
                "is_ai_generated": "true" if req.ai_generated else "false",
            },
        )["id"]
        self.graph.upload("ig-api-upload", container, video)
        self._wait(container)

        media_id = self.graph.call(
            "POST", f"{self.user}/media_publish", data={"creation_id": container}
        )["id"]
        # live from here on: nothing below may raise
        try:
            url = self.graph.call("GET", media_id, params={"fields": "permalink"}).get("permalink")
        except PublishError as e:
            log.warning("instagram permalink lookup failed: %s", e)
            url = None
        return PublishResult(external_id=media_id, url=url)

    def _wait(self, container: str) -> None:
        waited = 0.0
        while True:
            info = self.graph.call("GET", container, params={"fields": "status_code,status"})
            code = info.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise PublishError(
                    f"Instagram couldn't process the video: {info.get('status') or code}"
                )
            if waited >= MAX_WAIT_S:
                raise PublishError(
                    f"Instagram was still processing the video after {MAX_WAIT_S / 60:.0f} "
                    "minutes; nothing was posted"
                )
            self.graph.sleep(POLL_S)
            waited += POLL_S


class FacebookPublisher:
    platform = "facebook"

    def __init__(
        self,
        page_id: str,
        token: str,
        http: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.page = page_id
        self.graph = _Graph(token, http, "Facebook", sleep)

    def publish(self, req: PublishRequest) -> PublishResult:
        video = _video(req)
        session = self.graph.call(
            "POST", f"{self.page}/video_reels", json={"upload_phase": "start"}
        )
        video_id = str(session["video_id"])
        self.graph.upload("video-upload", video_id, video)
        done = self.graph.call(
            "POST",
            f"{self.page}/video_reels",
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "title": req.title,
                "description": req.caption,
                "is_ai_generated": "true" if req.ai_generated else "false",
            },
        )
        if not done.get("success"):
            raise PublishError("Facebook didn't accept the Reel for publishing")
        self._wait(video_id)
        return PublishResult(external_id=video_id, url=f"https://www.facebook.com/reel/{video_id}")

    def _wait(self, video_id: str) -> None:
        """Raise if Meta reports the Reel failed; other doubts are logged, since it may be live."""
        waited = 0.0
        while waited < MAX_WAIT_S:
            try:
                status = self.graph.call("GET", video_id, params={"fields": "status"}).get(
                    "status", {}
                )
            except PublishError as e:
                log.warning("facebook status check failed; assuming it publishes: %s", e)
                return
            failed = [
                phase
                for phase in ("uploading_phase", "processing_phase", "publishing_phase")
                if (status.get(phase) or {}).get("status") == "error"
            ]
            if failed or status.get("video_status") in ("error", "upload_failed", "expired"):
                detail = (status.get(failed[0]) or {}).get("error") if failed else None
                raise PublishError(
                    "Facebook couldn't publish the Reel: "
                    + (_meta_error(detail) if detail else status.get("video_status", "error"))
                )
            publishing = status.get("publishing_phase") or {}
            if publishing.get("publish_status") == "published" or publishing.get("status") == (
                "completed"
            ):
                return
            self.graph.sleep(POLL_S)
            waited += POLL_S
        log.warning("facebook still processing after %.0f s; assuming it publishes", MAX_WAIT_S)
