from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Dict, Optional, Tuple

from .store import SessionStore

_STORE_CACHE: Dict[Tuple[str, str], SessionStore] = {}
_RUNNING_SESSIONS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def _cache_key(cfg_path: str, db_path: Optional[str]) -> Tuple[str, str]:
    cfg_key = str(Path(cfg_path).resolve())
    db_key = str(Path(db_path).resolve()) if db_path else ""
    return cfg_key, db_key


def _get_store(cfg_path: str, db_path: Optional[str]) -> SessionStore:
    key = _cache_key(cfg_path, db_path)
    store = _STORE_CACHE.get(key)
    if store is None:
        store = SessionStore(cfg_path=cfg_path, db_path=db_path)
        _STORE_CACHE[key] = store
    return store


def _register_session(session_id: str, data: Dict[str, Any]):
    with _LOCK:
        if session_id in _RUNNING_SESSIONS:
            raise RuntimeError(f"session already running: {session_id}")
        _RUNNING_SESSIONS[session_id] = data


def _unregister_session(session_id: str):
    with _LOCK:
        _RUNNING_SESSIONS.pop(session_id, None)


def run_session_turn(
    session_id: str,
    db_path: str,
    user_input: str,
    *,
    cfg_path: str = "config.json",
    context_version: int | None = None,
    user_tag: str | None = None,
):
    """Process a user turn by rebuilding context from SQLite and streaming events to the DB."""
    store = _get_store(cfg_path, db_path)
    session = store.get_session(session_id, version=context_version, user_tag=user_tag)
    _register_session(session_id, {"session": session})
    try:
        events = session.process_user_message(user_input)
        store.save_context_version(session, user_tag=user_tag, meta={"source": "append"})
    except Exception:
        # Emergency save: ensure partial progress/events are not lost if the run crashes (e.g. OpenAI error)
        store.save_context_version(session, user_tag=user_tag, meta={"source": "crash_recovery"})
        raise
    finally:
        _unregister_session(session_id)
    return {"session_id": session_id, "events": events}


def resolve_audit_ticket(session_id: str, audit_id: str, decision: bool, actor: Optional[str], note: Optional[str]):
    with _LOCK:
        entry = _RUNNING_SESSIONS.get(session_id)
    if not entry:
        raise KeyError(f"session not active: {session_id}")
    chat_session = entry["session"]
    return chat_session.resolve_audit(audit_id, approved=decision, actor=actor or "user", note=note)
