from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from . import db
from .config import build_openai_client, load_config, load_tool_docs
from .logging_utils import setup_logging
from .repositories.chat_event_repository import ChatEventRepository
from .repositories.context_repository import ContextRepository
from .session import ChatSession


class SessionStore:
    """Lightweight factory for ChatSession instances backed entirely by SQLite history."""

    def __init__(
        self,
        cfg_path: str = "config.json",
        docs_path: Optional[str] = None,
        decision_provider=None,
        db_path: str | Path | None = None,
    ):
        self.cfg_path = Path(cfg_path).resolve()
        self.cfg = load_config(self.cfg_path)
        docs_path = docs_path or self.cfg["docs_filename"]
        self.docs = load_tool_docs(docs_path)
        self.logger = setup_logging(self.cfg.get("logging", {}))
        self.client: OpenAI = build_openai_client(self.cfg["openai_client"])
        self.decision_provider = decision_provider
        self.database = db.ChatDatabase(db_path) if db_path else db.DEFAULT_DB
        self.event_repo = ChatEventRepository(self.database)
        self.context_repo = ContextRepository(self.database)
        self.session_labels: Dict[str, str] = {}
        self.active_sessions: set[str] = set()
        self.active_versions: Dict[str, Optional[int]] = {} # session_id -> locked version

    @property
    def db_path(self) -> str:
        return self.database.path.as_posix()

    @property
    def config_file(self) -> str:
        return self.cfg_path.as_posix()

    def _deprecated_api(self, name: str, *args, **kwargs):
        message = f"[DEPRECATED] SessionStore.{name} called with args={args} kwargs={kwargs}"
        self.logger.warning(message)
        print(message)

    def submit_message(self, session_id: str, content: str) -> str:
        self._deprecated_api("submit_message", session_id, content)
        raise RuntimeError("SessionStore.submit_message is deprecated. Use session_runner.run_session_turn instead.")

    def task_status(self, task_id: str):
        self._deprecated_api("task_status", task_id)
        raise RuntimeError("SessionStore.task_status is deprecated. Tasks are no longer managed by SessionStore.")

    def resolve_audit(self, *args, **kwargs):
        self._deprecated_api("resolve_audit", *args, **kwargs)
        raise RuntimeError("SessionStore.resolve_audit is deprecated in the stateless runner mode.")

    def _default_label(self) -> str:
        return f"Session-{uuid.uuid4().hex[:8]}"

    def _build_session(self, session_id: str, label: str) -> ChatSession:
        session = ChatSession(
            session_id=session_id,
            cfg=self.cfg,
            docs=self.docs,
            logger=self.logger,
            client=self.client,
            decision_provider=self.decision_provider,
            label=label,
            event_repo=self.event_repo,
        )
        session.save_callback = lambda s: self.save_context_version(s, meta={"source": "auto_hop"})
        return session

    def _label_for(self, session_id: str) -> str:
        if session_id in self.session_labels:
            return self.session_labels[session_id]
        record = self.event_repo.get_session_record(session_id)
        if record:
            label = record.get("label") or session_id
            self.session_labels[session_id] = label
            return label
        raise KeyError(f"session not found: {session_id}")

    def create_session(self, name: Optional[str] = None) -> ChatSession:
        session_id = uuid.uuid4().hex
        label = (name or "").strip() or self._default_label()
        session = self._build_session(session_id, label)
        self.event_repo.register_session(session_id, label)
        self.session_labels[session_id] = label
        self.active_sessions.add(session_id)
        return session

    def _load_chat_session(
        self,
        session_id: str,
        *,
        version: int | None = None,
        user_tag: str | None = None,
        force_rebuild: bool = False,
    ) -> ChatSession:
        label = self._label_for(session_id)
        session = self._build_session(session_id, label)

        context_row = None
        # Only try to load a snapshot if explicitly requested via version or user_tag
        if not force_rebuild and (version is not None or user_tag is not None):
            if version is not None:
                context_row = self.context_repo.get_version(session_id, version)
            elif user_tag:
                context_row = self.context_repo.get_by_tag(session_id, user_tag)

        if context_row:
            meta = context_row.get("meta") or {}
            # Versioned History Filtering
            all_events = self.event_repo.list_by_session(session_id)
            last_idx = meta.get("last_event_idx")
            
            if last_idx is not None:
                # Primary filter: Event Index
                events = [e for e in all_events if e.get("index", 0) <= last_idx]
            else:
                # Fallback filter: Timestamp
                ts_boundary = context_row.get("created_at")
                # Use a slightly more strict comparison to avoid including events from the exact same instant
                # unless we are sure they belong to this snapshot.
                events = [e for e in all_events if e.get("timestamp") <= ts_boundary]
            
            session.load_from_context(
                context_row["messages"],
                events,
                version=context_row.get("version"),
                user_tag=context_row.get("user_tag"),
                meta=meta,
            )
        else:
            # DEFAULT PATH: Load full history from events.
            # This ensures that polling always reflects the absolute latest state in the DB.
            events = self.event_repo.list_by_session(session_id)
            session.load_from_history(events)

        self.session_labels[session_id] = label
        self.active_sessions.add(session_id)
        return session

    def get_session(
        self,
        session_id: str,
        *,
        version: int | None = None,
        user_tag: str | None = None,
        force_rebuild: bool = False,
    ) -> ChatSession:
        return self._load_chat_session(session_id, version=version, user_tag=user_tag, force_rebuild=force_rebuild)

    def session_summary(self, session_id: str) -> Dict[str, Any]:
        label = self._label_for(session_id)
        events = self.event_repo.list_by_session(session_id)
        ctx = self.context_repo.latest(session_id)
        status = "active" if session_id in self.active_sessions else "closed"
        return {
            "session_id": session_id,
            "label": label,
            "events": len(events),
            "status": status,
            "context_version": ctx.get("version") if ctx else None,
            "context_user_tag": ctx.get("user_tag") if ctx else None,
            "pending_audits": [],
        }

    def list_sessions(self):
        return [self.session_summary(session_id) for session_id in sorted(self.active_sessions)]

    def get_docs(self) -> Dict[str, Any]:
        return self.docs

    def load_session_from_history(
        self,
        session_id: str,
        *,
        version: int | None = None,
        user_tag: str | None = None,
        force_rebuild: bool = False,
    ) -> ChatSession:
        # Pass parameters to _load_chat_session
        session = self._load_chat_session(session_id, version=version, user_tag=user_tag, force_rebuild=force_rebuild)
        
        # Explicitly manage the version lock only during manual loads
        if version is not None or user_tag is not None:
            self.active_versions[session_id] = session.context_version
        elif force_rebuild:
            self.active_versions.pop(session_id, None)
            
        return session

    def clone_session_from_history(self, source_session_id: str, name: Optional[str]) -> ChatSession:
        events = self.event_repo.list_by_session(source_session_id)
        if not events:
            raise KeyError(f"session not found: {source_session_id}")
        session = self.create_session(name)
        self.event_repo.clone_events(source_session_id, session.id)
        cloned_events = self.event_repo.list_by_session(session.id)
        session.load_from_history(cloned_events)
        return session

    def save_context_version(
        self,
        session: ChatSession,
        *,
        user_tag: str | None = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        meta = meta or {}
        if session.context_version is not None:
            meta.setdefault("from_version", session.context_version)
        
        # Capture current event boundary from DB
        last_idx = self.event_repo.next_index(session.id) - 1
        meta["last_event_idx"] = last_idx
        self.logger.info(f"Saving version for session {session.id}. Anchoring to event index: {last_idx}")

        version = self.context_repo.save_version(session.id, session.messages, meta=meta, user_tag=user_tag)
        session.context_version = version
        session.context_user_tag = user_tag
        return version

    def refresh_context_from_events(self, session_id: str, *, user_tag: str | None = None) -> Dict[str, Any]:
        label = self._label_for(session_id)
        events = self.event_repo.list_by_session(session_id)
        session = self._build_session(session_id, label)
        session.load_from_history(events)
        version = self.save_context_version(session, user_tag=user_tag, meta={"source": "rebuild", "events": len(events)})
        return {"session_id": session_id, "version": version, "user_tag": user_tag}

    def close_session(self, session_id: str) -> Dict[str, Any]:
        label = self._label_for(session_id)
        was_active = session_id in self.active_sessions
        self.active_sessions.discard(session_id)
        self.active_versions.pop(session_id, None)
        return {"session_id": session_id, "label": label, "status": "closed" if was_active else "inactive"}

    def is_active(self, session_id: str) -> bool:
        return session_id in self.active_sessions
