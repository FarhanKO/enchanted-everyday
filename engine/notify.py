"""Operator alerts to Telegram, plus the dead-man's-switch ping.

The worker sends plain Bot API messages; the interactive approval flow lives in bot/.
Alerting must never crash the thing it is reporting on, so every call here swallows its errors.
"""

from __future__ import annotations

import logging

import httpx

from engine.config import Settings, get_settings

log = logging.getLogger(__name__)


def alert(text: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    if not (s.telegram_bot_token and s.telegram_owner_id):
        log.warning("alert not sent: Telegram not configured", extra={"alert": text})
        return False
    try:
        httpx.post(
            f"https://api.telegram.org/bot{s.telegram_bot_token.get_secret_value()}/sendMessage",
            json={"chat_id": s.telegram_owner_id, "text": text[:4000]},
            timeout=15,
        ).raise_for_status()
        return True
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
