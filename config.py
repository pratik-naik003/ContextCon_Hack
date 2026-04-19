from __future__ import annotations

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

load_dotenv()

logger = logging.getLogger(__name__)


class Settings(BaseModel):
    telegram_bot_token: str
    crustdata_api_key: str
    gemini_api_key: str
    database_url: str = "sqlite:///placemate.db"
    watcher_poll_seconds: int = 60
    log_level: str = "INFO"
    rate_limit_messages_per_minute: int = 20
    rate_limit_api_calls_per_minute: int = 30
    session_ttl_seconds: int = 3600

    @field_validator("telegram_bot_token", "crustdata_api_key", "gemini_api_key")
    @classmethod
    def must_not_be_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must be set")
        return v.strip()


def load_settings() -> Settings:
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        crustdata_api_key=os.getenv("CRUSTDATA_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        database_url=os.getenv("DATABASE_URL", "sqlite:///placemate.db"),
        watcher_poll_seconds=int(os.getenv("WATCHER_POLL_SECONDS", "60")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        rate_limit_messages_per_minute=int(os.getenv("RATE_LIMIT_MESSAGES_PER_MINUTE", "20")),
        rate_limit_api_calls_per_minute=int(os.getenv("RATE_LIMIT_API_CALLS_PER_MINUTE", "30")),
        session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "3600")),
    )


settings = load_settings()
