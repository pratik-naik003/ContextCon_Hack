from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from crustdata import Crustdata, CrustdataUnavailable
from db import upsert_recruiter, verify_recruiter, search_students, get_db
from llm import parse_find_query
from security import SessionStore, message_limiter, sanitize_error

logger = logging.getLogger("placemate.recruiter")

_MD_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!])')


def _esc(text: str) -> str:
    return _MD_ESCAPE_RE.sub(r'\\\1', str(text)) if text else ""

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


def _format_crustdata_person(person: dict) -> str | None:
    if not isinstance(person, dict) or "error" in person:
        return None

    bp = person.get("basic_profile", {})
    if not isinstance(bp, dict) or not bp.get("name"):
        return None

    name = _esc(bp.get("name", ""))
    headline = _esc(bp.get("headline", bp.get("current_title", "")))

    loc_obj = bp.get("location", {})
    location = _esc(loc_obj.get("raw", "")) if isinstance(loc_obj, dict) else ""

    exp = person.get("experience", {})
    if not isinstance(exp, dict):
        exp = {}
    employment = exp.get("employment_details", {})
    current_jobs = employment.get("current", [])
    current_str = ""
    company_linkedin = ""
    if isinstance(current_jobs, list) and current_jobs:
        job = current_jobs[0]
        if isinstance(job, dict):
            company = _esc(job.get("name", ""))
            title = _esc(job.get("title", ""))
            if company and title:
                current_str = f"{title} at {company}"
            elif company:
                current_str = company
            elif title:
                current_str = title
            company_linkedin = job.get("company_professional_network_profile_url", "")

    edu = person.get("education", {})
    if not isinstance(edu, dict):
        edu = {}
    schools = edu.get("schools", [])
    edu_str = ""
    if isinstance(schools, list) and schools:
        school = schools[0]
        if isinstance(school, dict):
            school_name = _esc(school.get("school", ""))
            degree = _esc(school.get("degree", ""))
            if school_name and degree:
                edu_str = f"{degree}, {school_name}"
            elif school_name:
                edu_str = school_name

    lines = [f"*{name}*"]
    if current_str:
        lines.append(f"Current: {current_str}")
    elif headline:
        lines.append(headline)
    if edu_str:
        lines.append(f"Education: {edu_str}")
    if location:
        lines.append(f"Location: {location}")
    if company_linkedin:
        lines.append(f"[Company LinkedIn]({company_linkedin})")

    return "\n".join(lines)


async def _search_crustdata_people(parsed: dict) -> list[dict]:
    title = parsed.get("title", "")
    company = parsed.get("company", "")

    if not title and not company:
        skills = parsed.get("skills", [])
        role = parsed.get("role", "")
        if role:
            role_titles = {
                "sde": "Software Engineer",
                "data": "Data Scientist",
                "pm": "Product Manager",
                "design": "Designer",
            }
            title = role_titles.get(role.lower(), role)
        elif skills:
            title = skills[0]

    if not title and not company:
        return []

    cd = Crustdata()
    try:
        result = await cd.person_search(
            title=title,
            company_name=company,
            limit=min(parsed.get("limit", 10), 25),
        )
        if isinstance(result, dict):
            return result.get("profiles", result.get("people", result.get("results", [])))
        if isinstance(result, list):
            return result
        return []
    finally:
        await cd.close()


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
            "Usage: `/find React engineers at Razorpay`\n"
            "Or: `/find 10 Python developers`\n"
            "Or: `/find Data Scientists with ML and Python`",
            parse_mode="Markdown",
        )
        return

    try:
        await update.message.chat.send_action("typing")
        parsed = await parse_find_query(query, user_id=tg_id)
        limit = min(parsed.get("limit", 10), 20)
        sent = 0

        try:
            crustdata_people = await _search_crustdata_people(parsed)
        except CrustdataUnavailable:
            crustdata_people = []
            logger.warning("Crustdata unavailable for find query: %s", query)
        except Exception as e:
            crustdata_people = []
            logger.error("Crustdata search failed: %s", e, exc_info=True)

        for person in crustdata_people:
            if sent >= limit:
                break
            card = _format_crustdata_person(person)
            if card:
                await update.message.reply_text(
                    card, parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
                sent += 1

        local_matches = await search_students(parsed)
        for m in local_matches:
            if sent >= limit:
                break
            skills_str = ", ".join(_esc(s) for s in m.get("skills", [])[:8])
            mastery_str = ", ".join(
                f"{_esc(k)} {v}%" for k, v in m.get("mastery", {}).items()
            ) or "No quizzes taken yet"
            card = (
                f"*{_esc(m.get('name', 'Student'))}* — {_esc(m.get('college', 'N/A'))} ({_esc(m.get('year', 'N/A'))})\n"
                f"Skills: {skills_str}\n"
                f"Verified mastery: {mastery_str}\n"
                "_PlaceMate verified student_"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Message via PlaceMate", callback_data=f"rec:msg:{m['id']}"),
            ]])
            await update.message.reply_text(card, parse_mode="Markdown", reply_markup=kb)
            sent += 1

        if sent == 0:
            await update.message.reply_text(
                "No results found. Try different keywords.\n\n"
                "Examples:\n"
                "• `/find Software Engineers at Google`\n"
                "• `/find React developers`\n"
                "• `/find Data Scientists with Python`",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error("Find error: %s", e)
        await update.message.reply_text(sanitize_error(e))


async def handle_rec_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    recruiter_tg_id = q.from_user.id

    if not message_limiter.is_allowed(recruiter_tg_id):
        return

    if not await _is_verified_recruiter(recruiter_tg_id):
        await q.message.reply_text("You must be a verified recruiter to message students.")
        return

    parts = q.data.split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        return
    student_db_id = int(parts[2])

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tg_id, name FROM students WHERE id = ?", (student_db_id,)
        )
        row = await cursor.fetchone()
        if not row:
            await q.message.reply_text("Student not found.")
            return
        student_tg_id = row["tg_id"]
        student_name = row["name"] or "the student"

        rec_cursor = await db.execute(
            "SELECT company, title FROM recruiters WHERE tg_id = ?", (recruiter_tg_id,)
        )
        rec_row = await rec_cursor.fetchone()
        company = (rec_row["company"] or "a company") if rec_row else "a company"
        title = (rec_row["title"] or "a recruiter") if rec_row else "a recruiter"
    finally:
        await db.close()

    try:
        await ctx.bot.send_message(
            chat_id=student_tg_id,
            text=(
                f"A recruiter from *{company}* ({title}) is interested in your profile on PlaceMate.\n\n"
                "They found you through your verified skills. Reply here to connect."
            ),
            parse_mode="Markdown",
        )
        await q.message.reply_text(f"Message sent to {student_name}.")
    except Forbidden:
        await q.message.reply_text(
            f"{student_name} has not started PlaceMate yet and cannot be contacted. "
            "They need to send /start to the bot first."
        )
    except Exception as e:
        logger.error("rec:msg dispatch failed: %s", e)
        await q.message.reply_text(sanitize_error(e))
