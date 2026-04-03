from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import db


class ChatEventRepository:
    def __init__(self, database: db.ChatDatabase | None = None):
        self.database = database

    def append(
        self,
        *,
        session_id: str,
        index: int,
        type_: str,
        actor: str,
        timestamp: str,
        content: Optional[str],
        payload: Optional[Dict[str, Any]] = None,
        flags: Optional[Dict[str, Any]] = None,
    ) -> None:
        kwargs = {"database": self.database} if self.database else {}
        db.insert_event(
            session_id=session_id,
            index=index,
            type_=type_,
            actor=actor,
            timestamp=timestamp,
            content=content,
            payload=payload,
            flags=flags,
            **kwargs,
        )

    def list_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        kwargs = {"database": self.database} if self.database else {}
        return db.list_events(session_id, **kwargs)

    def next_index(self, session_id: str) -> int:
        kwargs = {"database": self.database} if self.database else {}
        return db.max_index(session_id, **kwargs) + 1

    def list_sessions_overview(self) -> List[Dict[str, Any]]:
        kwargs = {"database": self.database} if self.database else {}
        return db.list_sessions_overview(**kwargs)

    def delete_session(self, session_id: str) -> int:
        kwargs = {"database": self.database} if self.database else {}
        return db.delete_session_events(session_id, **kwargs)

    def clone_events(self, source_session_id: str, target_session_id: str) -> None:
        kwargs = {"database": self.database} if self.database else {}
        db.clone_session_events(source_session_id, target_session_id, **kwargs)

    def register_session(self, session_id: str, label: str) -> None:
        kwargs = {"database": self.database} if self.database else {}
        db.upsert_session_record(session_id, label, **kwargs)

    def get_session_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        kwargs = {"database": self.database} if self.database else {}
        return db.get_session_record(session_id, **kwargs)

    def get_session_label(self, session_id: str) -> Optional[str]:
        record = self.get_session_record(session_id)
        if not record:
            return None
        return record.get("label")
