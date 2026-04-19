from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from handlers.tutor import signal_keyboard
from security import message_limiter

logger = logging.getLogger("placemate.demo")

DEMO_EVENTS_PATH = Path("assets/demo_events.json")


def _load_demo_events() -> list[dict]:
    if DEMO_EVENTS_PATH.exists():
        return json.loads(DEMO_EVENTS_PATH.read_text())
    return [
        {
            "company_name": "Razorpay",
            "event_type": "hiring_surge",
            "headline": "Razorpay just opened 15 SDE roles after their Series F",
            "match_reason": "Your Python + System Design skills match 4 of the 6 JD requirements",
            "missing_skills": "Kafka, Redis at scale",
            "hm_name": "Priya Sharma",
            "hm_title": "VP Engineering",
        },
    ]


async def run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    if not message_limiter.is_allowed(tg_id):
        await update.message.reply_text("Slow down! Try again in a minute.")
        return

    events = _load_demo_events()
    event = events[0] if events else {}

    await update.message.reply_text(
        "*Demo mode* — simulating a live Crustdata signal...",
        parse_mode="Markdown",
    )
    await update.message.chat.send_action("typing")
    await asyncio.sleep(1.5)

    headline = event.get("headline", "New opportunity detected!")
    match_reason = event.get("match_reason", "Your skills match this role")
    missing = event.get("missing_skills", "None identified")
    hm = event.get("hm_name", "Hiring Manager")
    hm_title = event.get("hm_title", "")

    signal_msg = (
        f"*{headline}*\n\n"
        f"*Why you're a fit:* {match_reason}\n"
        f"*You're missing:* {missing}\n"
        f"*Hiring manager:* {hm}, {hm_title}"
    )
    await update.message.reply_text(
        signal_msg,
        parse_mode="Markdown",
        reply_markup=signal_keyboard(0),
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*PlaceMate Commands*\n\n"
        "/start — Set up your profile\n"
        "/demo — See a live signal demo\n"
        "/recruiter — Switch to recruiter mode\n"
        "/find — Search for candidates (recruiter)\n"
        "/help — Show this message",
        parse_mode="Markdown",
    )
