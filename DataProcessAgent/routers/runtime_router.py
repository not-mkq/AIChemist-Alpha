import datetime
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response, PlainTextResponse
from pydantic import BaseModel

import db as db_mod
from db import get_connection
from tool_runtime import (
    run_tool,
    _get_project_tool_config,
    expand_single_tool_iterations,
)
from run_history import build_run_history_dot, render_dot_to_svg
from merge_runtime import run_merge_tool
from meta_runtime import (
    run_meta_tool,
    check_meta_tool_available,
)
from tool_registry import get_tool_type_from_file as get_tool_type
from errors import RunFailure
from request_checker import (
    check_merge_tool_request,
    check_tool_request,
    get_run_param_type_map,
)

logger = logging.getLogger(__name__)

router = APIRouter()

class RunToolRequest(BaseModel):
    project: str
    batch: Optional[str] = None
    item: Optional[str] = None
    tool: str
    scope: str
    available_labels: Optional[List[str]] = None
    available_result_cols: Optional[List[str]] = None
    run_id: Optional[str] = None  # 允许前端预设 ID 用于进度查询

def _collect_text_values(value: Any) -> Set[str]:
    collected: Set[str] = set()
    if value is None: return collected
    if isinstance(value, list):
        for item in value: collected.update(_collect_text_values(item))
        return collected
    text = str(value).strip()
    if text: collected.add(text)
    return collected

def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)

def _build_run_id(body: RunToolRequest) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    parts = ["run", ts, suffix, _safe_slug(body.project), _safe_slug(body.tool), _safe_slug(body.scope.replace("->", "-")), _safe_slug(body.batch or "no-batch"), _safe_slug(body.item or "no-item")]
    return "-".join(parts)

# 快照和备份逻辑（保持与 main.py 一致）
def _backup_sqlite_for_run(run_id: str) -> Dict[str, Any]:
    db_path = Path(db_mod.DB_PATH)
    if not db_path.exists(): return {"status": "skip", "reason": "db_not_found"}
    base_dir = Path("log") if Path("log").is_dir() else Path("log_snapshots")
    dest_dir = base_dir / "db-snapshots"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{run_id}.db"
    try:
        with sqlite3.connect(db_path) as src_conn, sqlite3.connect(dest_path) as dest_conn:
            src_conn.backup(dest_conn)
        return {"status": "ok", "path": str(dest_path)}
    except Exception as e: return {"status": "error", "reason": str(e)}

def _resolve_workspace_dir() -> Path:
    override = os.getenv("WORKSPACE_GIT_DIR")
    if override: return Path(override)
    try:
        import tool_runtime
        if hasattr(tool_runtime, "WORKSPACE_ROOT"): return Path(tool_runtime.WORKSPACE_ROOT)
    except: pass
    return Path(__file__).resolve().parents[1] / "workspace"

def _snapshot_workspace_git(run_id: str, body: RunToolRequest, phase: str) -> Dict[str, Any]:
    workspace_dir = _resolve_workspace_dir()
    try:
        import git
        repo = git.Repo(workspace_dir) if (workspace_dir / ".git").exists() else git.Repo.init(workspace_dir)
        repo.git.add(all=True)
        msg = f"[run][{phase}] {run_id} tool={body.tool} scope={body.scope} project={body.project} batch={body.batch or '-'} item={body.item or '-'}"
        repo.git.commit("--allow-empty", "-m", msg)
        return {"status": "ok", "commit": repo.head.commit.hexsha, "message": msg}
    except Exception as e: return {"status": "error", "reason": str(e)}

def _take_snapshots(body: RunToolRequest, run_id: str, phase: str) -> Dict[str, Any]:
    snapshot_id = f"{run_id}-{phase}"
    return {"db_snapshot": _backup_sqlite_for_run(snapshot_id), "workspace_commit": _snapshot_workspace_git(snapshot_id, body, phase)}

def _restore_db_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    path = snapshot.get("path")
    if snapshot.get("status") != "ok" or not path: return {"status": "skip", "reason": "no_snapshot"}
    try:
        with sqlite3.connect(path) as src_conn, sqlite3.connect(db_mod.DB_PATH) as dest_conn:
            src_conn.backup(dest_conn)
        return {"status": "ok", "restored_from": str(path)}
    except Exception as e: return {"status": "error", "reason": str(e)}

