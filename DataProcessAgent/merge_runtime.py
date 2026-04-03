"""
merge_runtime.py

运行 merge 工具，负责三种模式：
- batch_from_items   : 在某个 batch 上汇总该 batch 下所有 item
- project_from_items: 在 project 上汇总所有 item
- project_from_batches: 在 project 上汇总所有 batch

特点：
- 输入按 label 收集下一级的文件（假设每个 item/batch 同一 label 只有一个文件）
- 运行时把输入文件 copy 到 /tmp 下，命名为 <prj>@<batch>@<item>@<filename>
- 输出文件写入 batch_files/prj_files，对应的 label 写入 batch_file_labels/prj_file_labels
- 输出数值写入 batch_results/prj_results（覆盖旧值）
"""

from __future__ import annotations

import contextvars
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from db import (
    get_connection,
    create_batch_file,
    create_prj_file,
    add_batch_file_label,
    add_prj_file_label,
)
from tool_runtime import _get_project_tool_config, _resolve_run_params  # 重用配置读取与参数解析
from request_checker import check_merge_tool_request, get_run_param_type_map
from param_value_utils import extract_wrapped_mapping

WORKSPACE_ROOT = os.path.abspath("workspace")


# =========================
# 注册表
# =========================

@dataclass
class MergeToolInfo:
    name: str
    func: Callable[..., Any]
    comment: Optional[str] = None  # Markdown 格式的注释，描述工具功能


MERGE_TOOLS_REGISTRY: Dict[str, MergeToolInfo] = {}


def regist_merge_tool(func: Callable[..., Any], tool_name: Optional[str] = None, comment: Optional[str] = None) -> None:
    """
    注册 Merge Tool 代码。
    
    参数：
        func: 工具函数
        tool_name: 工具代码名（默认为函数名）
        comment: Markdown 格式的注释，描述工具功能
    """
    name = tool_name or func.__name__
    if name in MERGE_TOOLS_REGISTRY:
        raise RuntimeError(f"Merge tool '{name}' already registered")
    MERGE_TOOLS_REGISTRY[name] = MergeToolInfo(name=name, func=func, comment=comment)
    print(f"[MERGE-TOOL] regist_merge_tool: {name} -> {func}")


# =========================
# 运行上下文 & return API
# =========================

@dataclass
class MergeRunContext:
    project_name: str
    batch_name: Optional[str]
    tool_name: str
    merge_mode: str
    tmp_dir: Path
    output_file_label: Optional[str]
    result_col: Optional[str]
    conn: sqlite3.Connection = field(default=None)
    output_file_rel_path: Optional[str] = None
    output_value: Optional[Any] = None


_CURRENT_CONTEXT: contextvars.ContextVar[MergeRunContext] = contextvars.ContextVar(
    "CURRENT_MERGE_CONTEXT", default=None  # type: ignore[arg-type]
)


def _get_ctx() -> MergeRunContext:
    ctx = _CURRENT_CONTEXT.get()
    if ctx is None:
        raise RuntimeError("merge_return_file/value called outside merge tool context")
    return ctx


def merge_return_file(filename: str) -> None:
    ctx = _get_ctx()
    src = ctx.tmp_dir / filename
    if not src.exists():
        raise FileNotFoundError(f"merge_return_file: {src} not found")

    if ctx.merge_mode == "batch_from_items":
        if not ctx.batch_name:
            raise RuntimeError("merge_return_file: batch_name missing for batch_from_items")
        dest_dir = Path(WORKSPACE_ROOT) / ctx.project_name / ctx.batch_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        rel_path = os.path.relpath(dest, Path(WORKSPACE_ROOT) / ctx.project_name)
        if dest.exists():
            dest.unlink()
        shutil.copy2(src, dest)
        create_batch_file(ctx.conn, ctx.project_name, ctx.batch_name, dest.name, rel_path)
        if ctx.output_file_label:
            add_batch_file_label(ctx.conn, ctx.project_name, ctx.batch_name, dest.name, ctx.output_file_label)
    else:
        dest_dir = Path(WORKSPACE_ROOT) / ctx.project_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        rel_path = os.path.relpath(dest, Path(WORKSPACE_ROOT) / ctx.project_name)
        if dest.exists():
            dest.unlink()
        shutil.copy2(src, dest)
        create_prj_file(ctx.conn, ctx.project_name, dest.name, rel_path)
        if ctx.output_file_label:
            add_prj_file_label(ctx.conn, ctx.project_name, dest.name, ctx.output_file_label)

    ctx.output_file_rel_path = rel_path
    print(f"[MERGE-TOOL] merge_return_file: {src} -> {rel_path} (label={ctx.output_file_label})")


