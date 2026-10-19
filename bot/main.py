"""Telegram bot (long polling, so the VPS opens no inbound port).

Only TELEGRAM_OWNER_ID can talk to it; every other update is dropped before any handler runs.
Handles /start, /status, /produce, /redo, /reshoot, /publish and /posted, and the Approve / Skip
buttons. The worker pushes the day's script (engine/stages/deliver.py); /redo turns the story down
for the next backup (engine/redo.py); /produce builds the storyboard, package and video, which
arrives with the buttons (engine/stages/media.py); /reshoot redraws one frame and re-sends the
video. Approve posts to every platform that posts automatically (engine/publish.py) and answers
with the posting kit for the rest (engine/approval.py); /publish retries what failed, and /posted
settles a post that stopped mid-upload.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy.exc import OperationalError
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from engine.approval import DOCUMENT_LIMIT_MB, Refused, decide, posting_kit, prepare_reshoot
from engine.config import get_settings
from engine.db.session import get_engine
from engine.flows import daily_run, run_status, today
from engine.flows import produce as produce_flow
from engine.log import setup_logging
from engine.publish import (
    LABELS,
    NothingToPublish,
    auto_platforms,
    manual_platforms,
    mark_post,
    publish_render,
    report,
)
from engine.redo import RedoRefused, prepare_redo

log = logging.getLogger(__name__)


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "content-engine bot is running.\n"
        "/status - today's run\n"
        "/produce - storyboard, package and video for today's script\n"
        "/redo [note] - turn down today's story and get the next backup, e.g. /redo less sad\n"
        "/reshoot S03 [note] - redraw one frame of today's video, e.g. /reshoot S03 warmer light\n"
        "/publish [platform] - post the approved video where it failed, e.g. /publish instagram\n"
        "/posted <platform> - it's live there after all; never post it again"
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
# one round of posting at a time, so Approve and /publish never upload the same video together
_posting = asyncio.Lock()


async def produce(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    day = today(get_settings())
    info = await asyncio.to_thread(run_status, day)
    stages = (info or {}).get("stages") or {}
    if stages.get("critic", {}).get("status") != "done":
        await msg.reply_text(f"No reviewed script for {day} yet.")
        return
    if stages.get("deliver_render", {}).get("status") == "done":
        await msg.reply_text(f"The video for {day} was already sent. /reshoot S03 redraws a frame.")
        return
    if _busy.locked():
        await msg.reply_text("Busy with your last request; its result will arrive here.")
        return
    async with _busy:
        await msg.reply_text(
            f"Building the storyboard, package and video for {day}. "
            "The package arrives first; the video about 5 minutes later."
        )
        await _produce(msg, day, "Production failed. Send /produce again to resume.")


async def _produce(msg, day, failed: str) -> None:
    try:
        await asyncio.to_thread(produce_flow, run_date=str(day))
    except Exception:
        log.exception("production failed", extra={"run_date": str(day)})
        await msg.reply_text(failed)


async def reshoot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    settings = get_settings()
    day = today(settings)
    if not context.args:
        await msg.reply_text(
            "Which frame? e.g. /reshoot S03, /reshoot S03 warmer light, /reshoot thumbnail"
        )
        return
    frame, note = context.args[0], " ".join(context.args[1:]) or None
    if _busy.locked():
        await msg.reply_text("Busy with your last request; send /reshoot when it's done.")
        return
    async with _busy:
        try:
            asked = await asyncio.to_thread(
                prepare_reshoot, get_engine(), day, frame, settings, note
            )
        except Refused as e:
            await msg.reply_text(str(e))
            return
        how = f' with "{asked["note"]}"' if asked["note"] else ""
        await msg.reply_text(
            f"Redrawing {asked['frame']}{how} (take {asked['take']}) and re-rendering; "
            "the new video arrives in a few minutes. The previous one can no longer be approved."
        )
        await _produce(msg, day, "The reshoot failed. Send /produce to resume it.")


async def on_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Approve / Skip buttons under a video."""
    query = update.callback_query
    if query.from_user.id != get_settings().telegram_owner_id:
        await query.answer()
        return
    action, _, render_id = (query.data or "").partition(":")
    try:
        d = await asyncio.to_thread(decide, get_engine(), int(render_id), action)
    except Refused as e:
        await query.answer(str(e), show_alert=True)
        return
    await query.answer("Approved" if action == "approve" else "Skipped")
    await query.edit_message_reply_markup(reply_markup=None)
    chat = query.message.chat_id
    if action == "skip":
        await context.bot.send_message(chat, "Skipped. Nothing from this video will be posted.")
        return

    settings = get_settings()
    auto, manual = auto_platforms(settings), manual_platforms(settings)
    if auto:
        names = ", ".join(LABELS[p] for p in auto)
        await context.bot.send_message(chat, f"Approved. Posting to {names} now...")
        await context.bot.send_message(chat, await _publish(d.render_id))
    elif settings.dry_run:
        await context.bot.send_message(
            chat, "Approved. DRY_RUN is on, so nothing posts automatically: post it from the kit."
        )
    if not manual:
        return
    if d.thumbnail and d.thumbnail.exists():
        await context.bot.send_photo(chat, d.thumbnail.read_bytes(), caption="Cover image")
    if d.size_mb <= DOCUMENT_LIMIT_MB:
        with d.video.open("rb") as f:
            await context.bot.send_document(
                chat,
                f,
                filename=f"{d.episode.id}.mp4",
                caption="Full-quality file to upload",
                read_timeout=300,
                write_timeout=300,
            )
    else:
        await context.bot.send_message(
            chat, f"The file is {d.size_mb} MB, over Telegram's limit. It's at {d.video}."
        )
    for text in posting_kit(d.episode, d.music_credits, manual):
        await context.bot.send_message(chat, text[:4096])


