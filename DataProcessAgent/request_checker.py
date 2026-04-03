"""
request_checker.py

请求检查器：在运行工具前检查所需的文件和结果列是否满足要求。

提供两个主要函数：
1. check_tool_request - 检查普通工具的运行请求
2. check_merge_tool_request - 检查合并工具的运行请求

这些函数只进行检查，不收集文件，返回缺失的资源列表。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from param_value_utils import extract_wrapped_mapping, is_null_placeholder

WORKSPACE_ROOT = os.path.abspath("workspace")


def get_run_param_type_map(
    code_name: str, conn: Optional[sqlite3.Connection] = None
) -> Dict[str, str]:
    """
    根据模板文件，返回该工具 run_params 的类型映射。
    
    注意：conn 参数保留以保持兼容性，但不再使用。
    """
    from tool_registry import get_tool_code_template
    
    template = get_tool_code_template(code_name)
    if not template:
        return {}
    
    params = template.get("params") or []
    mapping: Dict[str, str] = {}
    if isinstance(params, list):
        for p in params:
            if not isinstance(p, dict):
                continue
            name = p.get("name")
            ptype = p.get("type")
            if isinstance(name, str) and isinstance(ptype, str):
                mapping[name] = ptype
    return mapping


def _maybe_json(raw: Any) -> Any:
    """尝试将字符串解析为 JSON，失败则返回原值。"""
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _ensure_tool_runtime_schema(conn: sqlite3.Connection) -> None:
    """确保结果表存在。"""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prj_config (
            project_name TEXT PRIMARY KEY
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS item_results (
            project_name TEXT NOT NULL,
            batch_name   TEXT NOT NULL,
            item_name    TEXT NOT NULL,
            PRIMARY KEY (project_name, batch_name, item_name),
            FOREIGN KEY (project_name, batch_name, item_name)
                REFERENCES items(project_name, batch_name, name)
            ON DELETE CASCADE
        );
        """
    )
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


def _result_column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    """检查结果表中是否存在指定列。"""
    cur.execute(f"PRAGMA table_info({table});")
    cols = {row["name"] for row in cur.fetchall()}
    return col in cols


def check_input_files(
    conn: sqlite3.Connection,
    scope: str,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    input_label_map: Dict[str, Any],
    virtual_labels: Optional[Set[str]] = None,
) -> List[str]:
    """
    检查输入文件是否存在（不复制文件）。

    参数：
        conn: 数据库连接
        scope: "item" | "batch" | "project"
        project: 项目名
        batch: 批次名（scope=item/batch 时需要）
        item: 条目名（scope=item 时需要）
        input_label_map: 参数名到标签的映射（支持包装结构）

    返回：
        缺失的标签列表
    """
    if not input_label_map:
        return []

    cur = conn.cursor()
    missing: List[str] = []
    project_root = Path(WORKSPACE_ROOT) / project
    virtual_labels = virtual_labels or set()

    for arg, raw_label in input_label_map.items():
        # 处理包装结构: {"value": "LABEL", "comment": "..."}
        if isinstance(raw_label, dict) and "value" in raw_label:
            label_str = raw_label["value"]
        else:
            label_str = raw_label

        print(f"[DEBUG] check_input_files: arg={arg}, label={label_str}, scope={scope}, project={project}, batch={batch}, item={item}")

        if not label_str or not isinstance(label_str, str):
            continue
            
        # 支持逗号分隔的多个标签
        labels = [l.strip() for l in label_str.split(",") if l.strip()]
        resolved_files: Set[Tuple[str, str]] = set()
        
        for label in labels:
            if label in virtual_labels:
                continue

            if scope == "item":
                if not batch or not item:
                    missing.append(label)
                    continue
                cur.execute(
                    """
                    SELECT f.filename, f.rel_path
                    FROM files f
                    JOIN file_labels fl ON (
                        fl.project_name=f.project_name AND fl.batch_name=f.batch_name
                        AND fl.item_name=f.item_name AND fl.filename=f.filename
                    )
                    WHERE f.project_name=? AND f.batch_name=? AND f.item_name=? AND fl.label=?;
                    """,
                    (project, batch, item, label),
                )
            elif scope == "batch":
                if not batch:
                    missing.append(label)
                    continue
                cur.execute(
                    """
                    SELECT bf.filename, bf.rel_path
                    FROM batch_files bf
                    JOIN batch_file_labels bl ON (
                        bl.project_name=bf.project_name AND bl.batch_name=bf.batch_name
                        AND bl.filename=bf.filename
                    )
                    WHERE bf.project_name=? AND bf.batch_name=? AND bl.label=?;
                    """,
                    (project, batch, label),
                )
            else:  # project
                cur.execute(
                    """
                    SELECT pf.filename, pf.rel_path
                    FROM prj_files pf
                    JOIN prj_file_labels pl ON (
                        pl.project_name=pf.project_name AND pl.filename=pf.filename
                    )
                    WHERE pf.project_name=? AND pl.label=?;
                    """,
                    (project, label),
                )
            
            rows = cur.fetchall()
            if not rows:
                missing.append(label)
                continue
            if len(rows) > 1:
                missing.append(f"{label}(duplicate)")
                continue
            
            row = rows[0]
            file_id = (row["rel_path"], row["filename"])
            if file_id in resolved_files:
                # 极端情况：多个标签指向同一个物理文件
                missing.append(f"{label}(overlap)")
                continue
            resolved_files.add(file_id)

            src = project_root / row["rel_path"]
            if not src.exists():
                missing.append(label)

    return missing


