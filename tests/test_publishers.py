"""Instagram, Facebook and YouTube uploads against a scripted transport: no network, no posts."""

from __future__ import annotations

import json

import httpx
import pytest

from engine.publishers import PublishError, PublishRequest
from engine.publishers.meta import FacebookPublisher, InstagramPublisher
from engine.publishers.youtube import YouTubePublisher

TOKEN = "page-token-secret"  # noqa: S105 - a fake


class Meta:
    """Answers each Graph / rupload request from a list of (method, path suffix, reply)."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        method, suffix, reply = self.script.pop(0)
        assert request.method == method and request.url.path.endswith(suffix), (
            request.method,
            str(request.url),
        )
        return httpx.Response(200, json=reply)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def req(tmp_path):
    video = tmp_path / "episode.mp4"
    video.write_bytes(b"\x00" * 1234)
    return PublishRequest(
        render_id=1, video_path=str(video), caption="A caption #shortstory", title="T",
        ai_generated=True,
    )  # fmt: skip


def _form(request: httpx.Request) -> dict[str, str]:
    return dict(httpx.QueryParams(request.content.decode()))


def test_instagram_uploads_waits_and_publishes_with_the_ai_label(req):
    meta = Meta(
        ("POST", "/17841/media", {"id": "C1", "uri": "https://rupload.facebook.com/x"}),
        ("POST", "/ig-api-upload/v26.0/C1", {"success": True, "message": "Upload successful."}),
        ("GET", "/C1", {"status_code": "IN_PROGRESS"}),
        ("GET", "/C1", {"status_code": "FINISHED"}),
        ("POST", "/17841/media_publish", {"id": "M9"}),
        ("GET", "/M9", {"permalink": "https://www.instagram.com/reel/abc/"}),
    )
    slept = []
    out = InstagramPublisher("17841", TOKEN, meta.client(), sleep=slept.append).publish(req)

    assert (out.external_id, out.url) == ("M9", "https://www.instagram.com/reel/abc/")
    create = _form(meta.requests[0])
    assert create["media_type"] == "REELS" and create["upload_type"] == "resumable"
    assert create["is_ai_generated"] == "true" and create["caption"] == req.caption
    upload = meta.requests[1]
    assert upload.headers["file_size"] == "1234" and upload.headers["offset"] == "0"
    assert len(upload.content) == 1234
    assert slept == [5.0]
    for r in meta.requests:  # the token rides in a header, never in a URL
        assert r.headers["Authorization"] == f"OAuth {TOKEN}"
        assert TOKEN not in str(r.url)


def test_instagram_processing_error_posts_nothing(req):
    meta = Meta(
        ("POST", "/17841/media", {"id": "C1"}),
        ("POST", "/ig-api-upload/v26.0/C1", {"success": True}),
        ("GET", "/C1", {"status_code": "ERROR", "status": "Error: unsupported audio codec"}),
    )
    with pytest.raises(PublishError, match="unsupported audio codec"):
        InstagramPublisher("17841", TOKEN, meta.client(), sleep=lambda _: None).publish(req)
    assert not meta.script  # media_publish was never called


def test_meta_errors_are_shown_in_metas_own_words(req):
    meta = Meta(
        ("POST", "/17841/media", {"error": {"message": "Invalid OAuth access token", "code": 190}}),
    )
    with pytest.raises(
        PublishError, match=r"Instagram said: Invalid OAuth access token \(code 190\)"
    ):
        InstagramPublisher("17841", TOKEN, meta.client()).publish(req)


def test_a_lost_permalink_doesnt_fail_a_live_post(req):
    meta = Meta(
        ("POST", "/17841/media", {"id": "C1"}),
        ("POST", "/ig-api-upload/v26.0/C1", {"success": True}),
        ("GET", "/C1", {"status_code": "FINISHED"}),
        ("POST", "/17841/media_publish", {"id": "M9"}),
        ("GET", "/M9", {"error": {"message": "temporarily unavailable", "code": 2}}),
    )
    out = InstagramPublisher("17841", TOKEN, meta.client()).publish(req)
    assert (out.external_id, out.url) == ("M9", None)


def test_facebook_reel_starts_uploads_and_finishes_published(req):
    meta = Meta(
        ("POST", "/555/video_reels", {"video_id": "V7", "upload_url": "https://rupload..."}),
        ("POST", "/video-upload/v26.0/V7", {"success": True}),
        ("POST", "/555/video_reels", {"success": True}),
        ("GET", "/V7", {"status": {"video_status": "processing"}}),
        (
            "GET",
            "/V7",
            {"status": {"video_status": "ready", "publishing_phase": {"status": "completed"}}},
        ),
    )
    out = FacebookPublisher("555", TOKEN, meta.client(), sleep=lambda _: None).publish(req)

    assert (out.external_id, out.url) == ("V7", "https://www.facebook.com/reel/V7")
    assert json.loads(meta.requests[0].content) == {"upload_phase": "start"}
    finish = _form(meta.requests[2])
    assert finish["upload_phase"] == "finish" and finish["video_state"] == "PUBLISHED"
    assert finish["is_ai_generated"] == "true" and finish["description"] == req.caption


def test_facebook_processing_error_is_a_failure(req):
    meta = Meta(
        ("POST", "/555/video_reels", {"video_id": "V7"}),
        ("POST", "/video-upload/v26.0/V7", {"success": True}),
        ("POST", "/555/video_reels", {"success": True}),
        (
            "GET",
            "/V7",
            {"status": {"processing_phase": {"status": "error", "error": {"message": "too long"}}}},
        ),
    )
    with pytest.raises(PublishError, match="too long"):
        FacebookPublisher("555", TOKEN, meta.client(), sleep=lambda _: None).publish(req)


def test_youtube_resumable_upload_with_the_synthetic_media_flag(req):
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya-access"})
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": "https://upload.example/session1"})
        return httpx.Response(200, json={"id": "vid1", "status": {"privacyStatus": "public"}})

    http = httpx.Client(transport=httpx.MockTransport(answer))
    out = YouTubePublisher("cid", "secret", "refresh", http).publish(req)

    assert (out.external_id, out.url) == ("vid1", "https://youtube.com/shorts/vid1")
    meta = json.loads(seen[1].content)
    assert meta["status"]["containsSyntheticMedia"] is True
    assert meta["status"]["selfDeclaredMadeForKids"] is False
    assert seen[1].headers["X-Upload-Content-Length"] == "1234"
    assert seen[2].method == "PUT" and len(seen[2].content) == 1234
    assert seen[2].headers["Authorization"] == "Bearer ya-access"


def test_youtube_refused_login_is_reported(req):
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    )
    with pytest.raises(PublishError, match="invalid_grant"):
        YouTubePublisher("cid", "secret", "refresh", http).publish(req)


def test_a_missing_file_is_caught_before_any_upload(req, tmp_path):
    gone = PublishRequest(1, str(tmp_path / "nope.mp4"), "c", "t", True)
    meta = Meta()
    with pytest.raises(PublishError, match="missing"):
        InstagramPublisher("17841", TOKEN, meta.client()).publish(gone)
    assert not meta.requests
