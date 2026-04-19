from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiosqlite

from security import audit_log

logger = logging.getLogger("placemate.db")

DB_PATH = "placemate.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id         INTEGER UNIQUE NOT NULL,
    name          TEXT,
    college       TEXT,
    year          TEXT,
    resume_text   TEXT,
    skills_json   TEXT,
    target_roles  TEXT,
    location      TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS student_companies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL REFERENCES students(id),
    company_id    TEXT NOT NULL,
    company_name  TEXT,
    added_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recruiters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id         INTEGER UNIQUE NOT NULL,
    email         TEXT,
    company       TEXT,
    title         TEXT,
    verified      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    TEXT,
    company_name  TEXT,
    event_type    TEXT,
    payload_json  TEXT,
    fetched_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL,
    event_id      INTEGER NOT NULL,
    sent_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    response      TEXT
);

CREATE TABLE IF NOT EXISTS skill_mastery (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL,
    skill         TEXT NOT NULL,
    level         INTEGER DEFAULT 0,
    last_score    INTEGER,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, skill)
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL,
    skill         TEXT NOT NULL,
    question_idx  INTEGER,
    correct       INTEGER,
    attempted_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
        logger.info("Database initialized")
    finally:
        await db.close()


async def upsert_student(tg_id: int, data: dict[str, Any]) -> int:
    db = await get_db()
    try:
        skills_json = json.dumps(data.get("skills", []))
        await db.execute(
            """INSERT INTO students (tg_id, name, college, resume_text, skills_json, target_roles)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(tg_id) DO UPDATE SET
                 name=excluded.name, college=excluded.college,
                 resume_text=excluded.resume_text, skills_json=excluded.skills_json,
                 target_roles=excluded.target_roles""",
            (tg_id, data.get("name"), data.get("college"),
             data.get("resume_text", ""), skills_json, data.get("target_roles", "")),
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM students WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        student_id = row[0]
        audit_log("student_upsert", tg_id, f"student_id={student_id}")
        return student_id
    finally:
        await db.close()


async def get_student_by_tg(tg_id: int) -> dict[str, Any] | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM students WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["skills"] = json.loads(d.get("skills_json") or "[]")
        return d
    finally:
        await db.close()


async def seed_watched_companies(student_id: int, companies: list[dict]) -> None:
    db = await get_db()
    try:
        for comp in companies:
            cid = str(comp.get("id", comp.get("company_id", "")))
            cname = comp.get("name", comp.get("company_name", "Unknown"))
            await db.execute(
                """INSERT OR IGNORE INTO student_companies (student_id, company_id, company_name)
                   VALUES (?, ?, ?)""",
                (student_id, cid, cname),
            )
        await db.commit()
        audit_log("seed_companies", details=f"student_id={student_id}, count={len(companies)}")
    finally:
        await db.close()


async def all_students_with_companies() -> dict[int, tuple[dict, list[dict]]]:
    db = await get_db()
    try:
        result: dict[int, tuple[dict, list[dict]]] = {}
        cursor = await db.execute("SELECT * FROM students")
        students = [dict(r) for r in await cursor.fetchall()]
        for s in students:
            s["skills"] = json.loads(s.get("skills_json") or "[]")
            cur2 = await db.execute(
                "SELECT company_id, company_name FROM student_companies WHERE student_id = ?",
                (s["id"],),
            )
            companies = [dict(r) for r in await cur2.fetchall()]
            result[s["id"]] = (s, companies)
        return result
    finally:
        await db.close()


async def insert_event(company_id: str, company_name: str, event_type: str, payload_json: str) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO events (company_id, company_name, event_type, payload_json) VALUES (?, ?, ?, ?)",
            (company_id, company_name, event_type, payload_json),
        )
        await db.commit()
        event_id = cursor.lastrowid
        audit_log("event_insert", details=f"event_id={event_id}, type={event_type}, company={company_name}")
        return event_id
    finally:
        await db.close()


