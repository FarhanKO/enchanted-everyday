"""YouTube Shorts through the Data API v3, with the refresh token from scripts/youtube_auth.py.

One resumable upload: the metadata first (which returns an upload URL), then the file. The video
is live, or private, the moment the second request succeeds. Until the API audit passes, YouTube
locks every API upload to private, so YOUTUBE_UPLOAD_ENABLED stays false until then.

A vertical video under three minutes is a Short; no flag is needed. `containsSyntheticMedia` is
YouTube's "altered or synthetic content" disclosure.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from engine.publishers.base import PublishError, PublishRequest, PublishResult

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CATEGORY = "1"  # Film & Animation
MAX_TITLE = 100
MAX_DESCRIPTION = 5000  # bytes
UPLOAD_TIMEOUT_S = 600.0


def _clean(text: str) -> str:
    return text.replace("<", "").replace(">", "")  # YouTube rejects angle brackets


def _google_error(resp: httpx.Response) -> str:
    try:
        err: Any = resp.json().get("error", {})
    except ValueError:
        return f"HTTP {resp.status_code}"
    if isinstance(err, str):  # the token endpoint: {"error": "invalid_grant", ...}
        return err
    reasons = [e.get("reason") for e in err.get("errors", []) if e.get("reason")]
    message = err.get("message") or f"HTTP {resp.status_code}"
    return f"{message} ({', '.join(reasons)})" if reasons else message


class YouTubePublisher:
    platform = "youtube"

    def __init__(
        self, client_id: str, client_secret: str, refresh_token: str, http: httpx.Client
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.http = http

    def _access_token(self) -> str:
        try:
            resp = self.http.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
        except httpx.HTTPError as e:
            raise PublishError(f"couldn't reach Google ({type(e).__name__})") from e
        token = resp.json().get("access_token") if resp.status_code == 200 else None
        if not token:
            raise PublishError(f"Google refused the YouTube login: {_google_error(resp)}")
        return token

    def publish(self, req: PublishRequest) -> PublishResult:
        video = Path(req.video_path)
        if not video.exists():
            raise PublishError(f"the video file is missing: {video}")
        body = video.read_bytes()
        auth = {"Authorization": f"Bearer {self._access_token()}"}
        metadata = {
            "snippet": {
                "title": _clean(req.title)[:MAX_TITLE],
                "description": _clean(req.caption)
                .encode()[:MAX_DESCRIPTION]
                .decode(errors="ignore"),
                "categoryId": CATEGORY,
                "defaultLanguage": "en",
                "defaultAudioLanguage": "en",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": req.ai_generated,
            },
        }
        try:
            start = self.http.post(
                UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    **auth,
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(len(body)),
                },
                json=metadata,
                timeout=60,
            )
        except httpx.HTTPError as e:
            raise PublishError(f"couldn't reach YouTube ({type(e).__name__})") from e
        location = start.headers.get("Location")
        if start.status_code != 200 or not location:
            raise PublishError(f"YouTube refused the upload: {_google_error(start)}")

        try:
            done = self.http.put(
                location,
                headers={**auth, "Content-Type": "video/mp4"},
                content=body,
                timeout=UPLOAD_TIMEOUT_S,
            )
        except httpx.HTTPError as e:
            raise PublishError(f"the upload to YouTube failed ({type(e).__name__})") from e
        if done.status_code not in (200, 201):
            raise PublishError(f"the upload to YouTube failed: {_google_error(done)}")
        data = done.json()
        privacy = (data.get("status") or {}).get("privacyStatus")
        if privacy and privacy != "public":
            log.warning("youtube kept the upload %s (API audit pending?)", privacy)
        return PublishResult(external_id=data["id"], url=f"https://youtube.com/shorts/{data['id']}")
