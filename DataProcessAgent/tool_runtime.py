"""
tool_runtime.py

负责：
- 工具注册：regist_tool(...)
- 工具运行时上下文：return_file(...), return_value(...)
- 运行 item 级工具：run_item_tool(project, batch, item, tool_instance_name)

约定：
- 工具代码放在 tools/ 目录下，示例：

  # tools/lsv_tool.py
  from tool_runtime import regist_tool, return_file, return_value

  def lsv_process(tool_name, lsv_file, smooth_window, baseline):
      # 当前工作目录已经是 /tmp/tmp_xxx/
      with open(lsv_file) as f:
          ...
      with open("LSV.img", "w") as f:
          ...
      return_file("LSV.img")
      return_value(LSV_value)

  regist_tool(lsv_process)

- “工具代码函数”只注册一次，例如 regist_tool(lsv_process)
- “工具实例”由配置决定：prj_config.tool_<实例名> 一列 + JSON 配置：

  {
    "code_name": "lsv_process",                    # 使用哪段代码函数
    "input_label_map": { "lsv_file": "LSV" },      # 函数参数 -> label
    "run_params": {
        "smooth_window": 5,                        # 直接常量
        "baseline": "auto",
        "prev_param": { "from_item_result": "V0"}  # 从 item_results 某列读
    },
    "output_file_label": "LSV-PROCESSED",          # 输出文件的 LABEL
    "result_col": "LSV_value"                      # 写入 item_results 的列名
  }

- 数值结果写入 item_results 表（原 process_results 概念升级）：
  - 行键： (project_name, batch_name, item_name)
  - 动态 ALTER TABLE ADD COLUMN "<result_col>" TEXT;
  - 一个工具多次运行会覆盖该列旧值。

- 如果：
  - 输入文件不全（某些 label 找不到文件）；
  - run_params 里请求的 item_results 列不存在 / 行不存在 / 该列值为 NULL；
  => 工具不执行，返回错误信息：
     {
       "status": "error",
       "reason": "missing_inputs" / "missing_run_params",
       "missing_labels": [...],
       "missing_item_results": [...]
     }
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
from typing import Any, Callable, Dict, Optional, List, Set, Tuple

from db import (
    get_connection,
    create_file,
    create_batch_file,
    create_prj_file,
    add_file_label,
    add_batch_file_label,
    add_prj_file_label,
    retry_on_lock,
)
from param_value_utils import (
    extract_wrapped_mapping,
    extract_wrapped_value,
    is_null_placeholder,
    render_runtime_text,
)
from request_checker import check_tool_request, get_run_param_type_map
from run_history import (
    finish_run_history,
    log_file_inputs,
    log_file_outputs,
    log_result_inputs,
    log_result_outputs,
    log_run_params,
    start_run_history,
)

# 与 upload.py 保持一致
WORKSPACE_ROOT = os.path.abspath("workspace")


# =========================
# 工具注册表
# =========================

@dataclass
class ToolInfo:
    name: str
    func: Callable[..., Any]
    comment: Optional[str] = None  # Markdown 格式的注释，描述工具功能


TOOLS_REGISTRY: Dict[str, ToolInfo] = {}


def regist_tool(func: Callable[..., Any], tool_name: Optional[str] = None, comment: Optional[str] = None) -> None:
    """
    由工具模块调用，用于把一个函数注册为"工具代码入口"。

    示例：
        from tool_runtime import regist_tool

        def lsv_process(tool_name, lsv_file, smooth_window, baseline):
            ...
        regist_tool(lsv_process, comment="# LSV处理工具\\n\\n用于处理LSV文件...")

    - tool_name 默认为 func.__name__
    - comment: Markdown 格式的注释，描述工具功能
    - "工具实例名"在配置中定义，通过 code_name 映射到这里注册的代码名
    """
    name = tool_name or func.__name__
    if name in TOOLS_REGISTRY:
        raise RuntimeError(f"Tool '{name}' already registered")

    TOOLS_REGISTRY[name] = ToolInfo(name=name, func=func, comment=comment)
    print(f"[TOOL] regist_tool: {name} -> {func}")


# =========================
# 运行时上下文（给 return_file / return_value 用）
# =========================

@dataclass
class RunContext:
    scope: str  # "item" | "batch" | "project"
    project_name: str
    batch_name: Optional[str]
    item_name: Optional[str]
    # tool_name 这里存的是“工具实例名”，方便日志和日志返回
    tool_name: str
    tmp_dir: Path
    target_dir: Path
    output_file_label: Optional[str]
    result_col: Optional[str]
    # 运行结果快照（方便 run_item_tool 返回）
    output_file_rel_path: Optional[str] = None
    output_value: Optional[Any] = None
    # DB 连接（复用调用方的连接）
    conn: sqlite3.Connection = field(default=None)
    history_id: Optional[int] = None
    file_outputs: List[Dict[str, Optional[str]]] = field(default_factory=list)
    result_outputs: List[Dict[str, Any]] = field(default_factory=list)
    # 动态重命名和渲染所需的上下文
    output_pattern: Optional[str] = None
    results_ctx: Dict[str, Any] = field(default_factory=dict)

@dataclass
class IterationConfig:
    input_label_map: Dict[str, Any]
    run_params: Dict[str, Any]
    output_file_label: Optional[str]
    result_col: Optional[str]
    output_pattern: Optional[str] = None


_CURRENT_CONTEXT: contextvars.ContextVar[RunContext] = contextvars.ContextVar(
    "CURRENT_TOOL_CONTEXT", default=None  # type: ignore[arg-type]
)


def _get_current_context() -> RunContext:
    ctx = _CURRENT_CONTEXT.get()
    if ctx is None:
        raise RuntimeError("return_file / return_value called outside tool context")
    return ctx


# =========================
# 运行时上下文获取：项目/批次/条目/作用域
# =========================

def get_project() -> str:
    """当前运行的 project 名，字符串。"""
    return _get_current_context().project_name


def get_batch() -> str:
    """当前运行的 batch 名（无 batch 时返回空字符串）。"""
    return _get_current_context().batch_name or ""


def get_item() -> str:
    """当前运行的 item 名（无 item 时返回空字符串）。"""
    return _get_current_context().item_name or ""


def get_scope() -> str:
    """当前运行的 scope（item / batch / project）。"""
    return _get_current_context().scope


# =========================
# 为工具代码提供的 API：return_file / return_value
# =========================

def return_file(filename: str) -> None:
    """
    工具代码调用：
        return_file("LSV.img")

    含义：
    - 在当前 tmp_dir（运行时 cwd）下有一个文件 filename
    - 如果配置了 output_pattern，则将其重命名（如 {stem}_processed.csv）
    - 把它拷贝到对应 item 目录下
    - 写入 files 表，并打上标签
    """
    ctx = _get_current_context()
    src = ctx.tmp_dir / filename
    if not src.exists():
        raise FileNotFoundError(f"return_file: {src} not found")

    # --- 处理重命名 (output_pattern) ---
    final_name = filename
    if ctx.output_pattern:
        try:
            # 使用 render_runtime_text 渲染模板
            # 此时 results_ctx 已经包含 stem, batch, item, project 等
            final_name = render_runtime_text(ctx.output_pattern, ctx.results_ctx)
            # 确保文件名合法且不为空
            final_name = final_name.strip()
            if not final_name:
                final_name = filename
        except Exception as e:
            print(f"[TOOL] Warning: output_pattern rendering failed: {e}. Use original name.")
            final_name = filename

    dest = ctx.target_dir / final_name
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 覆盖写
    if dest.exists():
        dest.unlink()

    shutil.copy2(src, dest)

    project_root = Path(WORKSPACE_ROOT) / ctx.project_name
    rel_path = os.path.relpath(dest, project_root)

    if ctx.scope == "item":
        create_file(
            conn=ctx.conn,
            project_name=ctx.project_name,
            batch_name=ctx.batch_name,  # type: ignore[arg-type]
            item_name=ctx.item_name,    # type: ignore[arg-type]
            filename=final_name,
            rel_path=rel_path,
        )
        if ctx.output_file_label:
            add_file_label(
                conn=ctx.conn,
                project_name=ctx.project_name,
                batch_name=ctx.batch_name,  # type: ignore[arg-type]
                item_name=ctx.item_name,    # type: ignore[arg-type]
                filename=final_name,
                label=ctx.output_file_label,
            )
    elif ctx.scope == "batch":
        create_batch_file(
            conn=ctx.conn,
            project_name=ctx.project_name,
            batch_name=ctx.batch_name,  # type: ignore[arg-type]
            filename=final_name,
            rel_path=rel_path,
        )
        if ctx.output_file_label:
            add_batch_file_label(
                conn=ctx.conn,
                project_name=ctx.project_name,
                batch_name=ctx.batch_name,  # type: ignore[arg-type]
                filename=final_name,
                label=ctx.output_file_label,
            )
    else:
        create_prj_file(
            conn=ctx.conn,
            project_name=ctx.project_name,
            filename=final_name,
            rel_path=rel_path,
        )
        if ctx.output_file_label:
            add_prj_file_label(
                conn=ctx.conn,
                project_name=ctx.project_name,
                filename=final_name,
                label=ctx.output_file_label,
            )

    # 更新上下文快照
    ctx.output_file_rel_path = rel_path
    ctx.file_outputs.append({"label": ctx.output_file_label, "filename": final_name})
    print(f"[TOOL] return_file: {src} -> {rel_path} (label={ctx.output_file_label})")


def return_json(data: Dict[str, Any]) -> None:
    """
    工具代码调用：
        return_json({"a": 1, "b": 2})

    含义：
    - 如果配置的 result_col 是 "mkq"，则会在结果表中产生:
      mkq.a = 1, mkq.b = 2
    - 该函数与 return_value 互斥（虽然技术上可以共存，但建议在一个工具中二选一）。
    """
    if not isinstance(data, dict):
        raise ValueError("return_json expected a dictionary.")
    
    ctx = _get_current_context()
    if ctx.result_col is None:
        print("[TOOL] return_json called but no result_col configured; ignore.")
        return

    prefix = ctx.result_col
    conn = ctx.conn
    
    _ensure_tool_runtime_schema(conn)
    _ensure_result_row(conn, ctx.scope, ctx.project_name, ctx.batch_name, ctx.item_name)

    # 遍历字典，每一项都作为一个单独的列写入
    for key, value in data.items():
        col_name = f"{prefix}.{key}"
        _ensure_result_column(conn, ctx.scope, col_name)
        
        if value is None:
            stored = None
        elif isinstance(value, (dict, list)):
            stored = json.dumps(value, ensure_ascii=False)
        else:
            stored = str(value)

        # 优化：在循环中不进行 commit
        _update_db_result(conn, ctx.scope, ctx.project_name, ctx.batch_name, ctx.item_name, col_name, stored, commit=False)
        ctx.result_outputs.append({"result_col": col_name, "value": value})

    # 最后统一 commit
    _safe_commit(conn)
    ctx.output_value = data  # 整体作为输出值
    print(f"[TOOL] return_json: prefix={prefix}, keys={list(data.keys())}")


@retry_on_lock()
def _safe_commit(conn: sqlite3.Connection) -> None:
    """内部辅助：安全地 commit，带重试逻辑"""
    conn.commit()


@retry_on_lock()
def _update_db_result(conn: sqlite3.Connection, scope: str, project: str, batch: Optional[str], item: Optional[str], col: str, stored: Optional[str], commit: bool = True) -> None:
    """内部辅助：执行 SQL 更新结果列"""
    if scope == "item":
        sql = (
            f'UPDATE item_results SET "{col}" = ? '
            "WHERE project_name = ? AND batch_name = ? AND item_name = ?;"
        )
        params = (stored, project, batch, item)
    elif scope == "batch":
        sql = f'UPDATE batch_results SET "{col}" = ? WHERE project_name = ? AND batch_name = ?;'
        params = (stored, project, batch)
    else:
        sql = f'UPDATE prj_results SET "{col}" = ? WHERE project_name = ?;'
        params = (stored, project)

    conn.execute(sql, params)
    if commit:
        conn.commit()


def return_value(value: Any) -> None:
    """
    工具代码调用：
        return_value(LSV_value)

    含义：
    - 将数值结果写入 item_results 表中：
      行键： (project_name, batch_name, item_name)
      列名： ctx.result_col
    - 值可以是数字 / 字符串 / JSON-serializable 对象
      存储格式统一为 TEXT（必要时 json.dumps）
    """
    ctx = _get_current_context()

    if ctx.result_col is None:
        print("[TOOL] return_value called but no result_col configured; ignore.")
        return

    col = ctx.result_col
    conn = ctx.conn

    print(
        f"[TOOL] return_value called: "
        f"project={ctx.project_name}, batch={ctx.batch_name}, item={ctx.item_name}, "
        f"col={col}, value={value!r}"
    )

    # 确保结果表存在/列存在
    _ensure_tool_runtime_schema(conn)
    _ensure_result_row(conn, ctx.scope, ctx.project_name, ctx.batch_name, ctx.item_name)
    _ensure_result_column(conn, ctx.scope, col)

    if value is None:
        stored = None
    elif isinstance(value, (dict, list)):
        stored = json.dumps(value, ensure_ascii=False)
    else:
        stored = str(value)

    _update_db_result(conn, ctx.scope, ctx.project_name, ctx.batch_name, ctx.item_name, col, stored)

    ctx.output_value = value
    ctx.result_outputs.append({"result_col": col, "value": value})
    print(f"[TOOL] result: scope={ctx.scope} {ctx.project_name}/{ctx.batch_name or ''}.{col} = {stored!r}")


# =========================
# DB schema: prj_config & item_results
# =========================

@retry_on_lock()
def _ensure_tool_runtime_schema(conn: sqlite3.Connection) -> None:
    """
    确保 prj_config 和 item_results 这两张表存在。
    """
    cur = conn.cursor()

    # prj_config: project_name + 动态列 tool_<tool_instance_name>
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prj_config (
            project_name TEXT PRIMARY KEY
            -- 之后通过 ALTER TABLE ADD COLUMN tool_<tool_instance_name> TEXT 动态扩展
        );
        """
    )

    # item_results: 行键 = (project, batch, item) + 动态结果列
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

    # batch_results
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

    # prj_results
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