def merge_return_value(value: Any) -> None:
    ctx = _get_ctx()
    if ctx.result_col is None:
        print("[MERGE-TOOL] merge_return_value called but no result_col configured; ignore.")
        return

    col = ctx.result_col
    conn = ctx.conn

    _ensure_result_table(conn, ctx.merge_mode)
    _ensure_result_row(conn, ctx.merge_mode, ctx.project_name, ctx.batch_name)
    _ensure_result_column(conn, ctx.merge_mode, col)

    if value is None:
        stored = None
    elif isinstance(value, (dict, list)):
        stored = json.dumps(value, ensure_ascii=False)
    else:
        stored = str(value)

    if ctx.merge_mode == "batch_from_items":
        sql = f'UPDATE batch_results SET "{col}" = ? WHERE project_name=? AND batch_name=?;'
        conn.execute(sql, (stored, ctx.project_name, ctx.batch_name))
    else:
        sql = f'UPDATE prj_results SET "{col}" = ? WHERE project_name=?;'
        conn.execute(sql, (stored, ctx.project_name))
    conn.commit()

    ctx.output_value = value
    print(
        f"[MERGE-TOOL] result: mode={ctx.merge_mode} "
        f"{ctx.project_name}/{ctx.batch_name or ''}.{col} = {stored!r}"
    )


def parse_composite_filename(composed: str) -> Dict[str, str]:
    """
    解析运行时生成的 composite 文件名：
        <project>@<batch>@<item>@<filename>

    返回字段：
      prj_name, batch_name, item_name, file_name, file_ext, file_basename

    如果格式不匹配会抛 ValueError。
    """
    parts = composed.split("@", 3)
    if len(parts) != 4:
        raise ValueError(f"Invalid composite filename: {composed}")

    prj_name, batch_name, item_name, file_name = parts
    p = Path(file_name)
    return {
        "prj_name": prj_name,
        "batch_name": batch_name,
        "item_name": item_name,
        "file_name": file_name,
        "file_ext": p.suffix.lstrip("."),
        "file_basename": p.stem,
    }


# =========================
# 运行入口
# =========================

