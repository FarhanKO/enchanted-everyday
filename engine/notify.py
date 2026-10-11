"""Operator alerts to Telegram, plus the dead-man's-switch ping.

The worker sends plain Bot API messages; the interactive approval flow lives in bot/.
Alerting must never crash the thing it is reporting on, so alert() swallows its errors;
send_message() and send_document() raise, for callers that must know delivery worked.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from engine.config import Settings, get_settings

log = logging.getLogger(__name__)

TEXT_LIMIT = 4096  # Telegram's limits
CAPTION_LIMIT = 1024


class TelegramError(RuntimeError):
    pass


class TelegramNotConfigured(TelegramError):
    pass


def _post(method: str, s: Settings, **kwargs: Any) -> dict:
    if not (s.telegram_bot_token and s.telegram_owner_id):
        raise TelegramNotConfigured("TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_ID are not set")
    url = f"https://api.telegram.org/bot{s.telegram_bot_token.get_secret_value()}/{method}"
    try:
        resp = httpx.post(url, timeout=300, **kwargs)  # long enough for a 50 MB upload
    except httpx.HTTPError as e:
        # httpx puts the URL, and so the bot token, in its messages; never let it reach logs
        raise TelegramError(f"{method} failed: {type(e).__name__}") from None
    if resp.is_error:
        raise TelegramError(f"{method} failed: HTTP {resp.status_code} {resp.text[:300]}")
    return resp.json().get("result") or {}


def send_message(text: str, settings: Settings | None = None) -> None:
    """Send plain text to the owner. Raises on failure; use alert() where failure must not."""
    s = settings or get_settings()
    _post("sendMessage", s, json={"chat_id": s.telegram_owner_id, "text": text[:TEXT_LIMIT]})


def send_document(
    filename: str, content: bytes, caption: str = "", settings: Settings | None = None
) -> None:
    s = settings or get_settings()
    _post(
        "sendDocument",
        s,
        data={"chat_id": s.telegram_owner_id, "caption": caption[:CAPTION_LIMIT]},
        files={"document": (filename, content)},
    )


def send_video(
    path: Path,
    caption: str = "",
    buttons: list[list[dict]] | None = None,
    settings: Settings | None = None,
    *,
    width: int = 720,
    height: int = 1280,
    duration: float | None = None,
) -> int:
    """Upload a video (Bot API limit: 50 MB) with optional inline buttons; return the message id."""
    s = settings or get_settings()
    data: dict[str, Any] = {
        "chat_id": s.telegram_owner_id,
        "caption": caption[:CAPTION_LIMIT],
        "supports_streaming": "true",
        "width": width,
        "height": height,
    }
    if duration:
        data["duration"] = round(duration)
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    with path.open("rb") as f:
        result = _post("sendVideo", s, data=data, files={"video": (path.name, f, "video/mp4")})
    return int(result["message_id"])


def send_photo(path: Path, caption: str = "", settings: Settings | None = None) -> None:
    s = settings or get_settings()
    with path.open("rb") as f:
        _post(
            "sendPhoto",
            s,
            data={"chat_id": s.telegram_owner_id, "caption": caption[:CAPTION_LIMIT]},
            files={"photo": (path.name, f)},
        )


def alert(text: str, settings: Settings | None = None) -> bool:
    try:
        send_message(text, settings)
        return True
    except TelegramNotConfigured:
        log.warning("alert not sent: Telegram not configured", extra={"alert": text})
    except Exception:
        log.exception("alert failed", extra={"alert": text})
    return False


def ping_healthcheck(suffix: str = "", settings: Settings | None = None) -> None:
    """suffix: "" for success, "/start" or "/fail" (healthchecks.io convention)."""
    s = settings or get_settings()
    if not s.healthcheck_ping_url:
        return
    try:
        httpx.get(s.healthcheck_ping_url.rstrip("/") + suffix, timeout=10)
    except Exception:
        log.warning("healthcheck ping failed", exc_info=True)
