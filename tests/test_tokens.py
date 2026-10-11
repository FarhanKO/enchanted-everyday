"""Login health check: warn before Meta's data access runs out and when either login breaks."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from engine.config import Settings
from engine.tokens import check_meta, check_tokens, check_youtube

DHAKA = ZoneInfo("Asia/Dhaka")
NOW = datetime(2027, 1, 5, 10, 0, tzinfo=DHAKA)  # the daily 10:00 check


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        meta_page_access_token="EAApage",
        youtube_client_id="id.apps.googleusercontent.com",
        youtube_client_secret="s3cr3t-value",
        youtube_refresh_token="1//refresh",
    )


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def meta_ok(expires: date):
    stamp = int(datetime(expires.year, expires.month, expires.day, 2, 43, tzinfo=DHAKA).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/debug_token")
        return httpx.Response(
            200,
            json={
                "data": {
                    "type": "PAGE",
                    "is_valid": True,
                    "expires_at": 0,
                    "data_access_expires_at": stamp,
                }
            },
        )

    return handler


def test_meta_quiet_until_the_warning_window(settings):
    assert check_meta(settings, NOW, client(meta_ok(date(2027, 1, 9)))) is None


@pytest.mark.parametrize(
    ("expires", "head"),
    [
        (date(2027, 1, 8), "expires in 3 days: 8 January 2027 at 02:43 (Asia/Dhaka time)"),
        (date(2027, 1, 6), "expires in 1 day: 6 January 2027 at 02:43"),
        (date(2027, 1, 5), "expired on 5 January 2027 at 02:43"),  # 02:43 passed by 10:00
        (date(2027, 1, 1), "expired on 1 January 2027"),
    ],
)
def test_meta_warns_daily_from_three_days_out(settings, expires, head):
    msg = check_meta(settings, NOW, client(meta_ok(expires)))
    assert head in msg
    assert "scripts\\meta_tokens.py" in msg  # the steps come with the warning


def test_meta_later_today_says_today(settings):
    early = NOW.replace(hour=1)  # 01:00, before the 02:43 cut-off
    msg = check_meta(settings, early, client(meta_ok(date(2027, 1, 5))))
    assert "expires TODAY, 5 January 2027 at 02:43" in msg


def test_meta_invalid_token_warns_at_once(settings):
    def handler(request):
        return httpx.Response(
            400, json={"error": {"code": 190, "message": "Session has been invalidated"}}
        )

    msg = check_meta(settings, NOW, client(handler))
    assert msg.startswith("Meta login stopped working")
    assert "Session has been invalidated" in msg


def test_meta_other_errors_and_outages_stay_quiet(settings):
    def rate_limited(request):
        return httpx.Response(400, json={"error": {"code": 4, "message": "rate limit"}})

    def down(request):
        raise httpx.ConnectError("no route")

    assert check_meta(settings, NOW, client(rate_limited)) is None
    assert check_meta(settings, NOW, client(down)) is None


def test_youtube_healthy_refresh_is_quiet(settings):
    def handler(request):
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(200, json={"access_token": "ya29", "expires_in": 3599})

    assert check_youtube(settings, client(handler)) is None


def test_youtube_revoked_login_warns_with_steps(settings):
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    msg = check_youtube(settings, client(handler))
    assert msg.startswith("YouTube login stopped working")
    assert "scripts\\youtube_auth.py" in msg


def test_youtube_outage_stays_quiet(settings):
    def handler(request):
        return httpx.Response(503, text="unavailable")

    assert check_youtube(settings, client(handler)) is None


def test_unconfigured_platforms_are_skipped():
    def handler(request):
        raise AssertionError("no request expected")

    assert check_tokens(Settings(_env_file=None), NOW, client(handler)) == []


def test_no_token_in_messages(settings):
    def handler(request):
        if "graph.facebook.com" in str(request.url):
            return httpx.Response(400, json={"error": {"code": 190, "message": "expired"}})
        return httpx.Response(400, json={"error": "invalid_grant"})

    messages = check_tokens(settings, NOW, client(handler))
    assert len(messages) == 2
    for m in messages:
        assert "EAApage" not in m and "1//refresh" not in m and "s3cr3t-value" not in m
