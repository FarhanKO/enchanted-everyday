"""The bot answers the owner when a command fails, instead of going quiet."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import OperationalError
from telegram import Update

from bot.main import on_error


def _fail(update, error) -> None:
    asyncio.run(on_error(update, SimpleNamespace(error=error)))


def _update() -> MagicMock:
    update = MagicMock(spec=Update)
    update.effective_message.reply_text = AsyncMock()
    return update


def test_database_down_is_explained():
    update = _update()
    _fail(update, OperationalError("select 1", {}, OSError("failed to resolve host 'postgres'")))
    (text,), _ = update.effective_message.reply_text.call_args
    assert text.startswith("Can't reach the database")


def test_other_errors_name_their_type_only():
    update = _update()
    _fail(update, ValueError("internal detail"))
    (text,), _ = update.effective_message.reply_text.call_args
    assert "ValueError" in text and "internal detail" not in text


def test_polling_errors_are_only_logged():
    _fail(None, RuntimeError("Conflict: terminated by other getUpdates request"))
