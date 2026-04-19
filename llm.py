from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from config import settings
from security import audit_log, api_limiter

logger = logging.getLogger("placemate.llm")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-3-flash-preview"

_client: httpx.AsyncClient | None = None
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 300


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30)
    return _client


def _cached(key: str) -> Any | None:
    if key in _cache:
        ts, val = _cache[key]
        if time.monotonic() - ts < CACHE_TTL:
            return val
        del _cache[key]
    return None


def _set_cache(key: str, val: Any) -> None:
    _cache[key] = (time.monotonic(), val)


async def _generate(prompt: str, cache_key: str | None = None) -> str:
    if cache_key:
        cached = _cached(cache_key)
        if cached:
            return cached

    if not api_limiter.is_allowed(0):
        logger.warning("LLM rate limit hit, returning cached or fallback")
        if cache_key:
            cached = _cached(cache_key)
            if cached:
                return cached
        return ""

    url = f"{GEMINI_BASE}/models/{MODEL}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": settings.gemini_api_key,
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }

    try:
        client = _get_client()
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("Gemini returned no candidates")
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        result = "\n".join(text_parts)
        audit_log("llm_call", details=f"model={MODEL}, prompt_len={len(prompt)}, response_len={len(result)}")
        if cache_key:
            _set_cache(cache_key, result)
        return result
    except httpx.HTTPStatusError as e:
        logger.error("Gemini HTTP error %d: %s", e.response.status_code, e.response.text[:300])
        if cache_key:
            cached = _cached(cache_key)
            if cached:
                return cached
        return ""
    except Exception as e:
        logger.error("Gemini call failed: %s", e)
        if cache_key:
            cached = _cached(cache_key)
            if cached:
                return cached
        return ""


async def extract_skills_from_resume(resume_text: str) -> list[str]:
    prompt = f"""Extract technical and professional skills from this resume text.
Return ONLY a JSON array of skill strings. No explanation, no markdown fences.
Example: ["Python", "React", "PostgreSQL", "System Design"]

Resume:
{resume_text[:3000]}"""

    cache_key = f"skills:{hash(resume_text[:500])}"
    result = await _generate(prompt, cache_key)
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        skills = json.loads(cleaned)
        if isinstance(skills, list):
            return [str(s).strip() for s in skills[:20]]
    except (json.JSONDecodeError, ValueError):
        pass

    words = resume_text.split()
    tech_keywords = {"Python", "Java", "JavaScript", "React", "Node", "SQL", "AWS",
                     "Docker", "Kubernetes", "Git", "TypeScript", "Go", "Rust", "C++",
                     "PostgreSQL", "MongoDB", "Redis", "GraphQL", "REST", "API"}
    return [w for w in words if w in tech_keywords][:10]


async def compose_signal_message(student: dict, company: dict, job: dict) -> str:
    skills = student.get("skills", [])
    jd_text = json.dumps(job)[:1000]
    prompt = f"""You are PlaceMate, a career bot. Write a short, high-signal Telegram message for this student.

Student: {student.get('name', 'Student')}, {student.get('college', '')}, skills: {', '.join(skills[:8])}, target role: {student.get('target_roles', '')}
Company event: {company.get('company_name', '')} posted a new role.
JD details: {jd_text}

Format (Markdown):
🚨 **<headline>**

**Why you're a fit:** <1 line, quantified skill match>
**You're missing:** <skills the student lacks from JD>
**Company:** <company name, 1 interesting detail>

Keep under 80 words. Punchy. Specific. No fluff."""

    cache_key = f"signal:{student.get('tg_id')}:{company.get('company_id')}:{job.get('id', '')}"
    result = await _generate(prompt, cache_key)
    return result or f"🚨 **New role at {company.get('company_name', 'a company')}**\n\nThis matches your profile. Tap below to learn more."


async def draft_cold_email(student: dict, event: dict, hm: dict) -> str:
    prompt = f"""Write a 4-line cold email from a student to a hiring manager. Rules:
- Line 1: Reference a SPECIFIC recent event at the company (funding, exec hire, new role).
- Line 2: Connect student's skill to the JD in one sentence.
- Line 3: Name-drop one relevant project or skill.
- Line 4: Soft CTA — ask for 15 min.

Student: {student.get('name', '')}, skills: {', '.join(student.get('skills', [])[:6])}
Company: {event.get('company_name', '')}, event: {event.get('event_type', '')}
Hiring manager: {hm.get('name', 'the hiring manager')}, {hm.get('title', '')}
JD snippet: {json.dumps(event.get('payload_json', ''))[:500]}

Output just the email body. No subject line. No signature."""

    cache_key = f"email:{student.get('tg_id')}:{event.get('id', '')}"
    result = await _generate(prompt, cache_key)
    return result or "Hi, I noticed your team is hiring and I'd love to chat about how my skills align. Could we do a quick 15-min call?"


async def parse_find_query(query: str) -> dict[str, Any]:
    prompt = f"""Parse this recruiter search query into structured filters.
Return ONLY valid JSON with these optional fields, no markdown fences:
{{"role": "string", "skills": ["list"], "year": "string", "college": "string", "limit": number}}

Query: {query}"""

    cache_key = f"parse:{hash(query)}"
    result = await _generate(prompt, cache_key)
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            parsed.setdefault("limit", 10)
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return {"skills": query.split(), "limit": 10}
