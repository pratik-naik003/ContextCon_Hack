from __future__ import annotations

from pydantic import BaseModel


class CrustdataEvent(BaseModel):
    company_id: str
    company_name: str
    event_type: str
    payload: dict


class EventRecord(BaseModel):
    id: int
    company_id: str
    company_name: str
    event_type: str
    payload_json: str
    fetched_at: str = ""