async def _publish(render_id: int | None = None, platform: str | None = None) -> str:
    """Post (or re-post) the approved video; the outcome as one message."""
    async with _posting:
        try:
            if platform:
                # the owner checked: an interrupted attempt didn't go live, so it may run again
                await asyncio.to_thread(mark_post, get_engine(), platform, "failed", render_id)
            outcomes = await asyncio.to_thread(
                publish_render,
                get_engine(),
                render_id,
                None,
                [platform] if platform else None,
            )
        except NothingToPublish as e:
            return str(e)
        except Exception:
            log.exception("publishing failed", extra={"render_id": render_id})
            return "Posting failed before it reached any platform. Details are in the bot's log."
    return report(outcomes)[:4096] if outcomes else "Nothing to post."


def _platform_arg(args: list[str] | None) -> tuple[str | None, str | None]:
    """(platform, problem) from a command's first argument."""
    if not args:
        return None, None
    name = args[0].lower()
    auto = auto_platforms(get_settings())
    if name not in auto:
        return None, (
            f"{args[0]} doesn't post automatically. Automatic: "
            + (", ".join(auto) or "none (DRY_RUN is on, or no platform is set up)")
        )
    return name, None


async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/publish [platform]: post the latest approved video where it isn't live yet."""
    msg = update.effective_message
    if not auto_platforms(get_settings()):
        await msg.reply_text(
            "Nothing posts automatically: DRY_RUN is on, or no platform is set up."
        )
        return
    platform, problem = _platform_arg(context.args)
    if problem:
        await msg.reply_text(problem)
        return
    if _posting.locked():
        await msg.reply_text("Already posting; the result will arrive here.")
        return
    where = LABELS[platform] if platform else "every automatic platform"
    await msg.reply_text(f"Posting the latest approved video to {where}...")
    await msg.reply_text(await _publish(platform=platform))


async def posted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/posted <platform>: an interrupted post went live after all; record it, never re-post."""
    msg = update.effective_message
    platform, problem = _platform_arg(context.args)
    if problem or not platform:
        await msg.reply_text(problem or "Which platform? e.g. /posted instagram")
        return
    try:
        await asyncio.to_thread(mark_post, get_engine(), platform, "published")
    except NothingToPublish as e:
        await msg.reply_text(str(e))
        return
    await msg.reply_text(f"Noted: it's live on {LABELS[platform]}, so it won't be posted again.")


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
    app.add_handler(CommandHandler("reshoot", reshoot, filters=owner_only, block=False))
    app.add_handler(CommandHandler("publish", publish, filters=owner_only, block=False))
    app.add_handler(CommandHandler("posted", posted, filters=owner_only))
    # buttons can't carry the owner filter; on_decision checks the sender itself. Approve posts,
    # which takes minutes, so it doesn't hold up other updates
    app.add_handler(CallbackQueryHandler(on_decision, pattern=r"^(approve|skip):\d+$", block=False))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    setup_logging(get_settings().log_level)
    build_app().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
