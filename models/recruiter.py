from __future__ import annotations

from pydantic import BaseModel


class RecruiterRecord(BaseModel):
    id: int
    tg_id: int
    email: str = ""
    company: str = ""
    title: str = ""
    verified: bool = False
