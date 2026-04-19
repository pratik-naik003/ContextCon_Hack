from __future__ import annotations

import logging

from telegram import Bot

from handlers.tutor import signal_keyboard

logger = logging.getLogger("placemate.signal")


async def send_signal(bot: Bot, tg_id: int, message: str, event_id: int) -> None:
    try:
        await bot.send_message(
            chat_id=tg_id,
            text=message,
            parse_mode="Markdown",
            reply_markup=signal_keyboard(event_id),
        )
    except Exception as e:
        logger.error("Failed to send signal to %d: %s", tg_id, e)
