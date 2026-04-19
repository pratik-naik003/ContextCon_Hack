from __future__ import annotations

import time
import logging
from collections import defaultdict
from functools import wraps
from typing import Any

from config import settings

logger = logging.getLogger("placemate.security")


class RateLimiter:
    """Per-user sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        now = time.monotonic()
        window_start = now - self._window
        hits = self._hits[user_id]
        self._hits[user_id] = [t for t in hits if t > window_start]
        if len(self._hits[user_id]) >= self._max:
            logger.warning("Rate limit hit for user %d", user_id)
            return False
        self._hits[user_id].append(now)
        return True


message_limiter = RateLimiter(settings.rate_limit_messages_per_minute)
api_limiter = RateLimiter(settings.rate_limit_api_calls_per_minute)


class SessionStore:
    """In-memory session state with TTL."""

    def __init__(self, ttl: int = 3600):
        self._store: dict[int, dict[str, Any]] = {}
        self._timestamps: dict[int, float] = {}
        self._ttl = ttl

    def get(self, key: int) -> dict[str, Any] | None:
        if key not in self._store:
            return None
        if time.monotonic() - self._timestamps[key] > self._ttl:
            self.delete(key)
            return None
        return self._store[key]

    def set(self, key: int, value: dict[str, Any]) -> None:
        self._store[key] = value
        self._timestamps[key] = time.monotonic()

    def delete(self, key: int) -> None:
        self._store.pop(key, None)
        self._timestamps.pop(key, None)


def audit_log(action: str, user_id: int | None = None, details: str = "") -> None:
    logger.info(
        "AUDIT | action=%s | user=%s | details=%s",
        action,
        user_id or "system",
        details,
    )


def sanitize_error(exc: Exception) -> str:
    """Return a user-safe error message. Never expose internals."""
    return "Something went wrong. Please try again later."
