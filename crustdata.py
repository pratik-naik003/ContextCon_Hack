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
API_VERSION = "2025-11-01"


class ResponseCache:
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
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"companies": [], "profiles": [], "job_listings": []}


class Crustdata:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=30,
            headers={
                "Authorization": f"Bearer {settings.crustdata_api_key}",
                "Content-Type": "application/json",
                "x-api-version": API_VERSION,
            },
        )

    async def _request(self, path: str, payload: dict, cache_key: str,
                       fallback_file: str = "demo_events.json") -> dict | list:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        if not api_limiter.is_allowed(0):
            logger.warning("Crustdata rate limit, serving fallback")
            return _load_fallback(fallback_file)

        retries = 3
        for attempt in range(retries):
            try:
                r = await self.client.post(f"{BASE}{path}", json=payload)
                r.raise_for_status()
                data = r.json()
                _cache.set(cache_key, data)
                audit_log("crustdata_call", details=f"path={path}, status={r.status_code}")
                return data
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning("Crustdata attempt %d failed for %s: %s", attempt + 1, path, e)
                if attempt == retries - 1:
                    logger.error("Crustdata exhausted retries for %s, serving fallback", path)
                    return _load_fallback(fallback_file)
                await _backoff(attempt)

        return _load_fallback(fallback_file)

    async def company_search(self, *, headcount_min: int = 50, headcount_max: int = 1000,
                              country: str = "", industry: str = "",
                              funding_type: str = "", limit: int = 20) -> dict:
        conditions = []
        if headcount_min:
            conditions.append({"field": "headcount.total", "type": ">", "value": headcount_min})
        if headcount_max:
            conditions.append({"field": "headcount.total", "type": "<", "value": headcount_max})
        if country:
            conditions.append({"field": "locations.country", "type": "=", "value": country})
        if industry:
            conditions.append({"field": "basic_info.industries", "type": "contains", "value": industry})
        if funding_type:
            conditions.append({"field": "funding.last_round_type", "type": "=", "value": funding_type})

        if len(conditions) == 1:
            filters = conditions[0]
        elif len(conditions) > 1:
            filters = {"op": "and", "conditions": conditions}
        else:
            filters = {"field": "headcount.total", "type": ">", "value": 10}

        payload = {
            "filters": filters,
            "fields": ["basic_info", "headcount", "funding", "hiring", "locations"],
            "limit": min(limit, 100),
            "sorts": [{"column": "headcount.total", "order": "desc"}],
        }

        key = f"company_search:{json.dumps(payload)}"
        return await self._request("/company/search", payload, key)

    async def person_search(self, *, title: str = "", company_name: str = "",
                             limit: int = 10) -> dict:
        conditions = []
        if title:
            conditions.append({
                "field": "experience.employment_details.current.title",
                "type": "(.)",
                "value": title,
            })
        if company_name:
            conditions.append({
                "field": "experience.employment_details.current.name",
                "type": "=",
                "value": company_name,
            })

        if len(conditions) == 1:
            filters = conditions[0]
        elif len(conditions) > 1:
            filters = {"op": "and", "conditions": conditions}
        else:
            return {"profiles": []}

        payload = {
            "filters": filters,
            "limit": min(limit, 50),
        }

        key = f"person_search:{json.dumps(payload)}"
        return await self._request("/person/search", payload, key)

    async def job_search(self, *, company_id: int | None = None,
                          company_name: str = "",
                          title: str = "", category: str = "Engineering",
                          limit: int = 20) -> dict:
        conditions = []
        if company_id:
            conditions.append({
                "field": "company.basic_info.company_id",
                "type": "=",
                "value": company_id,
            })
        if company_name:
            conditions.append({
                "field": "company.basic_info.name",
                "type": "(.)",
                "value": company_name,
            })
        if title:
            conditions.append({
                "field": "job_details.title",
                "type": "(.)",
                "value": title,
            })
        if category:
            conditions.append({
                "field": "job_details.category",
                "type": "=",
                "value": category,
            })

        if len(conditions) == 1:
            filters = conditions[0]
        elif len(conditions) > 1:
            filters = {"op": "and", "conditions": conditions}
        else:
            filters = {"field": "job_details.category", "type": "=", "value": "Engineering"}

        payload = {
            "filters": filters,
            "fields": [
                "job_details.title", "job_details.url", "job_details.category",
                "company.basic_info.name", "company.basic_info.company_id",
                "company.basic_info.primary_domain",
                "location.raw", "location.country",
                "metadata.date_added",
            ],
            "limit": min(limit, 100),
            "sorts": [{"column": "metadata.date_added", "order": "desc"}],
        }

        key = f"job_search:{json.dumps(payload)}"
        return await self._request("/job/search", payload, key)

    async def company_enrich(self, *, domain: str = "", name: str = "",
                              company_id: int | None = None) -> list:
        payload: dict[str, Any] = {
            "fields": ["basic_info", "headcount", "funding", "hiring", "people"],
        }
        if domain:
            payload["domains"] = [domain]
        elif name:
            payload["names"] = [name]
        elif company_id:
            payload["crustdata_company_ids"] = [company_id]
        else:
            return []

        key = f"company_enrich:{json.dumps(payload)}"
        return await self._request("/company/enrich", payload, key)

    async def person_enrich(self, *, email: str = "",
                             profile_url: str = "") -> list:
        payload: dict[str, Any] = {}
        if email:
            payload["business_emails"] = [email]
        elif profile_url:
            payload["professional_network_profile_urls"] = [profile_url]
        else:
            return []

        key = f"person_enrich:{json.dumps(payload)}"
        return await self._request("/person/enrich", payload, key)

    async def close(self) -> None:
        await self.client.aclose()


async def _backoff(attempt: int) -> None:
    import asyncio
    wait = min(2 ** attempt, 8)
    await asyncio.sleep(wait)