async def recent_event_signatures(hours: int = 24) -> set[str]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT company_id, event_type, payload_json FROM events
               WHERE fetched_at > datetime('now', ?)""",
            (f"-{hours} hours",),
        )
        sigs = set()
        for row in await cursor.fetchall():
            payload = json.loads(row["payload_json"] or "{}")
            jd = payload.get("job_details", {})
            job_url = jd.get("url", "")
            sigs.add(f"{row['company_name']}:{row['event_type']}:{job_url}")
        return sigs
    finally:
        await db.close()


async def record_notification(student_id: int, event_id: int) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO notifications (student_id, event_id) VALUES (?, ?)",
            (student_id, event_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_notification_response(student_id: int, event_id: int, response: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE notifications SET response = ? WHERE student_id = ? AND event_id = ?",
            (response, student_id, event_id),
        )
        await db.commit()
    finally:
        await db.close()


async def record_quiz_attempt(tg_id: int, skill: str, question_idx: int, correct: bool) -> None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM students WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        if not row:
            return
        await db.execute(
            "INSERT INTO quiz_attempts (student_id, skill, question_idx, correct) VALUES (?, ?, ?, ?)",
            (row[0], skill, question_idx, int(correct)),
        )
        await db.commit()
    finally:
        await db.close()


async def compute_mastery_score(tg_id: int, skill: str) -> int:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM students WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        if not row:
            return 0
        student_id = row[0]
        cursor = await db.execute(
            "SELECT correct FROM quiz_attempts WHERE student_id = ? AND skill = ? ORDER BY attempted_at DESC",
            (student_id, skill),
        )
        attempts = [dict(r) for r in await cursor.fetchall()]
        if not attempts:
            return 0
        correct_count = sum(1 for a in attempts if a["correct"])
        return int((correct_count / len(attempts)) * 100)
    finally:
        await db.close()


async def update_mastery(tg_id: int, skill: str, score: int) -> None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM students WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        if not row:
            return
        student_id = row[0]
        await db.execute(
            """INSERT INTO skill_mastery (student_id, skill, level, last_score, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(student_id, skill) DO UPDATE SET
                 level=excluded.level, last_score=excluded.last_score, updated_at=CURRENT_TIMESTAMP""",
            (student_id, skill, score, score),
        )
        await db.commit()
        audit_log("mastery_update", tg_id, f"skill={skill}, score={score}")
    finally:
        await db.close()


async def get_latest_event_for_student(student_id: int) -> dict[str, Any] | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT e.* FROM events e
               JOIN notifications n ON n.event_id = e.id
               WHERE n.student_id = ?
               ORDER BY e.fetched_at DESC LIMIT 1""",
            (student_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_event_by_id(event_id: int) -> dict[str, Any] | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def search_students(filters: dict[str, Any]) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        query = "SELECT s.*, sm.skill as mastery_skill, sm.level as mastery_level FROM students s LEFT JOIN skill_mastery sm ON s.id = sm.student_id WHERE 1=1"
        params: list[Any] = []

        if filters.get("skills"):
            for skill in filters["skills"]:
                skill = str(skill).strip()[:50]
                if not re.match(r'^[a-zA-Z0-9\s\+\-\#\.]+$', skill):
                    continue
                query += " AND s.skills_json LIKE ?"
                params.append(f"%{skill}%")
        if filters.get("year"):
            query += " AND s.year = ?"
            params.append(filters["year"])
        if filters.get("college"):
            query += " AND s.college LIKE ?"
            params.append(f"%{filters['college']}%")

        query += " ORDER BY s.created_at DESC"
        limit = min(max(int(filters.get("limit", 10)), 1), 50)
        query += " LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = [dict(r) for r in await cursor.fetchall()]

        students_map: dict[int, dict] = {}
        for r in rows:
            sid = r["id"]
            if sid not in students_map:
                students_map[sid] = {
                    **r,
                    "skills": json.loads(r.get("skills_json") or "[]"),
                    "mastery": {},
                }
            if r.get("mastery_skill"):
                students_map[sid]["mastery"][r["mastery_skill"]] = r["mastery_level"]

        return list(students_map.values())[:limit]
    finally:
        await db.close()


async def upsert_recruiter(tg_id: int, email: str = "", company: str = "", title: str = "") -> int:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO recruiters (tg_id, email, company, title)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(tg_id) DO UPDATE SET
                 email=excluded.email, company=excluded.company, title=excluded.title""",
            (tg_id, email, company, title),
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM recruiters WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        audit_log("recruiter_upsert", tg_id)
        return row[0]
    finally:
        await db.close()


async def verify_recruiter(tg_id: int) -> None:
    db = await get_db()
    try:
        await db.execute("UPDATE recruiters SET verified = 1 WHERE tg_id = ?", (tg_id,))
        await db.commit()
        audit_log("recruiter_verified", tg_id)
    finally:
        await db.close()
