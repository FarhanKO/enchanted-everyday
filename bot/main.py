"""Telegram bot (long polling, so the VPS opens no inbound port).

Only TELEGRAM_OWNER_ID can talk to it; every other update is dropped before any handler runs.
Phase 0: /start, /status. Phase 1 adds script delivery; Phase 2 adds voice intake and the
Approve / Redo / Skip buttons.
"""

from __future__ import annotations

import asyncio
import json
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from engine.config import get_settings
from engine.flows import run_status, today
from engine.log import setup_logging

log = logging.getLogger(__name__)


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "content-engine bot is running.\n/status - today's run"
    )


async def status(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    day = today(get_settings())
    info = await asyncio.to_thread(run_status, day)
    if info is None:
        text = f"No run yet for {day}."
    else:
        stages = {k: v.get("status") for k, v in (info["stages"] or {}).items()}
        text = (
            f"Run {day}: {info['status']}\n"
            f"Stages: {json.dumps(stages)}\n"
            f"LLM spend: ${info['llm_cost_usd']}"
        )
    await update.effective_message.reply_text(text)


def build_app() -> Application:
    settings = get_settings()
    if not (settings.telegram_bot_token and settings.telegram_owner_id):
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_ID must be set")

    owner_only = filters.User(user_id=settings.telegram_owner_id)
    app = Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    app.add_handler(CommandHandler("start", start, filters=owner_only))
    app.add_handler(CommandHandler("status", status, filters=owner_only))
    return app


def main() -> None:
    setup_logging(get_settings().log_level)
    build_app().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
