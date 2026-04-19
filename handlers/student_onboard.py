from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from crustdata import Crustdata
from db import upsert_student, seed_watched_companies
from llm import extract_skills_from_resume
from security import SessionStore, message_limiter, sanitize_error

logger = logging.getLogger("placemate.onboard")

STATE = SessionStore(ttl=3600)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    if not message_limiter.is_allowed(tg_id):
        await update.message.reply_text("Slow down! Try again in a minute.")
        return
    STATE.set(tg_id, {"step": "name", "data": {}})
    await update.message.reply_text(
        "Hey! I'm PlaceMate — your personal placement officer on Telegram.\n\n"
        "I watch 300+ companies in real time and ping you the *moment* an opportunity matches you.\n\n"
        "First — what's your name?",
        parse_mode="Markdown",
    )


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    st = STATE.get(tg_id)
    if not st:
        return
    if not message_limiter.is_allowed(tg_id):
        await update.message.reply_text("Slow down! Try again in a minute.")
        return

    text = update.message.text.strip()
    if not text:
        return
    if len(text) > 10000:
        await update.message.reply_text("Input too long. Please keep it under 10,000 characters.")
        return

    step = st["step"]
    data = st["data"]

    try:
        if step == "name":
            if len(text) > 100:
                await update.message.reply_text("Name is too long. Please use a shorter name.")
                return
            data["name"] = text
            st["step"] = "college"
            STATE.set(tg_id, st)
            await update.message.reply_text(f"Nice to meet you, {text}! Which college are you at?")

        elif step == "college":
            data["college"] = text
            st["step"] = "resume"
            STATE.set(tg_id, st)
            await update.message.reply_text(
                "Paste your resume text OR drop your LinkedIn URL. I'll extract your skills automatically."
            )

        elif step == "resume":
            await update.message.chat.send_action("typing")
            skills = await extract_skills_from_resume(text)
            data["resume_text"] = text
            data["skills"] = skills
            st["step"] = "roles"
            STATE.set(tg_id, st)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("SDE", callback_data="onb:role:sde"),
                 InlineKeyboardButton("Data", callback_data="onb:role:data")],
                [InlineKeyboardButton("PM", callback_data="onb:role:pm"),
                 InlineKeyboardButton("Design", callback_data="onb:role:design")],
            ])
            skills_display = ", ".join(skills[:6]) if skills else "none detected yet"
            await update.message.reply_text(
                f"Extracted skills: *{skills_display}*\n\nWhat role are you gunning for?",
                parse_mode="Markdown",
                reply_markup=kb,
            )
    except Exception as e:
        logger.error("Onboard error for %d: %s", tg_id, e)
        await update.message.reply_text(sanitize_error(e))


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = q.from_user.id
    st = STATE.get(tg_id)
    if not st:
        return

    if not q.data.startswith("onb:role:"):
        return

    role = q.data.split(":")[-1]
    st["data"]["target_roles"] = role

    try:
        student_id = await upsert_student(tg_id, st["data"])
        cd = Crustdata()
        try:
            result = await cd.company_search(headcount_min=50, headcount_max=1000)
            companies_list = result.get("companies", []) if isinstance(result, dict) else []
            seed_data = []
            for c in companies_list[:50]:
                bi = c.get("basic_info", {})
                seed_data.append({
                    "company_id": str(bi.get("crustdata_company_id", c.get("crustdata_company_id", ""))),
                    "company_name": bi.get("name", "Unknown"),
                })
            await seed_watched_companies(student_id, seed_data)
        finally:
            await cd.close()

        await q.edit_message_text(
            "Locked in. I'm now watching 300+ companies for you.\n\n"
            "*I'll only ping you when something actually matters* — a funding round, a hiring surge, "
            "or a role that matches your skills.\n\n"
            "Type /demo to see what a live signal looks like.",
            parse_mode="Markdown",
        )
        STATE.delete(tg_id)
    except Exception as e:
        logger.error("Onboard callback error for %d: %s", tg_id, e)
        await q.edit_message_text(sanitize_error(e))
