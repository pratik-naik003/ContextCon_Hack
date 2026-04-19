from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from crustdata import Crustdata
from db import get_student_by_tg, get_latest_event_for_student
from llm import draft_cold_email
from security import message_limiter, sanitize_error

logger = logging.getLogger("placemate.apply")


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = q.from_user.id

    if not message_limiter.is_allowed(tg_id):
        return

    try:
        student = await get_student_by_tg(tg_id)
        if not student:
            await q.message.reply_text("Please complete onboarding first with /start")
            return

        event = await get_latest_event_for_student(student["id"])
        if not event:
            await q.message.reply_text("No recent events to apply for. Hang tight!")
            return

        await q.message.chat.send_action("typing")

        hm = await _fetch_hiring_manager(event)
        email = await draft_cold_email(student, event, hm)

        hm_name = hm.get("name", "the hiring manager")
        await q.message.reply_text(
            f"*Cold email draft to {hm_name}:*\n\n```\n{email}\n```\n\n"
            "Copy and send via LinkedIn InMail or email.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Apply error for %d: %s", tg_id, e)
        await q.message.reply_text(sanitize_error(e))


async def _fetch_hiring_manager(event: dict) -> dict:
    company_name = event.get("company_name", "")
    if not company_name:
        return {"name": "Hiring Manager", "title": ""}

    cd = Crustdata()
    try:
        result = await cd.person_search(
            title=["VP Engineering", "Engineering Manager", "CTO", "Head of Engineering"],
            company=[company_name],
        )
        profiles = result.get("profiles", result.get("results", []))
        if profiles:
            p = profiles[0]
            return {
                "name": p.get("name", "Hiring Manager"),
                "title": p.get("title", p.get("current_title", "")),
                "company": company_name,
            }
    except Exception as e:
        logger.warning("HM lookup failed: %s", e)
    finally:
        await cd.close()

    return {"name": "Hiring Manager", "title": "", "company": company_name}