@retry_on_lock()
def _ensure_result_row(
    conn: sqlite3.Connection, scope: str, project: str, batch: Optional[str], item: Optional[str]
) -> None:
    if scope == "item":
        conn.execute(
            """
            INSERT OR IGNORE INTO item_results (project_name, batch_name, item_name)
            VALUES (?, ?, ?);
            """,
            (project, batch, item),
        )
    elif scope == "batch":
        conn.execute(
            """
            INSERT OR IGNORE INTO batch_results (project_name, batch_name)
            VALUES (?, ?);
            """,
            (project, batch),
        )
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO prj_results (project_name)
            VALUES (?);
            """,
            (project,),
        )
    conn.commit()


@retry_on_lock()
def _ensure_result_column(conn: sqlite3.Connection, scope: str, col_name: str) -> None:
    # 禁止覆盖系统保留列
    reserved = {"project_name", "batch_name", "item_name"}
    if col_name.lower() in reserved:
        raise ValueError(
            f"列名 '{col_name}' 是系统保留字段（用于标识项目/批次/条目），"
            "禁止作为工具的结果列使用。请在工具配置中更改 'result_col' 的名称。"
        )

    table = "item_results" if scope == "item" else "batch_results" if scope == "batch" else "prj_results"
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table});")
    cols = {row["name"] for row in cur.fetchall()}

    if col_name not in cols:
        sql = f'ALTER TABLE {table} ADD COLUMN "{col_name}" TEXT;'
        cur.execute(sql)
        conn.commit()
        print(f"[DB] {table}: added column '{col_name}'")


def _get_project_tool_config(
    conn: sqlite3.Connection,
    project_name: str,
    tool_instance_name: str,   # 注意：这里的名字是“实例名”
) -> Dict[str, Any]:
    """
    获取工具实例配置（项目直接使用全局工具实例配置）。

    - 工具实例名：从全局配置文件读取
    - 配置里可以包含：
        - code_name: 使用哪段注册过的代码（函数名）
        - input_label_map / run_params / output_file_label / result_col
    
    注意：project_name 参数保留以保持兼容性，但不再使用。
    """
    from tool_registry import get_tool_config_from_file

    cfg = get_tool_config_from_file(tool_instance_name)

    if cfg is None:
        raise RuntimeError(
            f"Tool instance '{tool_instance_name}' not found in global config files"
        )

    # 填默认结构
    cfg.setdefault("input_label_map", {})
    cfg.setdefault("run_params", {})
    cfg.setdefault("output_file_label", None)
    cfg.setdefault("result_col", None)
    cfg.setdefault("output_pattern", None)

    # Unwrap fields consistently for all components
    cfg["input_label_map"], _, _ = extract_wrapped_mapping(cfg.get("input_label_map"))
    cfg["run_params"], _, _ = extract_wrapped_mapping(cfg.get("run_params"))
    cfg["output_file_label"], _, _, _ = extract_wrapped_value(cfg.get("output_file_label"))
    cfg["result_col"], _, _, _ = extract_wrapped_value(cfg.get("result_col"))
    cfg["output_pattern"], _, _, _ = extract_wrapped_value(cfg.get("output_pattern"))

    # --- 严格校验 code_name ---
    if not cfg.get("code_name"):
        raise RuntimeError(
            f"Tool instance '{tool_instance_name}' configuration is invalid: 'code_name' is mandatory."
        )

    # --- 检查 output_pattern (不修改 cfg) ---
    output_label_value, _, _, has_output_label = extract_wrapped_value(cfg.get("output_file_label"))
    output_pattern_value, _, _, has_output_pattern = extract_wrapped_value(cfg.get("output_pattern"))

    if has_output_label and output_label_value and (not has_output_pattern or not output_pattern_value):
        print(
            f"\n[TOOL-RUNTIME] ! WARNING !: Tool instance '{tool_instance_name}' has output_file_label "
            f"but MISSING output_pattern. This may cause filename conflicts or incorrect saving.\n"
        )

    print(
        f"[TOOL] Loaded config for tool instance '{tool_instance_name}' "
        f"(project '{project_name}' uses global config): {cfg}"
    )
    return cfg


def _maybe_json(raw: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _resolve_run_params(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: Optional[str],
    item_name: Optional[str],
    run_params: Dict[str, Any],
    scope: str,
    param_type_map: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], list, Dict[str, Any]]:
    """
    解析 run_params 中的值...
    返回：
    - resolved_params: 解析后的参数 dict
    - missing_cols:    无法解析的列名列表
    - results_ctx:     该 scope 下的所有结果数据 (Dict)
    """
    missing_cols = []
    resolved = {}

    # 先确保 schema，有列时再查
    _ensure_tool_runtime_schema(conn)
    cur = conn.cursor()

    # --- 获取当前 scope 的所有结果，用于字符串模板替换 ---
    # 提前注入系统默认字段，确保 render_runtime_text 能够解析它们
    results_ctx = {
        "prj": project_name,
        "project": project_name,
        "batch": batch_name or "",
        "item": item_name or "",
    }
    
    if scope == "item" and batch_name and item_name:
        cur.execute("SELECT * FROM item_results WHERE project_name=? AND batch_name=? AND item_name=?;", (project_name, batch_name, item_name))
        row = cur.fetchone()
        if row:
            results_ctx.update(dict(row))
    elif scope == "batch" and batch_name:
        cur.execute("SELECT * FROM batch_results WHERE project_name=? AND batch_name=?;", (project_name, batch_name))
        row = cur.fetchone()
        if row:
            results_ctx.update(dict(row))
    else:
        cur.execute("SELECT * FROM prj_results WHERE project_name=?;", (project_name,))
        row = cur.fetchone()
        if row:
            results_ctx.update(dict(row))
    # -----------------------------------------------

    if not run_params:
        return resolved, missing_cols, results_ctx

    type_map = param_type_map or {}

    for key, raw_value in run_params.items():
        expected_type = type_map.get(key)
        # ... (此处省略中间复杂的 from_result 解析逻辑，逻辑保持不变)
        value = raw_value
        if expected_type in {"from_result", "optional_from_result"} and not isinstance(raw_value, dict):
            value = {"from_result": raw_value}

        if isinstance(value, dict) and "from_result" in value:
            col = value["from_result"]
            if expected_type == "optional_from_result" and is_null_placeholder(col):
                resolved[key] = None
                continue
            if scope == "item":
                cur.execute("PRAGMA table_info(item_results);")
                cols = {row["name"] for row in cur.fetchall()}
                if col not in cols or not batch_name or not item_name:
                    missing_cols.append(col)
                    continue
                cur.execute(
                    f'SELECT "{col}" AS v FROM item_results '
                    "WHERE project_name = ? AND batch_name = ? AND item_name = ?;",
                    (project_name, batch_name, item_name),
                )
            elif scope == "batch":
                cur.execute("PRAGMA table_info(batch_results);")
                cols = {row["name"] for row in cur.fetchall()}
                if col not in cols or not batch_name:
                    missing_cols.append(col)
                    continue
                cur.execute(
                    f'SELECT "{col}" AS v FROM batch_results WHERE project_name=? AND batch_name=?;',
                    (project_name, batch_name),
                )
            else:
                cur.execute("PRAGMA table_info(prj_results);")
                cols = {row["name"] for row in cur.fetchall()}
                if col not in cols:
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
                else:
                    resolved[key] = None
                continue
            resolved[key] = _maybe_json(row["v"])
        elif isinstance(value, dict) and "from_item_result" in value:
            if not batch_name or not item_name:
                missing_cols.append(value["from_item_result"])
                continue
            col = value["from_item_result"]
            cur.execute("PRAGMA table_info(item_results);")
            cols = {row["name"] for row in cur.fetchall()}
            if col not in cols:
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
                continue
            resolved[key] = _maybe_json(row["v"])
        elif isinstance(value, dict) and "from_batch_result" in value:
            col = value["from_batch_result"]
            cur.execute("PRAGMA table_info(batch_results);")
            cols = {row["name"] for row in cur.fetchall()}
            if col not in cols or not batch_name:
                missing_cols.append(col)
                continue
            cur.execute(
                f'SELECT "{col}" AS v FROM batch_results WHERE project_name=? AND batch_name=?;',
                (project_name, batch_name),
            )
            row = cur.fetchone()
            if row is None or row["v"] is None:
                missing_cols.append(col)
                continue
            resolved[key] = _maybe_json(row["v"])
        elif isinstance(value, dict) and "from_prj_result" in value:
            col = value["from_prj_result"]
            cur.execute("PRAGMA table_info(prj_results);")
            cols = {row["name"] for row in cur.fetchall()}
            if col not in cols:
                missing_cols.append(col)
                continue
            cur.execute(
                f'SELECT "{col}" AS v FROM prj_results WHERE project_name=?;',
                (project_name,),
            )
            row = cur.fetchone()
            if row is None or row["v"] is None:
                missing_cols.append(col)
                continue
            resolved[key] = _maybe_json(row["v"])
        else:
            # 普通常量参数
            resolved[key] = value

    # 在最后对所有解析出的参数进行字符串模板渲染
    for key in resolved:
        resolved[key] = render_runtime_text(resolved[key], results_ctx)

    return resolved, missing_cols, results_ctx


def _collect_text_values(value: Any) -> Set[str]:
    """扁平化字符串或字符串列表为集合。"""
    collected: Set[str] = set()
    if value is None:
        return collected
    if isinstance(value, list):
        for item in value:
            collected.update(_collect_text_values(item))
        return collected
    text = str(value).strip()
    if text:
        collected.add(text)
    return collected


def _build_missing_input_details(input_map: Dict[str, Any], missing_labels: List[str]) -> List[Dict[str, str]]:
    """构造缺失输入标签的详细信息，便于前端展示。"""
    details: List[Dict[str, str]] = []
    if not missing_labels:
        return details
    missing_set = set(missing_labels)

    def matches(label: str) -> bool:
        return label in missing_set or f"{label}(duplicate)" in missing_set

    for param, label in (input_map or {}).items():
        if isinstance(label, str) and matches(label):
            details.append({"param": param, "label": label})
    return details


def _extract_result_cols(value: Any) -> List[str]:
    cols: List[str] = []
    if isinstance(value, dict):
        for key in ["from_result", "from_item_result", "from_batch_result", "from_prj_result"]:
            val = value.get(key)
            if isinstance(val, str) and not is_null_placeholder(val):
                cols.append(val)
    return cols


def _build_missing_result_details(run_params: Dict[str, Any], missing_cols: List[str]) -> List[Dict[str, str]]:
    """构造缺失结果列的详细信息。"""
    details: List[Dict[str, str]] = []
    if not missing_cols:
        return details
    missing_set = set(missing_cols)
    for param, value in (run_params or {}).items():
        for col in _extract_result_cols(value):
            if col in missing_set:
                details.append({"param": param, "column": col})
    return details


def _build_result_input_entries(
    run_params: Dict[str, Any],
    resolved_params: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """构造引用结果列的参数记录。"""
    entries: List[Dict[str, Any]] = []
    if not run_params:
        return entries

    keys = ["from_result", "from_item_result", "from_batch_result", "from_prj_result"]
    for name, raw in run_params.items():
        if not isinstance(raw, dict):
            continue
        for key in keys:
            col = raw.get(key)
            if is_null_placeholder(col):
                continue
            if isinstance(col, str):
                entries.append(
                    {
                        "param_name": name,
                        "result_col": col,
                        "value": resolved_params.get(name),
                    }
                )
                break
    return entries


def expand_single_tool_iterations(cfg: Dict[str, Any]) -> List[IterationConfig]:
    """
    将 single tool 的配置展开为逐次运行所需的参数集。
    如果配置中包含列表值，则要求所有列表长度一致，并按索引迭代。
    支持包装结构：{"value": [list], "comment": ...} -> 展开为 {"value": item, "comment": ...}
    """
    input_label_map = cfg.get("input_label_map", {}) or {}
    run_params = cfg.get("run_params", {}) or {}
    output_file_label = cfg.get("output_file_label")
    result_col = cfg.get("result_col")
    output_pattern = cfg.get("output_pattern")

    lengths: List[tuple[int, str]] = []

    def register_length(value: Any, field: str) -> None:
        if isinstance(value, list):
            if not value:
                raise ValueError(f"{field} 列表不能为空")
            lengths.append((len(value), field))

    for key, value in input_label_map.items():
        register_length(value, f"input_label_map.{key}")
    for key, value in run_params.items():
        register_length(value, f"run_params.{key}")
    register_length(output_file_label, "output_file_label")
    register_length(result_col, "result_col")
    register_length(output_pattern, "output_pattern")

    if lengths:
        expected = lengths[0][0]
        for length, field in lengths:
            if length != expected:
                raise ValueError(
                    f"列表参数长度不一致: {field}={length}, 期望 {expected}"
                )
    else:
        expected = 1

    def pick(value: Any, index: int) -> Any:
        if isinstance(value, list):
            return value[index]
        return value

    iterations: List[IterationConfig] = []
    for idx in range(expected):
        iter_input = {k: pick(v, idx) for k, v in input_label_map.items()}
        iter_run = {k: pick(v, idx) for k, v in run_params.items()}
        iter_output = pick(output_file_label, idx)
        iter_result = pick(result_col, idx)
        iter_pattern = pick(output_pattern, idx)
        iterations.append(
            IterationConfig(
                input_label_map=iter_input,
                run_params=iter_run,
                output_file_label=iter_output,
                result_col=iter_result,
                output_pattern=iter_pattern,
            )
        )

    return iterations


def _collect_scope_files(
    conn: sqlite3.Connection,
    scope: str,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    input_label_map: Dict[str, str],
    tmp_dir: Path,
) -> (Dict[str, Any], list[str]):
    """
    根据 scope 收集输入文件：
    - item: 从 files/file_labels 取单个或多个文件
    - batch: 从 batch_files/batch_file_labels 取单个或多个文件
    - project: 从 prj_files/prj_file_labels 取单个或多个文件
    文件复制到 tmp_dir。如果标签包含逗号，则返回文件名列表。
    """
    cur = conn.cursor()
    missing: list[str] = []
    results: Dict[str, Any] = {}

    project_root = Path(WORKSPACE_ROOT) / project

    for arg, label_str in input_label_map.items():
        if not label_str or not isinstance(label_str, str):
            continue
            
        labels = [l.strip() for l in label_str.split(",") if l.strip()]
        collected_files = []
        resolved_paths: Set[str] = set()
        is_multi = len(labels) > 1

        for label in labels:
            if scope == "item":
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
            src = project_root / row["rel_path"]
            
            # 唯一性检查：防止一个参数下的多个标签指向同一个文件
            path_id = str(row["rel_path"])
            if path_id in resolved_paths:
                missing.append(f"{label}(overlap)")
                continue
            resolved_paths.add(path_id)

            if not src.exists():
                missing.append(label)
                continue
            
            dest = tmp_dir / row["filename"]
            if not dest.exists():
                shutil.copy2(src, dest)
            collected_files.append(dest.name)
        
        if collected_files:
            results[arg] = collected_files if is_multi else collected_files[0]

    return results, missing


# =========================
# 工具执行核心：通用 run_tool
# =========================

def run_item_tool(
    project_name: str,
    batch_name: str,
    item_name: str,
    tool_instance_name: str,
    conn: Optional[sqlite3.Connection] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """兼容旧接口，调用通用 run_tool。"""
    return run_tool(
        project_name=project_name,
        tool_instance_name=tool_instance_name,
        batch_name=batch_name,
        item_name=item_name,
        conn=conn,
        run_id=run_id,
    )


def run_tool(
    project_name: str,
    tool_instance_name: str,
    batch_name: Optional[str] = None,
    item_name: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    根据传入参数决定 scope:
    - item_name 有值：item 级
    - 只有 batch_name：batch 级（汇总该 batch 内所有 item 的匹配文件）
    - 两者都缺失：project 级（汇总项目内所有 item 的匹配文件）
    """
    scope = "item" if item_name else "batch" if batch_name else "project"

    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True

    try:
        _ensure_tool_runtime_schema(conn)
        cfg = _get_project_tool_config(conn, project_name, tool_instance_name)
        code_name = cfg["code_name"]
        try:
            iterations = expand_single_tool_iterations(cfg)
        except ValueError as e:
            return {
                "status": "error",
                "reason": "invalid_iter_config",
                "detail": str(e),
            }

        if cfg.get("merge_mode"):
            return {
                "status": "error",
                "reason": "invalid_mode",
                "detail": "merge_mode detected, please use merge_runtime.run_merge_tool",
            }

        if code_name not in TOOLS_REGISTRY:
            # Try to load on demand
            from tool_registry import _ensure_tool_loaded
            _ensure_tool_loaded(tool_instance_name)
            
            if code_name not in TOOLS_REGISTRY:
                return {
                    "status": "error",
                    "reason": "tool_not_found",
                    "detail": f"Tool code '{code_name}' not registered",
                }

        param_type_map = get_run_param_type_map(code_name, conn=conn)
        available_labels: Set[str] = set()
        available_result_cols: Set[str] = set()

        # 使用请求检查器进行预检查
        for idx, iteration in enumerate(iterations):
            missing_labels, missing_result_cols = check_tool_request(
                conn=conn,
                project_name=project_name,
                batch_name=batch_name,
                item_name=item_name,
                input_label_map=iteration.input_label_map,
                run_params=iteration.run_params,
                scope=scope,
                code_name=code_name,
                param_type_map=param_type_map,
            )
            if available_labels:
                missing_labels = [lbl for lbl in missing_labels if lbl not in available_labels]
            if available_result_cols:
                missing_result_cols = [col for col in missing_result_cols if col not in available_result_cols]

            if missing_labels:
                missing_details = _build_missing_input_details(iteration.input_label_map, missing_labels)
                return {
                    "status": "error",
                    "reason": "missing_inputs",
                    "missing_labels": sorted(set(missing_labels)),
                    "missing_item_results": [],
                    "iteration_index": idx,
                    "missing_input_details": missing_details,
                }

            if missing_result_cols:
                missing_result_details = _build_missing_result_details(iteration.run_params, missing_result_cols)
                return {
                    "status": "error",
                    "reason": "missing_run_params",
                    "missing_labels": [],
                    "missing_item_results": sorted(set(missing_result_cols)),
                    "iteration_index": idx,
                    "missing_result_details": missing_result_details,
                }
            available_labels.update(_collect_text_values(iteration.output_file_label))
            available_result_cols.update(_collect_text_values(iteration.result_col))

        func = TOOLS_REGISTRY[code_name].func

        project_root = Path(WORKSPACE_ROOT) / project_name
        if scope == "item":
            target_dir = project_root / batch_name / item_name  # type: ignore[arg-type]
        elif scope == "batch":
            target_dir = project_root / batch_name  # type: ignore[arg-type]
        else:
            target_dir = project_root

        run_summaries: List[Dict[str, Any]] = []
        enable_history = scope == "item" and bool(run_id)

        for idx, iteration in enumerate(iterations):
            tmp_dir = Path(tempfile.mkdtemp(prefix=f"tool_{tool_instance_name}_"))
            history_id: Optional[int] = None
            try:
                file_args, missing = _collect_scope_files(
                    conn=conn,
                    scope=scope,
                    project=project_name,
                    batch=batch_name,
                    item=item_name,
                    input_label_map=iteration.input_label_map,
                    tmp_dir=tmp_dir,
                )
                if missing:
                    missing_details = _build_missing_input_details(iteration.input_label_map, missing)
                    return {
                        "status": "error",
                        "reason": "missing_inputs",
                        "missing_labels": sorted(set(missing)),
                        "missing_item_results": [],
                        "iteration_index": idx,
                        "missing_input_details": missing_details,
                    }

                resolved_run_params, missing_cols, results_ctx = _resolve_run_params(
                    conn=conn,
                    project_name=project_name,
                    batch_name=batch_name,
                    item_name=item_name,
                    run_params=iteration.run_params,
                    scope=scope,
                    param_type_map=param_type_map,
                )
                if missing_cols:
                    missing_result_details = _build_missing_result_details(iteration.run_params, missing_cols)
                    return {
                        "status": "error",
                        "reason": "missing_run_params",
                        "missing_labels": [],
                        "missing_item_results": sorted(set(missing_cols)),
                        "iteration_index": idx,
                        "missing_result_details": missing_result_details,
                    }
                
                # --- 提取 stem 变量 ---
                # 优先级：第一个输入参数的 stem
                primary_stem = None
                if file_args:
                    first_val = next(iter(file_args.values()))
                    if isinstance(first_val, list):
                        # 如果是多标签且试图使用 {stem}，报错
                        if iteration.output_pattern and "{stem}" in iteration.output_pattern:
                            return {
                                "status": "error",
                                "reason": "invalid_config",
                                "detail": "Cannot use {stem} in output_pattern when the primary input has multiple labels.",
                                "iteration_index": idx
                            }
                    else:
                        primary_stem = Path(first_val).stem
                
                # 合并基础变量到 results_ctx
                results_ctx.update({
                    "batch": batch_name or "",
                    "item": item_name or "",
                    "prj": project_name,
                    "project": project_name,
                })
                if primary_stem is not None:
                    results_ctx["stem"] = primary_stem

                if enable_history:
                    # next_index = get_next_iteration_index(conn, run_id)
                    history_id = start_run_history(
                        conn,
                        run_id=run_id,  # type: ignore[arg-type]
                        tool_instance=tool_instance_name,
                        code_name=code_name,
                        tool_type="single",
                        project=project_name,
                        batch=batch_name,
                        item=item_name,
                        scope=scope,
                        iteration_index=None,
                    )
                    file_entries = []
                    for name, label_str in iteration.input_label_map.items():
                        val = file_args.get(name)
                        if isinstance(val, list):
                            # 多标签情况：拆分为多个历史记录条目
                            labels = [l.strip() for l in label_str.split(",") if l.strip()]
                            # 理论上 labels 和 val 长度一致，如果不一致（极端异常），以 val 为准
                            for i in range(len(val)):
                                l = labels[i] if i < len(labels) else label_str
                                file_entries.append({
                                    "param_name": name,
                                    "label": l,
                                    "filename": val[i]
                                })
                        else:
                            file_entries.append({
                                "param_name": name,
                                "label": label_str,
                                "filename": val
                            })
                    log_file_inputs(conn, history_id, file_entries)
                    result_entries = _build_result_input_entries(iteration.run_params, resolved_run_params)
                    log_result_inputs(conn, history_id, result_entries)
                    log_run_params(conn, history_id, resolved_run_params)

                ctx = RunContext(
                    scope=scope,
                    project_name=project_name,
                    batch_name=batch_name,
                    item_name=item_name,
                    tool_name=tool_instance_name,
                    tmp_dir=tmp_dir,
                    target_dir=target_dir,
                    output_file_label=iteration.output_file_label,
                    result_col=iteration.result_col,
                    conn=conn,
                    output_pattern=iteration.output_pattern,
                    results_ctx=results_ctx,
                )
                ctx.history_id = history_id
                token = _CURRENT_CONTEXT.set(ctx)

                cwd = os.getcwd()
                os.chdir(tmp_dir)
                try:
                    try:
                        func(tool_instance_name, **file_args, **resolved_run_params)
                    except Exception as e:
                        import traceback
                        tb_str = traceback.format_exc()
                        print(f"[TOOL] Error during execution: {tb_str}")
                        if history_id:
                            finish_run_history(
                                conn,
                                history_id,
                                status="error",
                                error_reason=f"{e.__class__.__name__}: {str(e)}",
                                extra={"message": str(e), "traceback": tb_str},
                            )
                        return {
                            "status": "error",
                            "reason": "tool_exception",
                            "detail": f"{str(e)}\n{tb_str}",
                            "exception_type": e.__class__.__name__
                        }
                    else:
                        if history_id:
                            log_file_outputs(conn, history_id, ctx.file_outputs)
                            log_result_outputs(conn, history_id, ctx.result_outputs)
                            finish_run_history(conn, history_id, status="ok")
                finally:
                    _CURRENT_CONTEXT.reset(token)
                    os.chdir(cwd)

                run_summaries.append(
                    {
                        "index": idx,
                        "output_file": ctx.output_file_rel_path,
                        "output_value": ctx.output_value,
                    }
                )
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        if len(run_summaries) == 1:
            summary = run_summaries[0]
            return {
                "status": "ok",
                "output_file": summary["output_file"],
                "output_value": summary["output_value"],
                "runs": run_summaries,
            }

        return {
            "status": "ok",
            "runs": run_summaries,
        }

    finally:
        if owns_conn:
            conn.close()