def run_merge_tool(
    project_name: str,
    tool_instance_name: str,
    batch_name: Optional[str] = None,
    merge_mode: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True

    try:
        cfg = _get_project_tool_config(conn, project_name, tool_instance_name)
        if merge_mode not in {"batch_from_items", "project_from_items", "project_from_batches"}:
            return {
                "status": "error",
                "reason": "invalid_mode",
                "detail": f"merge_mode missing or invalid: {merge_mode}",
            }

        code_name = cfg.get("code_name", tool_instance_name)
        input_label_map: Dict[str, str] = cfg.get("input_label_map", {}) or {}
        output_file_label = cfg.get("output_file_label")
        result_col = cfg.get("result_col")
        
        # Unwrap input_cols (support {value: "col", comment: "..."})
        input_cols_raw = cfg.get("input_cols") or {}
        input_cols_values, _, _ = extract_wrapped_mapping(input_cols_raw)
        input_cols: Dict[str, str] = input_cols_values
        
        run_params: Dict[str, Any] = cfg.get("run_params", {}) or {}

        if code_name not in MERGE_TOOLS_REGISTRY:
            # Try to load on demand
            from tool_registry import _ensure_tool_loaded
            _ensure_tool_loaded(tool_instance_name)
            
            if code_name not in MERGE_TOOLS_REGISTRY:
                raise RuntimeError(
                    f"Merge tool code '{code_name}' not registered (instance '{tool_instance_name}')"
                )

        param_type_map = get_run_param_type_map(code_name, conn=conn)

        # 使用请求检查器进行预检查
        missing_labels, missing_results = check_merge_tool_request(
            conn=conn,
            project_name=project_name,
            batch_name=batch_name,
            merge_mode=merge_mode,
            input_label_map=input_label_map,
            input_cols=input_cols,
            run_params=run_params,
            code_name=code_name,
            param_type_map=param_type_map,
        )

        if missing_labels or missing_results:
            return {
                "status": "error",
                "reason": "missing_inputs",
                "missing_labels": sorted(set(missing_labels)),
                "missing_results": sorted(set(missing_results)),
            }

        func = MERGE_TOOLS_REGISTRY[code_name].func

        # 预检查通过后，创建临时目录并收集文件
        tmp_dir = Path(tempfile.mkdtemp(prefix="merge_tool_"))

        # 收集输入文件/结果列表
        file_args, _ = _collect_files(
            conn, project_name, batch_name, merge_mode, input_label_map, tmp_dir
        )
        result_args, _ = _collect_results(
            conn, project_name, batch_name, merge_mode, input_cols
        )

        # 解析运行参数（支持 from_result 系列）
        scope_for_params = "batch" if merge_mode == "batch_from_items" else "project"
        resolved_run_params, missing_run_params, results_ctx = _resolve_run_params(
            conn=conn,
            project_name=project_name,
            batch_name=batch_name if scope_for_params == "batch" else None,
            item_name=None,
            run_params=run_params,
            scope=scope_for_params,
            param_type_map=param_type_map,
        )
        if missing_run_params:
            return {
                "status": "error",
                "reason": "missing_run_params",
                "missing_results": sorted(set(missing_run_params)),
            }

        call_kwargs: Dict[str, Any] = {}
        call_kwargs.update(file_args)
        call_kwargs.update(result_args)
        call_kwargs.update(resolved_run_params)

        ctx = MergeRunContext(
            project_name=project_name,
            batch_name=batch_name,
            tool_name=tool_instance_name,
            merge_mode=merge_mode,
            tmp_dir=tmp_dir,
            output_file_label=output_file_label,
            result_col=result_col,
            conn=conn,
        )

        token = _CURRENT_CONTEXT.set(ctx)
        cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            try:
                func(tool_instance_name, **call_kwargs)
            except Exception as e:
                import traceback
                tb_str = traceback.format_exc()
                print(f"[MERGE-TOOL] Error during execution: {tb_str}")
                return {
                    "status": "error",
                    "reason": "tool_exception",
                    "detail": f"{str(e)}\n{tb_str}",
                    "exception_type": e.__class__.__name__
                }
        finally:
            _CURRENT_CONTEXT.reset(token)
            os.chdir(cwd)
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return {
            "status": "ok",
            "output_file": ctx.output_file_rel_path,
            "output_value": ctx.output_value,
        }

    finally:
        if owns_conn:
            conn.close()


# =========================
# 输入收集
# =========================

def _collect_files(
    conn: sqlite3.Connection,
    project: str,
    batch: Optional[str],
    merge_mode: str,
    input_label_map: Dict[str, str],
    tmp_dir: Path,
) -> Tuple[Dict[str, List[str]], List[str]]:
    """
    返回：({param: [filenames]}, missing_labels)
    """
    missing = []
    result: Dict[str, List[str]] = {k: [] for k in input_label_map}

    if not input_label_map:
        return result, missing

    cur = conn.cursor()

    if merge_mode == "batch_from_items":
        if not batch:
            raise RuntimeError("batch_from_items requires batch_name")
        # 找该 batch 下所有 item
        cur.execute(
            "SELECT name FROM items WHERE project_name=? AND batch_name=? ORDER BY name;",
            (project, batch),
        )
        items = [row["name"] for row in cur.fetchall()]
        for item_name in items:
            for arg, label in input_label_map.items():
                cur.execute(
                    """
                    SELECT f.rel_path, f.filename
                    FROM files f
                    JOIN file_labels l ON (
                        l.project_name=f.project_name AND l.batch_name=f.batch_name
                        AND l.item_name=f.item_name AND l.filename=f.filename
                    )
                    WHERE f.project_name=? AND f.batch_name=? AND f.item_name=? AND l.label=?;
                    """,
                    (project, batch, item_name, label),
                )
                row = cur.fetchone()
                if not row:
                    missing.append(label)
                    continue
                workspace_path = Path(WORKSPACE_ROOT) / project / row["rel_path"]
                tmp_name = f"{project}@{batch}@{item_name}@{row['filename']}"
                final = tmp_dir / tmp_name
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace_path, final)
                result[arg].append(final.name)
    elif merge_mode == "project_from_items":
        cur.execute(
            "SELECT batch_name, name FROM items WHERE project_name=? ORDER BY batch_name, name;",
            (project,),
        )
        rows = cur.fetchall()
        for batch_name, item_name in rows:
            for arg, label in input_label_map.items():
                cur.execute(
                    """
                    SELECT f.rel_path, f.filename
                    FROM files f
                    JOIN file_labels l ON (
                        l.project_name=f.project_name AND l.batch_name=f.batch_name
                        AND l.item_name=f.item_name AND l.filename=f.filename
                    )
                    WHERE f.project_name=? AND f.batch_name=? AND f.item_name=? AND l.label=?;
                    """,
                    (project, batch_name, item_name, label),
                )
                row = cur.fetchone()
                if not row:
                    missing.append(label)
                    continue
                workspace_path = Path(WORKSPACE_ROOT) / project / row["rel_path"]
                tmp_name = f"{project}@{batch_name}@{item_name}@{row['filename']}"
                final = tmp_dir / tmp_name
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace_path, final)
                result[arg].append(final.name)
    else:  # project_from_batches
        cur.execute(
            "SELECT name FROM batches WHERE project_name=? ORDER BY name;",
            (project,),
        )
        batches = [row["name"] for row in cur.fetchall()]
        for b in batches:
            for arg, label in input_label_map.items():
                cur.execute(
                    """
                    SELECT bf.rel_path, bf.filename
                    FROM batch_files bf
                    JOIN batch_file_labels bl ON (
                        bl.project_name=bf.project_name
                        AND bl.batch_name=bf.batch_name
                        AND bl.filename=bf.filename
                    )
                    WHERE bf.project_name=? AND bf.batch_name=? AND bl.label=?;
                    """,
                    (project, b, label),
                )
                row = cur.fetchone()
                if not row:
                    missing.append(label)
                    continue
                workspace_path = Path(WORKSPACE_ROOT) / project / row["rel_path"]
                tmp_name = f"{project}@{b}@{row['filename']}"
                final = tmp_dir / tmp_name
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace_path, final)
                result[arg].append(final.name)

    return result, missing


