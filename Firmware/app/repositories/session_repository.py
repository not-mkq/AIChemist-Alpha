from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..session import ChatSession
from ..store import SessionStore


class SessionRepository:
    """Thin wrapper around SessionStore to enable dependency injection and testing."""

    def __init__(self, store: Optional[SessionStore] = None):
        self.store = store or SessionStore()

    @property
    def config(self) -> Dict[str, Any]:
        return self.store.cfg

    @property
    def config_path(self) -> str:
        return self.store.config_file

    @property
    def db_path(self) -> str:
        return self.store.db_path

    def create_session(self, name: Optional[str] = None) -> ChatSession:
        return self.store.create_session(name)

    def list_sessions(self):
        return self.store.list_sessions()

    def get_session(
        self,
        session_id: str,
        *,
        version: int | None = None,
        user_tag: str | None = None,
        force_rebuild: bool = False,
    ) -> ChatSession:
        return self.store.get_session(session_id, version=version, user_tag=user_tag, force_rebuild=force_rebuild)

    def session_summary(self, session_id: str) -> Dict[str, Any]:
        return self.store.session_summary(session_id)

    def submit_message(self, session_id: str, content: str) -> str:
        return self.store.submit_message(session_id, content)

    def task_status(self, task_id: str):
        return self.store.task_status(task_id)

    def resolve_audit(self, session_id: str, audit_id: str, approved: bool, actor: str, note: Optional[str]):
        return self.store.resolve_audit(session_id, audit_id, approved, actor, note)

    def get_docs(self) -> Dict[str, Any]:
        return self.store.get_docs()

    def get_log_path(self) -> Optional[str]:
        return getattr(self.store.logger, "logfile", None)

    def context_latest(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.store.context_repo.latest(session_id)

    def context_version(self, session_id: str, version: int) -> Optional[Dict[str, Any]]:
        return self.store.context_repo.get_version(session_id, version)

    def context_by_tag(self, session_id: str, user_tag: str) -> Optional[Dict[str, Any]]:
        return self.store.context_repo.get_by_tag(session_id, user_tag)

    def refresh_context(self, session_id: str, user_tag: Optional[str] = None) -> Dict[str, Any]:
        return self.store.refresh_context_from_events(session_id, user_tag=user_tag)

    def delete_contexts(self, session_id: str) -> None:
        return self.store.context_repo.delete_session(session_id)

    @property
    def context_repo(self):
        return self.store.context_repo

    def list_context_versions(self, session_id: str) -> List[Dict[str, Any]]:
        return self.store.context_repo.list_versions(session_id)

    def save_context_version(self, session, *, user_tag: str | None = None, meta: Dict[str, Any] | None = None) -> int:
        return self.store.save_context_version(session, user_tag=user_tag, meta=meta)

    def load_session_from_history(
        self,
        session_id: str,
        *,
        version: int | None = None,
        user_tag: str | None = None,
        force_rebuild: bool = False,
    ) -> ChatSession:
        return self.store.load_session_from_history(session_id, version=version, user_tag=user_tag, force_rebuild=force_rebuild)

    def clone_session_from_history(self, session_id: str, name: Optional[str]) -> ChatSession:
        return self.store.clone_session_from_history(session_id, name)

    def close_session(self, session_id: str):
        return self.store.close_session(session_id)

    def is_active(self, session_id: str) -> bool:
        return self.store.is_active(session_id)
