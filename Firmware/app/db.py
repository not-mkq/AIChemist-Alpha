from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CHAT_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    type TEXT NOT NULL,
    actor TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    content TEXT,
    payload_json TEXT,
    flags_json TEXT,
    UNIQUE(session_id, idx)
);
CREATE INDEX IF NOT EXISTS chat_events_session_idx
    ON chat_events(session_id, idx);
"""

CHAT_CONTEXT_VERSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_context_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    user_tag TEXT,
    messages_json TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, version),
    UNIQUE(session_id, user_tag)
);
CREATE INDEX IF NOT EXISTS chat_context_versions_session_idx
    ON chat_context_versions(session_id);
"""

SESSION_RECORDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_records (
    session_id TEXT PRIMARY KEY,
    label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class ChatDatabase:
    """Lightweight wrapper around the SQLite database backing chat events."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(CHAT_EVENTS_SCHEMA)
            conn.executescript(CHAT_CONTEXT_VERSIONS_SCHEMA)
        self.ensure_session_records_table()

    def ensure_session_records_table(self) -> None:
        with self.connect() as conn:
            cols = [row["name"] for row in conn.execute("PRAGMA table_info(session_records)")]
            if not cols:
                conn.executescript(SESSION_RECORDS_SCHEMA)
                return
            if "archived" in cols:
                conn.executescript(
                    """
                    CREATE TABLE session_records_new (
                        session_id TEXT PRIMARY KEY,
                        label TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO session_records_new (session_id, label, created_at, updated_at)
                    SELECT session_id, label, created_at, updated_at FROM session_records;
                    DROP TABLE session_records;
                    ALTER TABLE session_records_new RENAME TO session_records;
                    """
                )


DEFAULT_DB = ChatDatabase(os.environ.get("CHAT_DB_PATH", "data/chat_events.db"))


def _db(database: ChatDatabase | None = None) -> ChatDatabase:
    return database or DEFAULT_DB


def get_connection(database: ChatDatabase | None = None) -> sqlite3.Connection:
    return _db(database).connect()


def ensure_schema(database: ChatDatabase | None = None) -> None:
    _db(database).ensure_schema()


def ensure_session_records_table(database: ChatDatabase | None = None) -> None:
    _db(database).ensure_session_records_table()


def to_json(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def from_row(row: sqlite3.Row) -> Dict[str, Any]:
    payload = row["payload_json"]
    flags = row["flags_json"]
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "index": row["idx"],
        "type": row["type"],
        "actor": row["actor"],
        "timestamp": row["timestamp"],
        "content": row["content"],
        "payload": json.loads(payload) if payload else None,
        "flags": json.loads(flags) if flags else None,
    }


def insert_event(
    *,
    session_id: str,
    index: int,
    type_: str,
    actor: str,
    timestamp: str,
    content: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
    flags: Optional[Dict[str, Any]] = None,
    database: ChatDatabase | None = None,
) -> None:
    with get_connection(database) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO chat_events
                (session_id, idx, type, actor, timestamp, content, payload_json, flags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                index,
                type_,
                actor,
                timestamp,
                content,
                to_json(payload),
                to_json(flags),
            ),
        )


def list_events(session_id: str, database: ChatDatabase | None = None) -> List[Dict[str, Any]]:
    with get_connection(database) as conn:
        rows = conn.execute(
            "SELECT * FROM chat_events WHERE session_id=? ORDER BY idx ASC",
            (session_id,),
        ).fetchall()
    return [from_row(row) for row in rows]


def max_index(session_id: str, database: ChatDatabase | None = None) -> int:
    with get_connection(database) as conn:
        row = conn.execute(
            "SELECT MAX(idx) AS max_idx FROM chat_events WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return int(row["max_idx"] or 0)


def upsert_session_record(
    session_id: str,
    label: str,
    timestamp: Optional[str] = None,
    *,
    database: ChatDatabase | None = None,
) -> None:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    with get_connection(database) as conn:
        conn.execute(
            """
            INSERT INTO session_records(session_id, label, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              label=excluded.label,
              updated_at=excluded.updated_at
            """,
            (session_id, label, ts, ts),
        )


def touch_session_record(session_id: str, timestamp: str, *, database: ChatDatabase | None = None) -> None:
    with get_connection(database) as conn:
        conn.execute(
            """
            UPDATE session_records
            SET updated_at=?
            WHERE session_id=?
            """,
            (timestamp, session_id),
        )


def get_session_record(session_id: str, database: ChatDatabase | None = None) -> Optional[Dict[str, Any]]:
    with get_connection(database) as conn:
        row = conn.execute(
            "SELECT * FROM session_records WHERE session_id=?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def delete_session_record(session_id: str, database: ChatDatabase | None = None) -> None:
    with get_connection(database) as conn:
        conn.execute("DELETE FROM session_records WHERE session_id=?", (session_id,))


def list_sessions_overview(database: ChatDatabase | None = None) -> List[Dict[str, Any]]:
    with get_connection(database) as conn:
        rows = conn.execute(
            """
            WITH stats AS (
                SELECT
                    session_id,
                    COUNT(*) AS event_count,
                    MIN(timestamp) AS first_event,
                    MAX(timestamp) AS last_event
                FROM chat_events
                GROUP BY session_id
            )
            SELECT
                stats.session_id,
                COALESCE(sr.label, stats.session_id) AS label,
                COALESCE(sr.created_at, stats.first_event) AS created_at,
                COALESCE(sr.updated_at, stats.last_event) AS updated_at,
                stats.first_event,
                stats.last_event,
                stats.event_count AS events
            FROM stats
            LEFT JOIN session_records sr ON sr.session_id = stats.session_id
            ORDER BY stats.last_event DESC
            """
        ).fetchall()
    return [
        {
            "session_id": row["session_id"],
            "label": row["label"],
            "first_event": row["first_event"],
            "last_event": row["last_event"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "events": row["events"],
        }
        for row in rows
    ]


def delete_session_events(session_id: str, database: ChatDatabase | None = None) -> int:
    with get_connection(database) as conn:
        cur = conn.execute("DELETE FROM chat_events WHERE session_id=?", (session_id,))
        conn.commit()
    delete_session_record(session_id, database=database)
    return cur.rowcount

# ---------------- context versions ----------------


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def insert_context_version(
    session_id: str,
    messages: List[Dict[str, Any]],
    *,
    meta: Optional[Dict[str, Any]] = None,
    user_tag: Optional[str] = None,
    version: Optional[int] = None,
    timestamp: Optional[str] = None,
    database: ChatDatabase | None = None,
) -> int:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    with get_connection(database) as conn:
        if version is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS max_version FROM chat_context_versions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            version = int(row["max_version"] or 0) + 1
        conn.execute(
            """
            INSERT INTO chat_context_versions (session_id, version, user_tag, messages_json, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, version, user_tag, _serialize(messages), _serialize(meta or {}), ts),
        )
    return version


def _context_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "version": row["version"],
        "user_tag": row["user_tag"],
        "messages": json.loads(row["messages_json"]),
        "meta": json.loads(row["meta_json"] or "{}"),
        "created_at": row["created_at"],
    }


def get_latest_context(session_id: str, database: ChatDatabase | None = None) -> Optional[Dict[str, Any]]:
    with get_connection(database) as conn:
        row = conn.execute(
            """
            SELECT * FROM chat_context_versions
            WHERE session_id=?
            ORDER BY version DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return _context_from_row(row)


def get_context_by_version(session_id: str, version: int, database: ChatDatabase | None = None) -> Optional[Dict[str, Any]]:
    with get_connection(database) as conn:
        row = conn.execute(
            "SELECT * FROM chat_context_versions WHERE session_id=? AND version=?",
            (session_id, version),
        ).fetchone()
    if not row:
        return None
    return _context_from_row(row)


def get_context_by_tag(session_id: str, user_tag: str, database: ChatDatabase | None = None) -> Optional[Dict[str, Any]]:
    with get_connection(database) as conn:
        row = conn.execute(
            "SELECT * FROM chat_context_versions WHERE session_id=? AND user_tag=?",
            (session_id, user_tag),
        ).fetchone()
    if not row:
        return None
    return _context_from_row(row)


def list_context_versions(session_id: str, database: ChatDatabase | None = None) -> List[Dict[str, Any]]:
    with get_connection(database) as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, version, user_tag, created_at
            FROM chat_context_versions
            WHERE session_id=?
            ORDER BY version DESC
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_context_versions(session_id: str, database: ChatDatabase | None = None) -> None:
    with get_connection(database) as conn:
        conn.execute("DELETE FROM chat_context_versions WHERE session_id=?", (session_id,))


def clone_session_events(
    source_session_id: str,
    target_session_id: str,
    database: ChatDatabase | None = None,
) -> None:
    with get_connection(database) as conn:
        rows = conn.execute(
            """
            SELECT type, actor, timestamp, content, payload_json, flags_json
            FROM chat_events
            WHERE session_id=?
            ORDER BY idx ASC
            """,
            (source_session_id,),
        ).fetchall()
        next_idx = (
            conn.execute(
                "SELECT COALESCE(MAX(idx), 0) FROM chat_events WHERE session_id=?",
                (target_session_id,),
            ).fetchone()[0]
            + 1
        )
        for offset, row in enumerate(rows):
            conn.execute(
                """
                INSERT INTO chat_events
                    (session_id, idx, type, actor, timestamp, content, payload_json, flags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_session_id,
                    next_idx + offset,
                    row["type"],
                    row["actor"],
                    row["timestamp"],
                    row["content"],
                    row["payload_json"],
                    row["flags_json"],
                ),
            )
