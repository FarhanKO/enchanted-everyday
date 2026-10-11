"""Daily check of the platform logins, with the fix-it steps sent to Telegram.

Meta: the Page token never expires, but its data access does (90 days after the token was made).
Meta reports that date for the token itself, so we warn from LOGIN_WARN_DAYS before it and every
day after, and at once if the token stops working. YouTube: a refresh token has no expiry date;
Google cuts it off on a password change, revoked access or 6 months unused. We try a refresh and
warn at once if Google refuses it.

A platform that isn't configured is skipped, and a check that can't reach the platform says
nothing (it's logged): only a definite answer from Meta or Google triggers a message. Tokens ride
in URLs, so httpx errors are reduced to their type before they're logged.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from engine.config import Settings, get_settings

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v26.0"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret

META_STEPS = """\
To renew (about 5 minutes, on your PC):
1. Open developers.facebook.com/tools/explorer and pick the app "Enchanted Everyday Uploader".
2. Click "Get User Access Token" and tick: pages_show_list, pages_read_engagement, \
pages_manage_posts, read_insights, business_management, instagram_basic, \
instagram_content_publish, instagram_manage_insights.
3. Click "Generate Access Token" and allow The Enchanted Everyday Page and Instagram account.
4. In the project folder run: .venv\\Scripts\\python.exe scripts\\meta_tokens.py
5. Type the App ID, then copy the App Secret (App settings > Basic > Show) and the Explorer \
token when it asks.
Done when it says "Page token: never expires". If the pipeline runs on the VPS, copy the three \
META_ lines from your .env to the server's .env."""

YOUTUBE_STEPS = """\
To sign in again (2 minutes, on your PC):
1. In the project folder run: .venv\\Scripts\\python.exe scripts\\youtube_auth.py
2. In the browser pick your account, then The Enchanted Everyday channel.
3. On "Google hasn't verified this app": Advanced > Go to Enchanted Everyday Uploader (unsafe), \
tick every box, Continue.
4. Wait for "Done. Channel: The Enchanted Everyday" in the terminal.
If the pipeline runs on the VPS, copy the YOUTUBE_REFRESH_TOKEN line to the server's .env.
Usual causes: a Google password change, the app's access removed at \
myaccount.google.com/permissions, or the app set back to Testing in Google Cloud."""


def _fmt(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def check_meta(settings: Settings, now: datetime, http: httpx.Client) -> str | None:
    if not settings.meta_page_access_token:
        return None
    token = settings.meta_page_access_token.get_secret_value()
    try:
        data = http.get(
            f"{GRAPH}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=30,
        ).json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("meta token check skipped: %s", type(e).__name__)
        return None

    if "error" in data:
        err = data["error"]
        if err.get("code") != 190:  # 190: the token itself is invalid or expired
            log.warning("meta token check skipped: Meta error %s", err.get("code"))
            return None
        return (
            "Meta login stopped working: Instagram and Facebook posting is paused until you "
            f"renew.\nMeta says: {err.get('message', 'invalid token')}\n\n{META_STEPS}"
        )

    info = data.get("data", {})
    if not info.get("is_valid", False):
        return (
            "Meta login stopped working: Instagram and Facebook posting is paused until you "
            f"renew.\n\n{META_STEPS}"
        )
    expires_at = info.get("data_access_expires_at") or 0
    if not expires_at:
        return None
    expires = datetime.fromtimestamp(expires_at, settings.tz)
    deadline = f"{_fmt(expires.date())} at {expires:%H:%M} ({settings.timezone} time)"
    days = (expires.date() - now.date()).days
    if days > settings.login_warn_days:
        return None
    if expires <= now:
        head = (
            f"Meta access expired on {deadline}. Instagram and Facebook posting is paused "
            "until you renew."
        )
    elif days == 0:
        head = f"Meta access expires TODAY, {deadline}. Renew now to keep posting."
    else:
        head = (
            f"Meta access expires in {days} day{'s' if days != 1 else ''}: {deadline}. "
            "After that, Instagram and Facebook posting stops."
        )
    return f"{head}\n\n{META_STEPS}"


def check_youtube(settings: Settings, http: httpx.Client) -> str | None:
    if not (
        settings.youtube_client_id
        and settings.youtube_client_secret
        and settings.youtube_refresh_token
    ):
        return None
    try:
        resp = http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret.get_secret_value(),
                "refresh_token": settings.youtube_refresh_token.get_secret_value(),
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("youtube token check skipped: %s", type(e).__name__)
        return None

    if "access_token" in data:
        return None
    error = data.get("error", f"HTTP {resp.status_code}")
    if error == "invalid_grant":
        reason = "Google refused the saved login (invalid_grant)."
    elif error in ("invalid_client", "unauthorized_client"):
        reason = (
            f"Google refused the app's client ID/secret ({error}). Check YOUTUBE_CLIENT_ID and "
            "YOUTUBE_CLIENT_SECRET in .env match the Desktop client in Google Cloud > Clients."
        )
    else:
        log.warning("youtube token check skipped: Google error %s", error)
        return None
    return (
        f"YouTube login stopped working: uploads to YouTube will fail until you sign in again.\n"
        f"{reason}\n\n{YOUTUBE_STEPS}"
    )


def check_tokens(
    settings: Settings | None = None,
    now: datetime | None = None,
    http: httpx.Client | None = None,
) -> list[str]:
    """The messages to send; empty when every configured login is healthy."""
    s = settings or get_settings()
    when = now or datetime.now(s.tz)
    client = http or httpx.Client()
    try:
        return [m for m in (check_meta(s, when, client), check_youtube(s, client)) if m]
    finally:
        if http is None:
            client.close()