def _collect_results(
    conn: sqlite3.Connection,
    project: str,
    batch: Optional[str],
    merge_mode: str,
    input_cols: Dict[str, str],
) -> Tuple[Dict[str, List[Any]], List[str]]:
    missing: List[str] = []
    result: Dict[str, List[Any]] = {}
    cur = conn.cursor()

    if merge_mode in {"batch_from_items", "project_from_items"}:
        if merge_mode == "project_from_items":
            cur.execute(
                "SELECT batch_name, name FROM items WHERE project_name=? ORDER BY batch_name, name;",
                (project,),
            )
            rows = cur.fetchall()
        else:
            cur.execute(
                "SELECT name FROM items WHERE project_name=? AND batch_name=? ORDER BY name;",
                (project, batch),
            )
            rows = [{"batch_name": batch, "name": row["name"]} for row in cur.fetchall()]
        for arg, col in input_cols.items():
            if not col or not str(col).strip():
                result[arg] = None
                continue

            if not _result_column_exists(cur, "item_results", col):
                missing.append(col)
                continue
            values: List[Any] = []
            for row in rows:
                bname, iname = row["batch_name"], row["name"]
                cur.execute(
                    f'SELECT "{col}" AS v FROM item_results '
                    "WHERE project_name=? AND batch_name=? AND item_name=?;",
                    (project, bname, iname),
                )
                r = cur.fetchone()
                if not r or r["v"] is None:
                    missing.append(col)
                    values = []
                    break
                values.append(_maybe_json(r["v"]))
            result[arg] = values
    else:  # project_from_batches
        cur.execute(
            "SELECT name FROM batches WHERE project_name=? ORDER BY name;",
            (project,),
        )
        batches = [row["name"] for row in cur.fetchall()]
        for arg, col in input_cols.items():
            if not col or not str(col).strip():
                result[arg] = None
                continue

            if not _result_column_exists(cur, "batch_results", col):
                missing.append(col)
                continue
            values: List[Any] = []
            for b in batches:
                cur.execute(
                    f'SELECT "{col}" AS v FROM batch_results '
                    "WHERE project_name=? AND batch_name=?;",
                    (project, b),
                )
                r = cur.fetchone()
                if not r or r["v"] is None:
                    missing.append(col)
                    values = []
                    break
                values.append(_maybe_json(r["v"]))
            result[arg] = values

    return result, missing


