from __future__ import annotations

import json
import logging
from typing import Any

from telegram import Bot

from db import record_notification
from handlers.student_signal import send_signal
from llm import compose_signal_message

logger = logging.getLogger("placemate.dispatcher")


async def dispatch_event(
    bot: Bot,
    student: dict[str, Any],
    company: dict[str, Any],
    job: dict[str, Any],
    event_id: int,
) -> None:
    try:
        msg = await compose_signal_message(student, company, job)
        await send_signal(bot, student["tg_id"], msg, event_id)
        await record_notification(student["id"], event_id)
        logger.info(
            "Dispatched event %d to student %d for %s",
            event_id, student["id"], company.get("company_name", ""),
        )
    except Exception as e:
        logger.error("Dispatch failed: event=%d student=%d error=%s", event_id, student["id"], e)
