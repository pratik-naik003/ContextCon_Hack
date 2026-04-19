from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from crustdata import Crustdata
from db import upsert_recruiter, verify_recruiter, search_students
from llm import parse_find_query
from security import SessionStore, message_limiter, sanitize_error

logger = logging.getLogger("placemate.recruiter")

RECRUITER_STATE = SessionStore(ttl=1800)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    if not message_limiter.is_allowed(tg_id):
        await update.message.reply_text("Slow down! Try again in a minute.")
        return
    RECRUITER_STATE.set(tg_id, {"step": "email"})
    await update.message.reply_text(
        "Recruiter mode. Send me your work email to verify."
    )


async def handle_recruiter_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    st = RECRUITER_STATE.get(tg_id)
    if not st or st.get("step") != "email":
        return

    email = update.message.text.strip()
    if "@" not in email:
        await update.message.reply_text("Please send a valid email address.")
        return

    try:
        await update.message.chat.send_action("typing")
        await upsert_recruiter(tg_id, email=email)

        cd = Crustdata()
        try:
            result = await cd.reverse_lookup(email)
            profiles = result.get("profiles", result.get("results", []))
            if profiles:
                p = profiles[0]
                company = p.get("company", p.get("current_company", ""))
                title = p.get("title", p.get("current_title", ""))
                await upsert_recruiter(tg_id, email=email, company=company, title=title)
                await verify_recruiter(tg_id)
                await update.message.reply_text(
                    f"Verified! *{p.get('name', '')}* at *{company}*\n\n"
                    "Use /find to search for candidates.\n"
                    "Example: `/find 10 CS students with React and Node`",
                    parse_mode="Markdown",
                )
            else:
                await verify_recruiter(tg_id)
                await update.message.reply_text(
                    "Couldn't verify via Crustdata, but you're in.\n\n"
                    "Use /find to search for candidates.",
                )
        finally:
            await cd.close()
        RECRUITER_STATE.delete(tg_id)
    except Exception as e:
        logger.error("Recruiter verify error: %s", e)
        await update.message.reply_text(sanitize_error(e))


async def find(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    if not message_limiter.is_allowed(tg_id):
        await update.message.reply_text("Slow down! Try again in a minute.")
        return

    query = " ".join(ctx.args) if ctx.args else ""
    if not query:
        await update.message.reply_text(
            "Usage: `/find 10 3rd-year CS students with React + Node at tier-1 colleges`",
            parse_mode="Markdown",
        )
        return

    try:
        await update.message.chat.send_action("typing")
        parsed = await parse_find_query(query)
        matches = await search_students(parsed)

        if not matches:
            await update.message.reply_text("No matching students found. Try broader criteria.")
            return

        for m in matches[:parsed.get("limit", 10)]:
            skills_str = ", ".join(m.get("skills", [])[:8])
            mastery_str = ", ".join(
                f"{k} {v}%" for k, v in m.get("mastery", {}).items()
            ) or "No quizzes taken yet"
            card = (
                f"*{m.get('name', 'Student')}* — {m.get('college', 'N/A')} ({m.get('year', 'N/A')})\n"
                f"Skills: {skills_str}\n"
                f"Verified mastery: {mastery_str}"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Message via PlaceMate", callback_data=f"rec:msg:{m['id']}"),
            ]])
            await update.message.reply_text(card, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error("Find error: %s", e)
        await update.message.reply_text(sanitize_error(e))
