from __future__ import annotations

import copy
import logging
from pathlib import Path

import asyncio
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

try:
    import uvicorn
except Exception:  # pragma: no cover - optional runtime dep
    uvicorn = None

from .repositories.session_repository import SessionRepository
from .schemas.api import AuditPayload, ContextCompressPayload, HistoryLoadPayload, MessagePayload, SessionPayload
from .services.session_service import SessionService
from .services.workspace_service import WorkspaceService
from .store import SessionStore

store = SessionStore()
session_repo = SessionRepository(store)
session_service = SessionService(session_repo)
workspace_root = Path(session_repo.config.get("workspace_root", "files"))
workspace_service = WorkspaceService(workspace_root)

app = FastAPI(title="Re-Re-MA Backend", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Non200Filter(logging.Filter):
    """Filter uvicorn access logs to only show non-200 responses."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            args = record.args or ()
            if len(args) >= 5:
                status = int(args[4])
                return status != 200
        except Exception:
            return True
        return True


def install_uvicorn_log_filter():
    if uvicorn is None:
        return
    try:
        cfg = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
        cfg.setdefault("filters", {})
        cfg["filters"]["non200"] = {"()": Non200Filter}
        access_logger = cfg.get("loggers", {}).get("uvicorn.access")
        if access_logger is not None:
            access_logger["filters"] = ["non200"]
        uvicorn.config.LOGGING_CONFIG = cfg
    except Exception as exc:  # noqa: BLE001
        print(f"[backend] install_uvicorn_log_filter failed: {exc}")


install_uvicorn_log_filter()


@app.post("/sessions")
def create_session(payload: SessionPayload = SessionPayload()):
    return session_service.create_session(payload.name)


@app.get("/sessions")
def list_sessions(status: str | None = Query(default=None, description="Filter by status (active/closed)")):
    return {"sessions": session_service.list_sessions(status=status)}


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    return session_service.get_session(session_id)


@app.get("/sessions/{session_id}/timeline")
def get_timeline(session_id: str):
    events = session_service.get_timeline(session_id)
    return {"session_id": session_id, "events": events}


@app.get("/sessions/{session_id}/events")
def get_events(session_id: str):
    return {"session_id": session_id, "events": session_service.get_events(session_id)}


@app.post("/sessions/{session_id}/messages")
def post_message(session_id: str, payload: MessagePayload):
    return session_service.submit_message(
        session_id,
        payload.content,
        context_version=payload.context_version,
        user_tag=payload.user_tag,
    )


@app.post("/sessions/{session_id}/close")
def close_session(session_id: str):
    return session_service.close_session(session_id)


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    try:
        return session_service.task_status(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/audit/{audit_id}")
def resolve_audit(session_id: str, audit_id: str, payload: AuditPayload):
    try:
        return session_service.resolve_audit(session_id, audit_id, payload.decision, payload.actor, payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/logs/latest")
def latest_log():
    return session_service.log_tail()


@app.get("/agents")
def list_agents():
    return {"agents": session_service.list_agents()}


@app.get("/workspace/files")
def workspace_files():
    return {"files": workspace_service.list_files()}


@app.get("/workspace/index")
def workspace_index():
    return workspace_service.index()


@app.get("/workspace/file")
def preview_workspace_file(path: str = Query(..., description="Relative path under workspace")):
    return workspace_service.preview_file(path)


@app.get("/workspace/updates")
async def workspace_updates(
    since: float = Query(0.0, description="Last known modification timestamp"),
    timeout: int = Query(25, ge=1, le=60, description="Long-poll timeout in seconds"),
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        latest = workspace_service.last_modified()
        if latest > since:
            return {"changed": True, "last_modified": latest}
        await asyncio.sleep(1.0)
    return {"changed": False, "last_modified": workspace_service.last_modified()}


@app.get("/workspace/file/download")
def download_workspace_file(path: str = Query(..., description="Relative path under workspace")):
    return workspace_service.download_file(path)


@app.post("/workspace/file/upload")
async def upload_workspace_file(
    file: UploadFile = File(..., description="File to upload into workspace"),
    path: str | None = Form(default=None, description="Optional target relative path/filename under workspace"),
):
    return workspace_service.save_upload(file, target_path=path)


@app.post("/sessions/{session_id}/events/file_upload_prompt")
def create_file_upload_prompt_event(session_id: str, payload: dict):
    """前端根据 file_agent 下发的任务写入 file_upload_prompt 事件。"""
    try:
        session_repo.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    append_event(session_id, "file_upload_prompt", "tool", payload, content=None)
    return {"status": "ok"}


@app.post("/sessions/{session_id}/events/audit_request")
def create_audit_request_event(session_id: str, payload: dict):
    """前端根据 audit_agent /ui/tasks 下发的任务写入 audit_request 事件。"""
    try:
        session_repo.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    append_event(session_id, "audit_request", "audit_guard", payload, content=None)
    return {"status": "ok"}


@app.post("/sessions/{session_id}/events/audit_decision")
def create_audit_decision_event(session_id: str, payload: dict):
    """前端在人工决策后写入 audit_decision 事件（供 audit_agent 交互模式使用）。"""
    try:
        session_repo.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    actor = payload.get("actor") or "audit_guard"
    append_event(session_id, "audit_decision", actor, payload, content=None)
    return {"status": "ok"}


# helper -------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(session_id: str, type_: str, actor: str, payload: dict, content: str | None = None):
    idx = session_service.event_repo.next_index(session_id)
    session_service.event_repo.append(
        session_id=session_id,
        index=idx,
        type_=type_,
        actor=actor,
        timestamp=_utc_now_iso(),
        content=content,
        payload=payload,
        flags=None,
    )


@app.post("/sessions/{session_id}/file/upload")
def upload_session_file(
    session_id: str,
    file: UploadFile = File(..., description="File to upload into workspace"),
    path: str | None = Form(default=None, description="Optional target relative path/filename under workspace"),
    task_id: str | None = Form(default=None, description="Optional file task id for linking upload"),
):
    try:
        session_repo.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    saved = workspace_service.save_upload(file, target_path=path)
    payload = {
        "task_id": task_id,
        "path": saved.get("path"),
        "name": saved.get("name"),
        "size": saved.get("size"),
        "modified": saved.get("modified"),
        "download_url": saved.get("download_url"),
        "overwritten": saved.get("overwritten", False),
        "user_filename": file.filename,
    }
    append_event(session_id, "file_upload_done", "user", payload, content=None)
    return payload


@app.get("/history/sessions")
def list_history_sessions():
    return {"sessions": session_service.list_history_sessions()}


@app.get("/history/sessions/{session_id}")
def get_history_session(session_id: str):
    return session_service.get_history_session(session_id)


@app.delete("/history/sessions/{session_id}")
def delete_history_session(session_id: str):
    if session_repo.is_active(session_id):
        raise HTTPException(status_code=400, detail="session is active; please close it before deleting")
    return session_service.delete_history_session(session_id)


@app.post("/history/sessions/{session_id}/load")
def load_history_session(session_id: str, payload: HistoryLoadPayload = HistoryLoadPayload()):
    return session_service.load_history_session(
        session_id,
        version=payload.version,
        user_tag=payload.user_tag,
        from_events=payload.from_events,
    )


@app.post("/history/sessions/{session_id}/clone")
def clone_history_session(session_id: str, payload: SessionPayload = SessionPayload()):
    return session_service.clone_history_session(session_id, payload.name)

@app.get("/history/sessions/{session_id}/contexts")
def list_history_contexts(session_id: str):
    return session_service.list_context_versions(session_id)


@app.get("/sessions/{session_id}/export/pdf")
def export_session_pdf(session_id: str):
    return session_service.export_pdf(session_id)


@app.get("/sessions/{session_id}/export/html")
def export_session_html(session_id: str):
    return session_service.export_html(session_id)


@app.get("/sessions/{session_id}/context")
def get_context(
    session_id: str,
    version: int | None = Query(default=None),
    user_tag: str | None = Query(default=None),
    include_messages: bool = Query(default=False),
):
    return session_service.context_info(session_id, version=version, user_tag=user_tag, include_messages=include_messages)


@app.post("/sessions/{session_id}/context/refresh")
def refresh_context(session_id: str, user_tag: str | None = Query(default=None)):
    return session_service.refresh_context(session_id, user_tag=user_tag)


@app.post("/sessions/{session_id}/context/compress")
def compress_context(session_id: str, payload: ContextCompressPayload = ContextCompressPayload()):
    return session_service.compress_context(
        session_id,
        version=payload.version,
        user_tag=payload.user_tag,
        new_tag=payload.new_tag,
    )
