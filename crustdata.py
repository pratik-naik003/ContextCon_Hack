from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from config import settings
from security import audit_log, api_limiter

logger = logging.getLogger("placemate.crustdata")

BASE = "https://api.crustdata.com"
HEADERS = {
    "Authorization": f"Token {settings.crustdata_api_key}",
    "Content-Type": "application/json",
}

DEMO_EVENTS_PATH = Path("assets/demo_events.json")
DEMO_STUDENTS_PATH = Path("assets/demo_students.json")


class ResponseCache:
    """Simple in-memory cache with 5-minute TTL."""

    def __init__(self, ttl: int = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        ts, val = self._store[key]
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return val

    def set(self, key: str, val: Any) -> None:
        self._store[key] = (time.monotonic(), val)


_cache = ResponseCache()


def _load_fallback(filename: str) -> dict:
    path = Path("assets") / filename
    if path.exists():
        return json.loads(path.read_text())
    return {"profiles": [], "results": []}


class Crustdata:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=30, headers=HEADERS)

    async def _request(self, method: str, path: str, cache_key: str,
                       fallback_file: str = "demo_events.json", **kwargs) -> dict:
        cached = _cache.get(cache_key)
        if cached:
            return cached

        if not api_limiter.is_allowed(0):
            logger.warning("Crustdata rate limit, serving fallback")
            return _load_fallback(fallback_file)

        retries = 3
        for attempt in range(retries):
            try:
                if method == "POST":
                    r = await self.client.post(f"{BASE}{path}", **kwargs)
                else:
                    r = await self.client.get(f"{BASE}{path}", **kwargs)
                r.raise_for_status()
                data = r.json()
                _cache.set(cache_key, data)
                audit_log("crustdata_call", details=f"path={path}, status={r.status_code}")
                return data
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning("Crustdata attempt %d failed: %s", attempt + 1, e)
                if attempt == retries - 1:
                    logger.error("Crustdata exhausted retries, serving fallback")
                    return _load_fallback(fallback_file)
                await _backoff(attempt)

        return _load_fallback(fallback_file)

    async def company_search(self, *, headcount: list[str] | None = None,
                              industry: list[str] | None = None,
                              funding_stage: list[str] | None = None,
                              location: list[str] | None = None, page: int = 1) -> dict:
        filters = []
        if headcount:
            filters.append({"filter_type": "COMPANY_HEADCOUNT", "type": "in", "value": headcount})
        if industry:
            filters.append({"filter_type": "INDUSTRY", "type": "in", "value": industry})
        if funding_stage:
            filters.append({"filter_type": "LAST_FUNDING_STAGE", "type": "in", "value": funding_stage})
        if location:
            filters.append({"filter_type": "REGION", "type": "in", "value": location})

        key = f"company_search:{json.dumps(filters)}:{page}"
        return await self._request("POST", "/screener/company/search", key,
                                    json={"filters": filters, "page": page})

    async def person_search(self, *, title: list[str] | None = None,
                             company: list[str] | None = None, page: int = 1) -> dict:
        filters = []
        if title:
            filters.append({"filter_type": "CURRENT_TITLE", "type": "in", "value": title})
        if company:
            filters.append({"filter_type": "CURRENT_COMPANY", "type": "in", "value": company})

        key = f"person_search:{json.dumps(filters)}:{page}"
        return await self._request("POST", "/screener/person/search", key,
                                    json={"filters": filters, "page": page})

    async def job_listings(self, company_id: str) -> dict:
        key = f"job_listings:{company_id}"
        return await self._request("GET", "/data_lab/job_listings/", key,
                                    params={"company_id": company_id})

    async def reverse_lookup(self, email: str) -> dict:
        key = f"reverse_lookup:{email}"
        return await self._request("POST", "/screener/person/enrich", key,
                                    json={"email": email})

    async def close(self) -> None:
        await self.client.aclose()


async def _backoff(attempt: int) -> None:
    import asyncio
    wait = min(2 ** attempt, 8)
    await asyncio.sleep(wait)