def _rollback_workspace(pre_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if pre_snapshot.get("status") != "ok": return {"status": "skip", "reason": "no_pre_commit"}
    workspace_dir = _resolve_workspace_dir()
    try:
        import git
        repo = git.Repo(workspace_dir)
        repo.git.reset("--hard", pre_snapshot.get("commit"))
        repo.git.clean("-fdx")
        return {"status": "ok", "rollback_to": pre_snapshot.get("commit")}
    except Exception as e: return {"status": "error", "reason": str(e)}

def _build_run_response(payload: Any, run_id: str, pre_snapshot: Dict[str, Any], post_snapshot: Optional[Dict[str, Any]], status_code: int = 200):
    body = payload if isinstance(payload, dict) else {"result": payload}
    body = dict(body)
    body["run_id"], body["run_snapshot"] = run_id, {"pre": pre_snapshot, "post": post_snapshot}
    return JSONResponse(body, status_code=status_code)

@router.post("/run-tool/check")
def check_tool_before_run(body: RunToolRequest):
    from tool_registry import _ensure_tool_loaded
    _ensure_tool_loaded(body.tool)
    conn = get_connection()
    try:
        tool_type = get_tool_type(body.tool)
        if tool_type is None: return JSONResponse({"status": "error", "reason": "tool_not_found"}, status_code=404)
        if tool_type == "meta":
            ok, err = check_meta_tool_available(meta_tool_name=body.tool, project=body.project, batch=body.batch, item=body.item, scope=body.scope, conn=conn)
            return {"status": "ok"} if ok else {"status": "error", **(err or {})}
        if tool_type == "single":
            # ... (保持 single 检查逻辑不变)
            cfg = _get_project_tool_config(conn, body.project, body.tool)
            print(f"[DEBUG] check_tool_before_run: cfg={cfg}")
            
            code_name = cfg.get("code_name", body.tool)
            iterations = expand_single_tool_iterations(cfg)
            print(f"[DEBUG] check_tool_before_run: iterations={iterations}")
            
            param_type_map = get_run_param_type_map(code_name, conn=conn)
            available_labels, available_result_cols = set(body.available_labels or []), set(body.available_result_cols or [])
            for idx, iteration in enumerate(iterations):
                # Use iteration's run_params if body.run_params is empty (it's not even in RunToolRequest model yet, 
                # but we should use iteration's params which are already resolved/expanded)
                missing_labels, missing_cols = check_tool_request(
                    conn=conn,
                    project_name=body.project,
                    batch_name=body.batch,
                    item_name=body.item,
                    input_label_map=iteration.input_label_map,
                    run_params=iteration.run_params,
                    scope=body.scope,
                    code_name=code_name,
                    param_type_map=param_type_map,
                    virtual_labels=available_labels,
                    virtual_result_cols=available_result_cols,
                )
                print(f"[DEBUG] check_tool_before_run: idx={idx}, missing_labels={missing_labels}, missing_cols={missing_cols}")
                
                if missing_labels or missing_cols:
                    return {
                        "status": "error",
                        "reason": "missing_inputs",
                        "missing_labels": missing_labels,
                        "missing_item_results": missing_cols,
                        "iteration_index": idx
                    }
                available_labels.update(_collect_text_values(iteration.output_file_label))
                available_result_cols.update(_collect_text_values(iteration.result_col))
            return {"status": "ok"}
        # merge
        merge_scopes = {"item->batch": "batch_from_items", "item->project": "project_from_items", "batch->project": "project_from_batches"}
        cfg = _get_project_tool_config(conn, body.project, body.tool)
        missing_labels, missing_cols = check_merge_tool_request(conn=conn, project_name=body.project, batch_name=body.batch, merge_mode=merge_scopes[body.scope], input_label_map=cfg.get("input_label_map", {}), input_cols=cfg.get("input_cols") or {}, run_params=cfg.get("run_params", {}), code_name=cfg.get("code_name", body.tool))
        if missing_labels or missing_cols: return {"status": "error", "reason": "missing_inputs", "missing_labels": missing_labels, "missing_results": missing_cols}
        return {"status": "ok"}
    finally: conn.close()

@router.post("/run-tool")
def run_tool_endpoint(body: RunToolRequest):
    from tool_registry import _ensure_tool_loaded
    _ensure_tool_loaded(body.tool)
    run_id = body.run_id or _build_run_id(body)
    pre_snapshot = _take_snapshots(body, run_id, "pre")
    conn = get_connection()
    try:
        tool_type = get_tool_type(body.tool)
        if tool_type == "meta":
            result = run_meta_tool(project_name=body.project, tool_instance_name=body.tool, batch_name=body.batch, item_name=body.item, scope=body.scope, conn=conn, run_id=run_id)
        elif tool_type == "single":
            result = run_tool(project_name=body.project, tool_instance_name=body.tool, batch_name=body.batch if body.scope != "project" else None, item_name=body.item if body.scope == "item" else None, conn=conn, run_id=run_id)
        elif tool_type == "merge":
            merge_scopes = {"item->batch": "batch_from_items", "item->project": "project_from_items", "batch->project": "project_from_batches"}
            result = run_merge_tool(project_name=body.project, batch_name=body.batch if body.scope == "item->batch" else None, tool_instance_name=body.tool, merge_mode=merge_scopes[body.scope], conn=conn)
        else: raise RunFailure({"status": "error", "reason": "tool_not_found"})
        if isinstance(result, dict) and result.get("status") != "ok": raise RunFailure(result)
        post_snapshot = _take_snapshots(body, run_id, "post")
        return _build_run_response(result, run_id, pre_snapshot, post_snapshot)
    except RunFailure as rf: result, status_code = rf.payload, 400
    except Exception as e:
        import traceback
        result, status_code = {"status": "error", "reason": "run_exception", "detail": f"{str(e)}\n{traceback.format_exc()}"}, 500
    finally: conn.close()
    rollback_info = {"db": _restore_db_from_snapshot(pre_snapshot.get("db_snapshot", {})), "workspace": _rollback_workspace(pre_snapshot.get("workspace_commit", {}))}
    result["rollback"] = rollback_info
    return _build_run_response(result, run_id, pre_snapshot, None, status_code=status_code)

@router.get("/run-tool/progress/{run_id}")
def get_run_progress(run_id: str):
    from meta_runtime import get_task_progress
    progress = get_task_progress(run_id)
    if not progress:
        return {"status": "unknown", "run_id": run_id}
    return {**progress, "status": "ok"}


@router.get("/run-history/{run_id}/graph")
def get_run_history_graph(run_id: str, format: str = "svg"):
    conn = get_connection()
    try:
        dot_source = build_run_history_dot(conn, run_id)
        if format == "dot": return PlainTextResponse(dot_source, media_type="text/vnd.graphviz")
        return Response(content=render_dot_to_svg(dot_source), media_type="image/svg+xml")
    finally: conn.close()

