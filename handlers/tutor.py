from __future__ import annotations

import json
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import (record_quiz_attempt, compute_mastery_score, update_mastery,
                update_notification_response, get_student_by_tg, get_latest_event_for_student)
from security import message_limiter

logger = logging.getLogger("placemate.tutor")

LESSONS: dict[str, dict] = {}


def load_lessons() -> None:
    lesson_dir = Path("assets/lessons")
    if not lesson_dir.exists():
        return
    for p in lesson_dir.glob("*.json"):
        if p.name.startswith("."):
            continue
        try:
            LESSONS[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning("Failed to load lesson %s: %s", p.name, e)


load_lessons()


def signal_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Get me ready in 3 days", callback_data=f"tutor:start:{event_id}")],
        [InlineKeyboardButton("Apply anyway", callback_data=f"apply:go:{event_id}"),
         InlineKeyboardButton("Skip", callback_data=f"tutor:skip:{event_id}")],
    ])


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = q.from_user.id

    if not message_limiter.is_allowed(tg_id):
        return

    parts = q.data.split(":")
    if len(parts) < 3:
        return

    action = parts[1]

    if action == "start":
        event_id = parts[2]
        await update_notification_response(tg_id, int(event_id), "get_ready")
        available = list(LESSONS.keys())
        if not available:
            await q.message.reply_text("No lessons available yet. Check back soon!")
            return
        skill = available[0]
        await _start_lesson(q, skill)

    elif action == "skip":
        event_id = parts[2]
        await update_notification_response(tg_id, int(event_id), "skip")
        await q.edit_message_text("Skipped. I'll keep watching for better matches.")

    elif action == "lesson":
        skill = parts[2]
        await _start_lesson(q, skill)

    elif action == "q":
        if len(parts) >= 5:
            skill = parts[2]
            if skill not in LESSONS:
                return
            try:
                idx = int(parts[3])
                picked = int(parts[4])
            except ValueError:
                return
            quiz = LESSONS[skill]["quiz"]
            if idx < 0 or idx >= len(quiz) or picked < 0 or picked >= len(quiz[idx]["options"]):
                return
            await _handle_answer(q, tg_id, skill, idx, picked)


async def _start_lesson(q, skill: str) -> None:
    if skill not in LESSONS:
        await q.message.reply_text("Lesson not found.")
        return
    lesson = LESSONS[skill]
    await q.message.reply_text(
        f"*{lesson['title']}*\n\n{lesson['lesson_md']}",
        parse_mode="Markdown",
    )
    await _send_question(q, skill, 0)


async def _send_question(q, skill: str, idx: int) -> None:
    quiz = LESSONS[skill]["quiz"]
    if idx >= len(quiz):
        return
    question = quiz[idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f"tutor:q:{skill}:{idx}:{i}")]
        for i, opt in enumerate(question["options"])
    ])
    await q.message.reply_text(
        f"*Q{idx + 1}.* {question['q']}",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _handle_answer(q, tg_id: int, skill: str, idx: int, picked: int) -> None:
    quiz = LESSONS[skill]["quiz"]
    if idx >= len(quiz):
        return
    question = quiz[idx]
    correct = picked == question["correct"]
    await record_quiz_attempt(tg_id, skill, idx, correct)

    if correct:
        feedback = "Correct!"
    else:
        feedback = f"Nope — answer was *{question['options'][question['correct']]}*"

    await q.message.reply_text(feedback, parse_mode="Markdown")

    if idx + 1 < len(quiz):
        await _send_question(q, skill, idx + 1)
    else:
        score = await compute_mastery_score(tg_id, skill)
        await update_mastery(tg_id, skill, score)
        if score >= 80:
            student = await get_student_by_tg(tg_id)
            event_row = await get_latest_event_for_student(student["id"]) if student else None
            event_id = event_row["id"] if event_row else 0
            await q.message.reply_text(
                f"*Mastery unlocked: {skill} — {score}/100*\n\n"
                "You're ready. Want me to draft your cold email to the hiring manager?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Draft my email", callback_data=f"apply:go:{event_id}"),
                ]]),
            )
        else:
            links_text = ""
            if "affiliate_links" in LESSONS[skill]:
                links = LESSONS[skill]["affiliate_links"]
                links_text = "\n\n*Go deeper:*\n" + "\n".join(
                    f"- [{l['label']}]({l['url']})" for l in links
                )
            await q.message.reply_text(
                f"Score: {score}/100 — close, but let's bulletproof this.{links_text}",
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
