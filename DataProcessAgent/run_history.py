"""
run_history.py

Helper utilities for recording single-tool run input/output relationships.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import textwrap
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from db import retry_on_lock

# Global locks for run_id to prevent race conditions on iteration_index
_run_locks: Dict[str, threading.Lock] = {}
_run_locks_mutex = threading.Lock()

def _get_run_lock(run_id: str) -> threading.Lock:
    with _run_locks_mutex:
        if run_id not in _run_locks:
            _run_locks[run_id] = threading.Lock()
        return _run_locks[run_id]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)

def get_next_iteration_index(conn: sqlite3.Connection, run_id: str) -> int:
    """Return the next iteration index for a given run_id."""
    cur = conn.execute(
        """
        SELECT COALESCE(MAX(iteration_index), -1) AS max_idx
        FROM tool_run_history
        WHERE run_id = ?;
        """,
        (run_id,),
    )
    row = cur.fetchone()
    max_idx = row["max_idx"] if row and row["max_idx"] is not None else -1
    return int(max_idx) + 1


@retry_on_lock()
def start_run_history(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    tool_instance: str,
    code_name: str,
    tool_type: str,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    iteration_index: Optional[int] = None,
) -> int:
    # If iteration_index is explicit, use it.
    # Otherwise, calculate atomically using subquery.
    
    if iteration_index is not None:
        cur = conn.execute(
            """
            INSERT INTO tool_run_history (
                run_id, tool_instance, code_name, tool_type,
                project, batch, item, scope, iteration_index, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running');
            """,
            (
                run_id,
                tool_instance,
                code_name,
                tool_type,
                project,
                batch,
                item,
                scope,
                iteration_index,
            ),
        )
    else:
        # Atomic auto-increment
        cur = conn.execute(
            """
            INSERT INTO tool_run_history (
                run_id, tool_instance, code_name, tool_type,
                project, batch, item, scope, iteration_index, status
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                (SELECT COALESCE(MAX(iteration_index), -1) + 1 FROM tool_run_history WHERE run_id = ?),
                'running'
            );
            """,
            (
                run_id,
                tool_instance,
                code_name,
                tool_type,
                project,
                batch,
                item,
                scope,
                run_id, # Parameter for the subquery
            ),
        )
        
    conn.commit()
    return int(cur.lastrowid)


@retry_on_lock()
def finish_run_history(
    conn: sqlite3.Connection,
    history_id: int,
    *,
    status: str,
    error_reason: Optional[str] = None,
    extra: Optional[Any] = None,
) -> None:
    extra_json = _json_dumps(extra) if extra is not None else None
    conn.execute(
        """
        UPDATE tool_run_history
        SET status = ?, error_reason = ?, extra = ?, finished_at = datetime('now')
        WHERE id = ?;
        """,
        (status, error_reason, extra_json, history_id),
    )
    conn.commit()


@retry_on_lock()
def log_file_inputs(
    conn: sqlite3.Connection,
    history_id: int,
    entries: Iterable[dict],
) -> None:
    to_insert: List[tuple] = []
    for entry in entries:
        to_insert.append(
            (
                history_id,
                entry.get("param_name"),
                entry.get("label"),
                entry.get("filename"),
            )
        )
    if not to_insert:
        return
    conn.executemany(
        """
        INSERT INTO tool_run_file_inputs (history_id, param_name, label, filename)
        VALUES (?, ?, ?, ?);
        """,
        to_insert,
    )
    conn.commit()


@retry_on_lock()
def log_result_inputs(
    conn: sqlite3.Connection,
    history_id: int,
    entries: Iterable[dict],
) -> None:
    to_insert: List[tuple] = []
    for entry in entries:
        to_insert.append(
            (
                history_id,
                entry.get("param_name"),
                entry.get("result_col"),
                _json_dumps(entry.get("value")),
            )
        )
    if not to_insert:
        return
    conn.executemany(
        """
        INSERT INTO tool_run_result_inputs (history_id, param_name, result_col, value_json)
        VALUES (?, ?, ?, ?);
        """,
        to_insert,
    )
    conn.commit()


@retry_on_lock()
def log_run_params(
    conn: sqlite3.Connection,
    history_id: int,
    params: dict,
) -> None:
    if not params:
        return
    to_insert = []
    for key, value in params.items():
        if value is None:
            continue
        to_insert.append((history_id, key, _json_dumps(value)))
    if not to_insert:
        return
    conn.executemany(
        """
        INSERT INTO tool_run_params (history_id, param_name, value_json)
        VALUES (?, ?, ?);
        """,
        to_insert,
    )
    conn.commit()


@retry_on_lock()
def log_file_outputs(
    conn: sqlite3.Connection,
    history_id: int,
    entries: Iterable[dict],
) -> None:
    to_insert: List[tuple] = []
    for entry in entries:
        to_insert.append(
            (
                history_id,
                entry.get("label"),
                entry.get("filename"),
            )
        )
    if not to_insert:
        return
    conn.executemany(
        """
        INSERT INTO tool_run_file_outputs (history_id, label, filename)
        VALUES (?, ?, ?);
        """,
        to_insert,
    )
    conn.commit()


@retry_on_lock()
def log_result_outputs(
    conn: sqlite3.Connection,
    history_id: int,
    entries: Iterable[dict],
) -> None:
    to_insert: List[tuple] = []
    for entry in entries:
        to_insert.append(
            (
                history_id,
                entry.get("result_col"),
                _json_dumps(entry.get("value")),
            )
        )
    if not to_insert:
        return
    conn.executemany(
        """
        INSERT INTO tool_run_result_outputs (history_id, result_col, value_json)
        VALUES (?, ?, ?);
        """,
        to_insert,
    )
    conn.commit()


# =========================
# Graph building helpers
# =========================

_FILE_PALETTE = [
    "#4C78A8",
    "#F58518",
    "#E45756",
    "#72B7B2",
    "#54A24B",
    "#EECA3B",
    "#B279A2",
    "#FF9DA6",
    "#9D755D",
    "#BAB0AC",
]

_RESULT_PALETTE = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]

_PARAM_PALETTE = [
    "#6B5B95",
    "#88B04B",
    "#F7CAC9",
    "#92A8D1",
    "#955251",
    "#B565A7",
    "#009B77",
    "#DD4124",
    "#45B8AC",
    "#EFC050",
]


def _wrap_label(text: str, width: int = 18) -> str:
    lines: List[str] = []
    for part in text.split("\n"):
        wrapped = textwrap.wrap(part, width=width) or [""]
        lines.extend(wrapped)
    return "\n".join(lines)


def _escape_label(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _color_for(key: str, palette: List[str]) -> str:
    if not key:
        return palette[0]
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    idx = digest[0] % len(palette)
    return palette[idx]


def _safe_id(prefix: str, key: str) -> str:
    base = re.sub(r"[^0-9A-Za-z_]", "_", key or prefix)
    base = base[:24] if len(base) > 24 else base
    digest = hashlib.sha1((prefix + key).encode("utf-8")).hexdigest()[:6]
    return f"{prefix}_{base}_{digest}"


def _format_value(value_json: Optional[str]) -> str:
    if value_json is None:
        return "null"
    try:
        value = json.loads(value_json)
    except Exception:
        return value_json
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def build_run_history_dot(conn: sqlite3.Connection, run_id: str) -> str:
    history_rows = conn.execute(
        """
        SELECT *
        FROM tool_run_history
        WHERE run_id = ?
        ORDER BY iteration_index ASC, id ASC;
        """,
        (run_id,),
    ).fetchall()
    if not history_rows:
        raise ValueError(f"run_id '{run_id}' not found")

    def fetch_related(query: str) -> List[sqlite3.Row]:
        return conn.execute(query, (run_id,)).fetchall()

    file_inputs = fetch_related(
        """
        SELECT fi.*, h.tool_instance, h.id AS history_id
        FROM tool_run_file_inputs fi
        JOIN tool_run_history h ON h.id = fi.history_id
        WHERE h.run_id = ?;
        """
    )
    file_outputs = fetch_related(
        """
        SELECT fo.*, h.tool_instance, h.id AS history_id
        FROM tool_run_file_outputs fo
        JOIN tool_run_history h ON h.id = fo.history_id
        WHERE h.run_id = ?;
        """
    )
    result_inputs = fetch_related(
        """
        SELECT ri.*, h.tool_instance, h.id AS history_id
        FROM tool_run_result_inputs ri
        JOIN tool_run_history h ON h.id = ri.history_id
        WHERE h.run_id = ?;
        """
    )
    result_outputs = fetch_related(
        """
        SELECT ro.*, h.tool_instance, h.id AS history_id
        FROM tool_run_result_outputs ro
        JOIN tool_run_history h ON h.id = ro.history_id
        WHERE h.run_id = ?;
        """
    )
    run_params = fetch_related(
        """
        SELECT rp.*, h.tool_instance, h.id AS history_id
        FROM tool_run_params rp
        JOIN tool_run_history h ON h.id = rp.history_id
        WHERE h.run_id = ?;
        """
    )

    file_nodes: Dict[str, Dict[str, Any]] = {}
    for entry in file_inputs + file_outputs:
        filename = entry["filename"] or "(unknown)"
        key = filename
        meta = file_nodes.setdefault(
            key, {"filename": filename, "labels": set()}
        )
        label = entry["label"]
        if label:
            meta["labels"].add(label)

    result_nodes: Dict[str, Dict[str, Any]] = {}
    for entry in result_inputs + result_outputs:
        col = entry["result_col"] or "(unknown)"
        meta = result_nodes.setdefault(col, {"values": set()})
        value = _format_value(entry["value_json"])
        if value != "null":
            meta["values"].add(value)

    tool_nodes: Dict[int, str] = {}

    param_nodes: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for entry in run_params:
        key = (entry["history_id"], entry["param_name"] or "")
        if key not in param_nodes:
            param_nodes[key] = {
                "value": _format_value(entry["value_json"]),
                "history_id": entry["history_id"],
                "name": entry["param_name"] or "",
            }
    # 过滤值为 null 的参数
    param_nodes = {
        key: meta for key, meta in param_nodes.items() if meta["value"] != "null"
    }

    dot_lines: List[str] = [
        "digraph run_history {",
        '  graph [rankdir=LR, splines=true, overlap=false, fontname="Helvetica"];',
        '  node [fontname="Helvetica", shape=box];',
        '  edge [fontname="Helvetica"];',
    ]

    run_node_id = _safe_id("run", run_id)
    run_label = _escape_label(_wrap_label(f"Run\n{run_id}"))
    dot_lines.append(
        f'  "{run_node_id}" [shape=hexagon, style="filled", fillcolor="#e0f7fa", label="{run_label}"];'
    )

    # Tool nodes
    for row in history_rows:
        tool_node_id = _safe_id("tool", f"{row['id']}_{row['tool_instance']}")
        status = row["status"] or "unknown"
        label = _wrap_label(
            f"{row['tool_instance']}\n#{row['iteration_index']} ({status})"
        )
        label = _escape_label(label)
        dot_lines.append(
            f'  "{tool_node_id}" [shape=box, style="filled", fillcolor="#d1e8ff", label="{label}"];'
        )
        dot_lines.append(f'  "{run_node_id}" -> "{tool_node_id}" [color="#9ecae9"];')
        tool_nodes[row["id"]] = tool_node_id

    # File nodes
    file_node_ids: Dict[str, str] = {}
    for key, meta in file_nodes.items():
        labels = ", ".join(sorted(meta["labels"])) if meta["labels"] else "-"
        text = f"文件\n{labels}\n{meta['filename']}"
        label = _escape_label(_wrap_label(text))
        node_id = _safe_id("file", key)
        color = _color_for(key, _FILE_PALETTE)
        dot_lines.append(
            f'  "{node_id}" [shape=folder, style="filled", fillcolor="{color}", color="{color}", label="{label}"];'
        )
        file_node_ids[key] = node_id

    # Result nodes
    result_node_ids: Dict[str, str] = {}
    for col, meta in result_nodes.items():
        values = ", ".join(sorted(meta["values"])) if meta["values"] else ""
        if values:
            text = f"结果列\n{col}\n值: {values}"
        else:
            text = f"结果列\n{col}"
        label = _escape_label(_wrap_label(text))
        node_id = _safe_id("result", col)
        color = _color_for(col, _RESULT_PALETTE)
        dot_lines.append(
            f'  "{node_id}" [shape=ellipse, style="filled", fillcolor="{color}", color="{color}", label="{label}"];'
        )
        result_node_ids[col] = node_id

    # Param nodes
    param_node_ids: Dict[Tuple[int, str], str] = {}
    for key, meta in param_nodes.items():
        text = f"参数\n{meta['name']}\n{meta['value']}"
        label = _escape_label(_wrap_label(text))
        node_id = _safe_id("param", f"{meta['history_id']}_{meta['name']}")
        color = _color_for(meta["name"] or str(meta["history_id"]), _PARAM_PALETTE)
        dot_lines.append(
            f'  "{node_id}" [shape=note, style="filled", fillcolor="{color}", color="{color}", label="{label}"];'
        )
        param_node_ids[key] = node_id

    def add_edge(src: str, dst: str, label: Optional[str] = None, color: str = "#636363"):
        if label:
            lbl = _escape_label(_wrap_label(label))
            dot_lines.append(
                f'  "{src}" -> "{dst}" [color="{color}", label="{lbl}"];'
            )
        else:
            dot_lines.append(f'  "{src}" -> "{dst}" [color="{color}"];')

    # File input edges
    for entry in file_inputs:
        filename = entry["filename"] or "(unknown)"
        node_id = file_node_ids.get(filename)
        tool_node = tool_nodes.get(entry["history_id"])
        if node_id and tool_node:
            param = entry["param_name"] or ""
            lbl = entry["label"] or ""
            label = f"{param}\n{lbl}".strip()
            add_edge(node_id, tool_node, label=label or None)

    # File output edges
    for entry in file_outputs:
        filename = entry["filename"] or "(unknown)"
        node_id = file_node_ids.get(filename)
        tool_node = tool_nodes.get(entry["history_id"])
        if node_id and tool_node:
            label = entry["label"]
            add_edge(tool_node, node_id, label=label or None)

    # Result input edges
    for entry in result_inputs:
        col = entry["result_col"] or "(unknown)"
        node_id = result_node_ids.get(col)
        tool_node = tool_nodes.get(entry["history_id"])
        if node_id and tool_node:
            label = entry["param_name"]
            add_edge(node_id, tool_node, label=label or None, color="#8c6bb1")

    # Result output edges
    for entry in result_outputs:
        col = entry["result_col"] or "(unknown)"
        node_id = result_node_ids.get(col)
        tool_node = tool_nodes.get(entry["history_id"])
        if node_id and tool_node:
            add_edge(tool_node, node_id, label=None, color="#8c6bb1")

    # Parameter edges
    for key, node_id in param_node_ids.items():
        history_id, _ = key
        tool_node = tool_nodes.get(history_id)
        if tool_node:
            add_edge(node_id, tool_node, label=None, color="#aaaaaa")

    dot_lines.append("}")
    return "\n".join(dot_lines)


def render_dot_to_svg(dot_source: str) -> str:
    try:
        result = subprocess.run(
            ["dot", "-Tsvg"],
            input=dot_source.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Graphviz 'dot' command not found") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"Graphviz failed: {stderr.strip()}") from exc
    return result.stdout.decode("utf-8")
