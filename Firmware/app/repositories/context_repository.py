from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import db


class ContextRepository:
    def __init__(self, database: db.ChatDatabase | None = None):
        self.database = database or db.DEFAULT_DB

    def save_version(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        *,
        meta: Optional[Dict[str, Any]] = None,
        user_tag: Optional[str] = None,
        version: Optional[int] = None,
    ) -> int:
        return db.insert_context_version(
            session_id,
            messages,
            meta=meta,
            user_tag=user_tag,
            version=version,
            database=self.database,
        )

    def latest(self, session_id: str) -> Optional[Dict[str, Any]]:
        return db.get_latest_context(session_id, database=self.database)

    def get_version(self, session_id: str, version: int) -> Optional[Dict[str, Any]]:
        return db.get_context_by_version(session_id, version, database=self.database)

    def get_by_tag(self, session_id: str, user_tag: str) -> Optional[Dict[str, Any]]:
        return db.get_context_by_tag(session_id, user_tag, database=self.database)

    def list_versions(self, session_id: str) -> List[Dict[str, Any]]:
        return db.list_context_versions(session_id, database=self.database)

    def delete_session(self, session_id: str) -> None:
        db.delete_context_versions(session_id, database=self.database)
