from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SessionPayload(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60, description="Optional session label")


class MessagePayload(BaseModel):
    content: str = Field(..., description="User message content")
    context_version: Optional[int] = Field(default=None, description="Optional context version to load")
    user_tag: Optional[str] = Field(default=None, description="Optional context user tag to load")


class AuditPayload(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$", description="Audit decision result")
    actor: Optional[str] = Field(default="user", description="Actor making the decision")
    note: Optional[str] = Field(default=None, description="Optional audit note")


class HistoryLoadPayload(BaseModel):
    version: Optional[int] = Field(default=None, description="Context version to load")
    user_tag: Optional[str] = Field(default=None, description="Context user tag to load")
    from_events: bool = Field(default=False, description="Force rebuild context from events")


class ContextCompressPayload(BaseModel):
    version: Optional[int] = Field(default=None, description="Context version to compress")
    user_tag: Optional[str] = Field(default=None, description="Context tag to compress")
    new_tag: Optional[str] = Field(default=None, description="Optional tag for compressed context")
