from __future__ import annotations

from pydantic import BaseModel, field_validator


class StudentCreate(BaseModel):
    tg_id: int
    name: str
    college: str
    resume_text: str = ""
    skills: list[str] = []
    target_roles: str = ""
    location: str = ""

    @field_validator("name", "college")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field must not be empty")
        return stripped


class StudentRecord(BaseModel):
    id: int
    tg_id: int
    name: str
    college: str
    year: str = ""
    resume_text: str = ""
    skills: list[str] = []
    target_roles: str = ""
    location: str = ""