def _maybe_json(raw: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


# =========================
# 结果表工具
# =========================

def _ensure_result_table(conn: sqlite3.Connection, merge_mode: str) -> None:
    cur = conn.cursor()
    if merge_mode == "batch_from_items":
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_results (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,
                PRIMARY KEY (project_name, batch_name),
                FOREIGN KEY (project_name, batch_name)
                    REFERENCES batches(project_name, name)
                    ON DELETE CASCADE
            );
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prj_results (
                project_name TEXT PRIMARY KEY,
                FOREIGN KEY (project_name)
                    REFERENCES projects(name)
                    ON DELETE CASCADE
            );
            """
        )
    conn.commit()


def _ensure_result_row(
    conn: sqlite3.Connection, merge_mode: str, project: str, batch: Optional[str]
) -> None:
    if merge_mode == "batch_from_items":
        conn.execute(
            "INSERT OR IGNORE INTO batch_results (project_name, batch_name) VALUES (?, ?);",
            (project, batch),
        )
    else:
        conn.execute(
            "INSERT OR IGNORE INTO prj_results (project_name) VALUES (?);",
            (project,),
        )
    conn.commit()


def _ensure_result_column(
    conn: sqlite3.Connection, merge_mode: str, col_name: str
) -> None:
    # 禁止覆盖系统保留列
    reserved = {"project_name", "batch_name", "item_name"}
    if col_name.lower() in reserved:
        raise ValueError(
            f"列名 '{col_name}' 是系统保留字段，禁止作为工具的结果列使用。"
        )

    cur = conn.cursor()
    table = "batch_results" if merge_mode == "batch_from_items" else "prj_results"
    cur.execute(f"PRAGMA table_info({table});")
    cols = {row["name"] for row in cur.fetchall()}
    if col_name not in cols:
        cur.execute(f'ALTER TABLE {table} ADD COLUMN "{col_name}" TEXT;')
        conn.commit()
        print(f"[MERGE-TOOL] {table}: added column '{col_name}'")


def _result_column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table});")
    cols = {row["name"] for row in cur.fetchall()}
    return col in cols
