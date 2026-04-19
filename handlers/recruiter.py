from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from crustdata import Crustdata
from db import upsert_recruiter, verify_recruiter, search_students, get_db
from llm import parse_find_query
from security import SessionStore, message_limiter, sanitize_error

logger = logging.getLogger("placemate.recruiter")

RECRUITER_STATE = SessionStore(ttl=1800)

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                      "protonmail.com", "mail.com", "aol.com", "icloud.com"}
EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


async def _is_verified_recruiter(tg_id: int) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT verified FROM recruiters WHERE tg_id = ?", (tg_id,)
        )
        row = await cursor.fetchone()
        return bool(row and row[0])
    finally:
        await db.close()


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
    if not EMAIL_RE.match(email) or len(email) > 254:
        await update.message.reply_text("Please send a valid email address.")
        return

    domain = email.split("@")[1].lower()
    if domain in FREE_EMAIL_DOMAINS:
        await update.message.reply_text(
            "Please use your company email address, not a personal one."
        )
        return

    try:
        await update.message.chat.send_action("typing")
        await upsert_recruiter(tg_id, email=email)

        cd = Crustdata()
        try:
            results = await cd.person_enrich(email=email)
            matches_found = False
            if isinstance(results, list) and results:
                matches = results[0].get("matches", [])
                if matches:
                    pd = matches[0].get("person_data", {})
                    bp = pd.get("basic_profile", {})
                    exp = pd.get("experience", {}).get("employment_details", {})
                    current = exp.get("current", [{}])
                    curr_job = current[0] if current else {}
                    company = curr_job.get("name", "")
                    title = curr_job.get("title", bp.get("current_title", ""))
                    name = bp.get("name", "")
                    await upsert_recruiter(tg_id, email=email, company=company, title=title)
                    await verify_recruiter(tg_id)
                    await update.message.reply_text(
                        f"Verified! *{name}* at *{company}*\n\n"
                        "Use /find to search for candidates.\n"
                        "Example: `/find 10 CS students with React and Node`",
                        parse_mode="Markdown",
                    )
                    matches_found = True
            if not matches_found:
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

    if not await _is_verified_recruiter(tg_id):
        await update.message.reply_text(
            "Please complete recruiter verification first with /recruiter"
        )
        return

    query = " ".join(ctx.args) if ctx.args else ""
    if not query or len(query) > 500:
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

        for m in matches[:min(parsed.get("limit", 10), 20)]:
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