def check_run_params(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: Optional[str],
    item_name: Optional[str],
    run_params: Dict[str, Any],
    scope: str,
    *,
    code_name: Optional[str] = None,
    param_type_map: Optional[Dict[str, str]] = None,
    virtual_result_cols: Optional[Set[str]] = None,
) -> List[str]:
    """
    检查 run_params 中引用的结果列是否存在且有效。

    参数：
        conn: 数据库连接
        project_name: 项目名
        batch_name: 批次名
        item_name: 条目名
        run_params: 运行参数字典（支持包装结构）
        scope: "item" | "batch" | "project"

    返回：
        缺失的结果列名列表
    """
    missing_cols: List[str] = []
    virtual_result_cols = virtual_result_cols or set()

    if not run_params:
        return missing_cols

    # 将模板中的类型映射加载出来，便于识别 from_result 等特殊参数
    type_map: Dict[str, str] = param_type_map or {}
    if not type_map and code_name:
        type_map = get_run_param_type_map(code_name, conn=conn)

    _ensure_tool_runtime_schema(conn)
    cur = conn.cursor()

    for key, raw_value in run_params.items():
        # 获取实际值（如果是包装格式）
        if isinstance(raw_value, dict) and "value" in raw_value:
            value = raw_value["value"]
        else:
            value = raw_value

        print(f"[DEBUG] check_run_params: key={key}, value={value}, scope={scope}")

        expected_type = type_map.get(key)
        
        # 兼容处理：如果期望是 from_result 且值是字符串，自动视为引用
        if expected_type in {"from_result", "optional_from_result"} and not isinstance(value, dict):
            value = {"from_result": value}

        if isinstance(value, dict) and "from_result" in value:
            col = value["from_result"]
            if expected_type == "optional_from_result" and is_null_placeholder(col):
                continue
            if col in virtual_result_cols:
                continue
            if scope == "item":
                if not batch_name or not item_name:
                    missing_cols.append(col)
                    continue
                table = "item_results"
                if not _result_column_exists(cur, table, col):
                    missing_cols.append(col)
                    continue
                cur.execute(
                    f'SELECT "{col}" AS v FROM item_results '
                    "WHERE project_name = ? AND batch_name = ? AND item_name = ?;",
                    (project_name, batch_name, item_name),
                )
            elif scope == "batch":
                if not batch_name:
                    missing_cols.append(col)
                    continue
                table = "batch_results"
                if not _result_column_exists(cur, table, col):
                    missing_cols.append(col)
                    continue
                cur.execute(
                    f'SELECT "{col}" AS v FROM batch_results WHERE project_name=? AND batch_name=?;',
                    (project_name, batch_name),
                )
            else:
                table = "prj_results"
                if not _result_column_exists(cur, table, col):
                    missing_cols.append(col)
                    continue
                cur.execute(
                    f'SELECT "{col}" AS v FROM prj_results WHERE project_name=?;',
                    (project_name,),
                )

            row = cur.fetchone()
            if row is None or row["v"] is None:
                if expected_type != "optional_from_result":
                    missing_cols.append(col)
        elif isinstance(value, dict) and "from_item_result" in value:
            if not batch_name or not item_name:
                missing_cols.append(value["from_item_result"])
                continue
            col = value["from_item_result"]
            if col in virtual_result_cols:
                continue
            if not _result_column_exists(cur, "item_results", col):
                missing_cols.append(col)
                continue
            cur.execute(
                f'SELECT "{col}" AS v FROM item_results '
                "WHERE project_name = ? AND batch_name = ? AND item_name = ?;",
                (project_name, batch_name, item_name),
            )
            row = cur.fetchone()
            if row is None or row["v"] is None:
                missing_cols.append(col)
        elif isinstance(value, dict) and "from_batch_result" in value:
            col = value["from_batch_result"]
            if col in virtual_result_cols:
                continue
            if not batch_name:
                missing_cols.append(col)
                continue
            if not _result_column_exists(cur, "batch_results", col):
                missing_cols.append(col)
                continue
            cur.execute(
                f'SELECT "{col}" AS v FROM batch_results WHERE project_name=? AND batch_name=?;',
                (project_name, batch_name),
            )
            row = cur.fetchone()
            if row is None or row["v"] is None:
                missing_cols.append(col)
        elif isinstance(value, dict) and "from_prj_result" in value:
            col = value["from_prj_result"]
            if col in virtual_result_cols:
                continue
            if not _result_column_exists(cur, "prj_results", col):
                missing_cols.append(col)
                continue
            cur.execute(
                f'SELECT "{col}" AS v FROM prj_results WHERE project_name=?;',
                (project_name,),
            )
            row = cur.fetchone()
            if row is None or row["v"] is None:
                missing_cols.append(col)

    return missing_cols


