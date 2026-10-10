"""Telegram bot (long polling, so the VPS opens no inbound port).

Only TELEGRAM_OWNER_ID can talk to it; every other update is dropped before any handler runs.
Handles /start, /status, /produce and /redo. The worker pushes the day's script
(engine/stages/deliver.py); /produce then builds its storyboard and package, and /redo turns the
story down for the next backup (engine/redo.py). Phase 2 replaces /produce with the voice note and
adds the Approve / Redo / Skip buttons here.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy.exc import OperationalError
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from engine.config import get_settings
from engine.db.session import get_engine
from engine.flows import daily_run, run_status, today
from engine.flows import produce as produce_flow
from engine.log import setup_logging
from engine.redo import RedoRefused, prepare_redo

log = logging.getLogger(__name__)


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "content-engine bot is running.\n"
        "/status - today's run\n"
        "/produce - storyboard and package for today's script\n"
        "/redo [note] - turn down today's story and get the next backup, e.g. /redo less sad"
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
        if info["redos"]:
            text += f"\nRedos: {info['redos']}"
    await update.effective_message.reply_text(text)


# one long job at a time: production and a redo both rewrite the day's run
_busy = asyncio.Lock()


async def produce(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    day = today(get_settings())
    info = await asyncio.to_thread(run_status, day)
    stages = (info or {}).get("stages") or {}
    if stages.get("critic", {}).get("status") != "done":
        await msg.reply_text(f"No reviewed script for {day} yet.")
        return
    if stages.get("deliver_package", {}).get("status") == "done":
        await msg.reply_text(f"The package for {day} was already sent.")
        return
    if _busy.locked():
        await msg.reply_text("Busy with your last request; its result will arrive here.")
        return
    async with _busy:
        await msg.reply_text(f"Building the storyboard and package for {day}...")
        try:
            await asyncio.to_thread(produce_flow, run_date=str(day))
        except Exception:
            log.exception("production failed", extra={"run_date": str(day)})
            await msg.reply_text("Production failed. Send /produce again to retry.")


async def redo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    settings = get_settings()
    day = today(settings)
    note = " ".join(context.args or []) or None
    if _busy.locked():
        await msg.reply_text("Busy with your last request; send /redo when it's done.")
        return
    async with _busy:
        try:
            started = await asyncio.to_thread(prepare_redo, get_engine(), day, settings, note)
        except RedoRefused as e:
            await msg.reply_text(str(e))
            return
        if started["resumed"]:
            await msg.reply_text(f'Finishing the unfinished redo: "{started["title"]}"...')
        else:
            left = started["backups_left"]
            await msg.reply_text(
                f'Turned down "{started["rejected_title"]}".\n'
                f'Writing "{started["title"]}" instead'
                + (" with your note" if note else "")
                + f" ({left} backup{'' if left == 1 else 's'} left after this)..."
            )
        try:
            await asyncio.to_thread(daily_run, run_date=str(day))
        except Exception:
            log.exception("redo failed", extra={"run_date": str(day)})
            await msg.reply_text("The redo failed. Send /redo again to finish it.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every unhandled error, and tell the owner when one of their commands hit it."""
    err = context.error
    log.error("unhandled bot error", exc_info=err)
    # updates only reach handlers through the owner filter, so this replies to the owner;
    # polling errors (update is None) are logged only
    if not (isinstance(update, Update) and update.effective_message):
        return
    if isinstance(err, OperationalError):
        text = "Can't reach the database. Is the stack running (docker compose up)?"
    else:
        text = f"That failed ({type(err).__name__}). Details are in the bot's log."
    await update.effective_message.reply_text(text)


def build_app() -> Application:
    settings = get_settings()
    if not (settings.telegram_bot_token and settings.telegram_owner_id):
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_ID must be set")

    owner_only = filters.User(user_id=settings.telegram_owner_id)
    app = Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    app.add_handler(CommandHandler("start", start, filters=owner_only))
    app.add_handler(CommandHandler("status", status, filters=owner_only))
    # block=False: these take minutes, and /status should keep answering meanwhile
    app.add_handler(CommandHandler("produce", produce, filters=owner_only, block=False))
    app.add_handler(CommandHandler("redo", redo, filters=owner_only, block=False))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    setup_logging(get_settings().log_level)
    build_app().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