def check_tool_request(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: Optional[str],
    item_name: Optional[str],
    input_label_map: Dict[str, str],
    run_params: Dict[str, Any],
    scope: str,
    *,
    code_name: Optional[str] = None,
    param_type_map: Optional[Dict[str, str]] = None,
    virtual_labels: Optional[Set[str]] = None,
    virtual_result_cols: Optional[Set[str]] = None,
    result_col: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """
    检查普通工具的运行请求是否满足要求。
    """
    # 增加：检查结果列名是否合法
    if result_col and result_col.lower() in {"project_name", "batch_name", "item_name"}:
        return (["RESERVED_COLUMN_ERROR"], [])

    missing_labels = check_input_files(
        conn=conn,
        scope=scope,
        project=project_name,
        batch=batch_name,
        item=item_name,
        input_label_map=input_label_map,
        virtual_labels=virtual_labels,
    )

    missing_result_cols = check_run_params(
        conn=conn,
        project_name=project_name,
        batch_name=batch_name,
        item_name=item_name,
        run_params=run_params,
        scope=scope,
        code_name=code_name,
        param_type_map=param_type_map,
        virtual_result_cols=virtual_result_cols,
    )

    return missing_labels, missing_result_cols


def check_merge_input_files(
    conn: sqlite3.Connection,
    project: str,
    batch: Optional[str],
    merge_mode: str,
    input_label_map: Dict[str, str],
) -> List[str]:
    """
    检查合并工具的输入文件是否存在。

    参数：
        conn: 数据库连接
        project: 项目名
        batch: 批次名（merge_mode=batch_from_items 时需要）
        merge_mode: "batch_from_items" | "project_from_items" | "project_from_batches"
        input_label_map: 参数名到标签的映射

    返回：
        缺失的标签列表
    """
    input_label_map_values, _, _ = extract_wrapped_mapping(input_label_map or {})
    input_label_map = input_label_map_values

    if not input_label_map:
        return []

    missing: List[str] = []
    cur = conn.cursor()
    project_root = Path(WORKSPACE_ROOT) / project

    if merge_mode == "batch_from_items":
        if not batch:
            return list(input_label_map.values())
        # 找该 batch 下所有 item
        cur.execute(
            "SELECT name FROM items WHERE project_name=? AND batch_name=? ORDER BY name;",
            (project, batch),
        )
        items = [row["name"] for row in cur.fetchall()]
        if not items:
            return list(input_label_map.values())
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
                    break  # 只要有一个 item 缺失就标记
                workspace_path = project_root / row["rel_path"]
                if not workspace_path.exists():
                    missing.append(label)
                    break
    elif merge_mode == "project_from_items":
        cur.execute(
            "SELECT batch_name, name FROM items WHERE project_name=? ORDER BY batch_name, name;",
            (project,),
        )
        rows = cur.fetchall()
        if not rows:
            return list(input_label_map.values())
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
                    break
                workspace_path = project_root / row["rel_path"]
                if not workspace_path.exists():
                    missing.append(label)
                    break
    else:  # project_from_batches
        cur.execute(
            "SELECT name FROM batches WHERE project_name=? ORDER BY name;",
            (project,),
        )
        batches = [row["name"] for row in cur.fetchall()]
        if not batches:
            return list(input_label_map.values())
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
                    break
                workspace_path = project_root / row["rel_path"]
                if not workspace_path.exists():
                    missing.append(label)
                    break

    return missing


def check_merge_result_cols(
    conn: sqlite3.Connection,
    project: str,
    batch: Optional[str],
    merge_mode: str,
    result_cols: Dict[str, str],
) -> List[str]:
    """
    检查合并工具所需的结果列是否存在。

    参数：
        conn: 数据库连接
        project: 项目名
        batch: 批次名（merge_mode=batch_from_items 时需要）
        merge_mode: "batch_from_items" | "project_from_items" | "project_from_batches"
        result_cols: 参数名到结果列名的映射（input_cols）

    返回：
        缺失的结果列列表
    """
    if not result_cols:
        return []

    missing: List[str] = []
    cur = conn.cursor()

    if merge_mode in {"batch_from_items", "project_from_items"}:
        if merge_mode == "project_from_items":
            cur.execute(
                "SELECT batch_name, name FROM items WHERE project_name=? ORDER BY batch_name, name;",
                (project,),
            )
            rows = cur.fetchall()
        else:
            if not batch:
                return list(result_cols.values())
            cur.execute(
                "SELECT name FROM items WHERE project_name=? AND batch_name=? ORDER BY name;",
                (project, batch),
            )
            rows = [{"batch_name": batch, "name": row["name"]} for row in cur.fetchall()]
        if not rows:
            return list(result_cols.values())
        for arg, col in result_cols.items():
            if not col or not str(col).strip():
                continue  # 忽略空列名
            
            if not _result_column_exists(cur, "item_results", col):
                missing.append(col)
                continue
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
                    break
    else:  # project_from_batches
        cur.execute(
            "SELECT name FROM batches WHERE project_name=? ORDER BY name;",
            (project,),
        )
        batches = [row["name"] for row in cur.fetchall()]
        if not batches:
            return list(result_cols.values())
        for arg, col in result_cols.items():
            if not col or not str(col).strip():
                continue # Skip empty column names (optional inputs)

            if not _result_column_exists(cur, "batch_results", col):
                missing.append(col)
                continue
            for b in batches:
                cur.execute(
                    f'SELECT "{col}" AS v FROM batch_results '
                    "WHERE project_name=? AND batch_name=?;",
                    (project, b),
                )
                r = cur.fetchone()
                if not r or r["v"] is None:
                    missing.append(col)
                    break

    return missing


def check_merge_tool_request(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: Optional[str],
    merge_mode: str,
    input_label_map: Dict[str, str],
    input_cols: Dict[str, str],
    run_params: Optional[Dict[str, Any]] = None,
    *,
    code_name: Optional[str] = None,
    param_type_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[str], List[str]]:
    """
    检查合并工具的运行请求是否满足要求。

    参数：
        conn: 数据库连接
        project_name: 项目名
        batch_name: 批次名（merge_mode=batch_from_items 时需要）
        merge_mode: "batch_from_items" | "project_from_items" | "project_from_batches"
        input_label_map: 输入参数到标签的映射
        input_cols: 参数名到结果列名的映射（从子级 results 聚合的输入向量）
        run_params: 运行参数（可引用结果列）

    返回：
        (missing_labels, missing_result_cols) 元组
        - missing_labels: 缺失的文件标签列表
        - missing_result_cols: 缺失的结果列列表
    """
    missing_labels = check_merge_input_files(
        conn=conn,
        project=project_name,
        batch=batch_name,
        merge_mode=merge_mode,
        input_label_map=input_label_map,
    )

    input_cols_values, _, _ = extract_wrapped_mapping(input_cols or {})
    input_cols = input_cols_values

    missing_result_cols = check_merge_result_cols(
        conn=conn,
        project=project_name,
        batch=batch_name,
        merge_mode=merge_mode,
        result_cols=input_cols,
    )

    run_params = run_params or {}
    run_params_values, _, _ = extract_wrapped_mapping(run_params)
    run_params = run_params_values
    if run_params:
        scope_for_params = "batch" if merge_mode == "batch_from_items" else "project"
        missing_result_cols.extend(
            check_run_params(
                conn=conn,
                project_name=project_name,
                batch_name=batch_name if scope_for_params == "batch" else None,
                item_name=None,
                run_params=run_params,
                scope=scope_for_params,
                code_name=code_name,
                param_type_map=param_type_map,
            )
        )

    return missing_labels, missing_result_cols
