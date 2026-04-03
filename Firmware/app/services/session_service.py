from __future__ import annotations

import uuid
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from .. import db
from ..config import build_openai_client, load_config
from ..pdf_export import build_session_pdf
from ..pdf_html import build_session_html
from ..repositories.session_repository import SessionRepository
from ..repositories.chat_event_repository import ChatEventRepository
from ..session_runner import run_session_turn, resolve_audit_ticket


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        event_repo: ChatEventRepository | None = None,
        runner=run_session_turn,
        audit_resolver=resolve_audit_ticket,
    ):
        self.repo = repository
        self.cfg_path = repository.config_path
        self.db_path = repository.db_path
        if event_repo:
            self.event_repo = event_repo
        else:
            database = db.ChatDatabase(self.db_path)
            self.event_repo = ChatEventRepository(database)
        self.runner = runner
        self.audit_resolver = audit_resolver
        self.task_results: Dict[str, Dict[str, Any]] = {}

    def create_session(self, name: Optional[str]):
        session = self.repo.create_session(name)
        return {"session_id": session.id, "summary": session.summary()}

    def list_sessions(self, status: Optional[str] = None):
        sessions = self.repo.list_sessions()
        if status:
            sessions = [s for s in sessions if s.get("status") == status]
        return sessions

    def get_session(self, session_id: str):
        try:
            # Check for version lock in the store
            locked_version = self.repo.store.active_versions.get(session_id)
            
            # Explicitly load the session with that version via the repo
            session = self.repo.get_session(session_id, version=locked_version)
            
            return {"summary": session.summary(), "events": session.list_events()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def get_timeline(self, session_id: str):
        return self.get_events(session_id)

    def get_events(self, session_id: str):
        try:
            locked_version = self.repo.store.active_versions.get(session_id)
            session = self.repo.get_session(session_id, version=locked_version)
            return session.list_events()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def submit_message(self, session_id: str, content: str, *, context_version: int | None = None, user_tag: str | None = None):
        try:
            self.repo.get_session(session_id, version=context_version, user_tag=user_tag)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        
        # Unlock version if user is submitting a new message
        # This ensures the UI view 'advances' to include the new turn
        if hasattr(self.repo.store, "active_versions"):
            self.repo.store.active_versions.pop(session_id, None)

        task_id = uuid.uuid4().hex
        try:
            result = self.runner(
                session_id,
                self.db_path,
                content,
                cfg_path=self.cfg_path,
                context_version=context_version,
                user_tag=user_tag,
            )
            payload = {"task_id": task_id, "status": "done", "result": result}
        except Exception as exc:  # pragma: no cover - surfaced via task_status
            if hasattr(self.repo, "logger"):
                self.repo.logger.error(f"Session run failed: {exc}", exc_info=True)
            elif hasattr(self.event_repo.database, "logger"): # Try to find a logger
                 pass # Fallback
            else:
                 print(f"ERROR: Session run failed: {exc}")
            payload = {"task_id": task_id, "status": "error", "error": str(exc)}
        self.task_results[task_id] = payload
        return {"task_id": task_id, "status": payload["status"]}

    def task_status(self, task_id: str):
        payload = self.task_results.get(task_id)
        if not payload:
            raise KeyError(f"task not found: {task_id}")
        if payload["status"] != "running":
            self.task_results.pop(task_id, None)
        return payload

    def resolve_audit(self, session_id: str, audit_id: str, decision: str, actor: Optional[str], note: Optional[str]):
        decision_bool = decision == "approve"
        
        # Unlock version when an audit decision is made
        if hasattr(self.repo.store, "active_versions"):
            self.repo.store.active_versions.pop(session_id, None)

        try:
            event = self.audit_resolver(session_id, audit_id, decision_bool, actor, note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"audit_id": audit_id, "status": "resolved", "event": event}

    def list_agents(self):
        return self.repo.get_docs()

    def list_history_sessions(self):
        return self.event_repo.list_sessions_overview()

    def _history_events(self, session_id: str) -> List[Dict[str, Any]]:
        events = self.event_repo.list_by_session(session_id)
        if not events:
            raise HTTPException(status_code=404, detail="session not found")
        return events

    def _history_label(self, session_id: str) -> str:
        record = self.event_repo.get_session_record(session_id)
        if record:
            return record.get("label") or session_id
        return session_id

    def get_history_session(self, session_id: str):
        events = self._history_events(session_id)
        return {"session_id": session_id, "label": self._history_label(session_id), "events": events}

    def delete_history_session(self, session_id: str):
        self._history_events(session_id)
        deleted = self.event_repo.delete_session(session_id)
        self.repo.delete_contexts(session_id)
        return {"session_id": session_id, "deleted_events": deleted}

    def load_history_session(self, session_id: str, *, version: int | None = None, user_tag: str | None = None, from_events: bool = False):
        self._history_events(session_id)
        try:
            session = self.repo.load_session_from_history(session_id, version=version, user_tag=user_tag, force_rebuild=from_events)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "session": session.summary(),
            "events": session.list_events(),
            "context_version": session.context_version,
            "context_user_tag": session.context_user_tag,
        }

    def close_session(self, session_id: str):
        try:
            return self.repo.close_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def context_info(
        self,
        session_id: str,
        *,
        version: int | None = None,
        user_tag: str | None = None,
        include_messages: bool = False,
    ):
        if version is not None:
            ctx = self.repo.context_version(session_id, version)
        elif user_tag:
            ctx = self.repo.context_by_tag(session_id, user_tag)
        else:
            ctx = self.repo.context_latest(session_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="context version not found")
        return {
            "session_id": session_id,
            "version": ctx.get("version"),
            "user_tag": ctx.get("user_tag"),
            "created_at": ctx.get("created_at"),
            "meta": ctx.get("meta"),
            "messages": ctx.get("messages") if include_messages else None,
        }

    def list_context_versions(self, session_id: str):
        versions = self.repo.list_context_versions(session_id)
        return {"session_id": session_id, "versions": versions}

    def refresh_context(self, session_id: str, *, user_tag: str | None = None):
        try:
            return self.repo.refresh_context(session_id, user_tag=user_tag)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def compress_context(self, session_id: str, *, version: int | None = None, user_tag: str | None = None, new_tag: str | None = None):
        # 压缩的是“上下文快照”，而不是事件流；事件只有一份，context 可以有多个版本。
        def _source_context() -> Dict[str, Any]:
            if version is not None:
                ctx = self.repo.context_version(session_id, version)
                if ctx:
                    return ctx
            if user_tag:
                ctx = self.repo.context_by_tag(session_id, user_tag)
                if ctx:
                    return ctx
            latest = self.repo.context_latest(session_id)
            if latest:
                return latest
            # 若没有任何上下文，则先从事件重建一份上下文，再返回最新版本。
            self.repo.refresh_context(session_id, user_tag=user_tag)
            ctx_latest = self.repo.context_latest(session_id)
            if ctx_latest:
                return ctx_latest
            raise HTTPException(status_code=404, detail="context version not found")

        try:
            ctx = _source_context()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        cfg = load_config(self.cfg_path)
        client = build_openai_client(cfg["openai_client"])
        prompt = (
            "You are a dialogue compressor.\n"
            "Rewrite the conversation in a much shorter form while preserving:\n"
            "- user intentions\n"
            "- problems to solve\n"
            "- decisions and constraints\n"
            "- tool calls and arguments\n"
            "- important facts and context that future turns rely on\n\n"
            "Remove:\n"
            "- greetings, filler language\n"
            "- stylistic details\n"
            "- emotional expressions\n"
            "- non-consequential branches\n\n"
            "Output a minimal, information-complete summary.\n"
            "If any ambiguity exists, prefer keeping information."
        )

        def _flatten_messages(msgs: List[Dict[str, Any]]) -> str:
            lines = []
            # skip base system prompts (first two messages)
            for msg in msgs[2:]:
                role = msg.get("role", "assistant").upper()
                content = msg.get("content") or ""
                if msg.get("tool_calls"):
                    tool_calls = msg["tool_calls"]
                    for tc in tool_calls:
                        lines.append(f"ASSISTANT TOOL_CALL {tc.get('function', {}).get('name')}: {tc.get('function', {}).get('arguments')}")
                elif role == "TOOL":
                    name = msg.get("name") or "tool"
                    lines.append(f"TOOL {name}: {content}")
                else:
                    lines.append(f"{role}: {content}")
            return "\n".join(lines)

        source_messages = ctx.get("messages") or []
        convo_text = _flatten_messages(source_messages)
        # Some models (e.g., gpt-5 preview) disallow non-default temperature; omit when None/unsupported.
        model_temp = cfg["openai_client"].get("temperature_final")
        temperature = None if model_temp is None else float(model_temp)
        try:
            kwargs = {
                "model": cfg["openai_client"]["default_model"],
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": convo_text},
                ],
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:  # pragma: no cover
            # Fallback: avoid hard failure when OpenAI is unavailable; build a local truncated summary.
            logger = getattr(self.repo, "logger", None) or getattr(getattr(self.repo, "store", None), "logger", None)
            if logger and hasattr(logger, "warning"):
                logger.warning(f"Compression via OpenAI failed: {exc}; using local fallback.")
            else:
                print(f"[WARN] Compression via OpenAI failed: {exc}; using local fallback.")

            def _fallback_summary(msgs: List[Dict[str, Any]], limit: int = 20) -> str:
                lines = []
                for msg in msgs[-limit:]:
                    role = msg.get("role", "assistant").upper()
                    content = (msg.get("content") or "").strip()
                    if not content:
                        continue
                    lines.append(f"{role}: {content}")
                return " | ".join(lines) if lines else "No prior messages to compress."

            summary = _fallback_summary(source_messages)
        else:
            summary = resp.choices[0].message.content or ""
        prev_version = ctx.get("version")
        base_prefix = source_messages[:2] if len(source_messages) >= 2 else source_messages
        new_messages = list(base_prefix) + [{"role": "assistant", "content": summary}]
        meta = {"source": "compressed", "from_version": prev_version, "compressed": True}
        target_tag = new_tag or user_tag or ctx.get("user_tag")
        version_id = self.repo.context_repo.save_version(session_id, new_messages, user_tag=target_tag, meta=meta)
        return {"session_id": session_id, "version": version_id, "user_tag": target_tag}

    def clone_history_session(self, session_id: str, name: Optional[str]):
        self._history_events(session_id)
        try:
            session = self.repo.clone_session_from_history(session_id, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"session": session.summary()}

    def export_pdf(self, session_id: str):
        summary = self._session_summary(session_id)
        events = self.event_repo.list_by_session(session_id)
        agents = self.repo.get_docs()
        pdf_bytes = build_session_pdf(summary, events, agents)
        filename = f"session_{session_id}.pdf"
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def export_html(self, session_id: str):
        summary = self._session_summary(session_id)
        events = self.event_repo.list_by_session(session_id)
        agents = self.repo.get_docs()
        html = build_session_html(summary, events, agents)
        filename = f"session_{session_id}.html"
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def log_tail(self, max_bytes: int = 4000):
        logfile = self.repo.get_log_path()
        if not logfile:
            raise HTTPException(status_code=404, detail="log file not available")
        try:
            with open(logfile, "r", encoding="utf-8", errors="ignore") as handle:
                data = handle.read()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="log file not available") from None
        return {"path": logfile, "tail": data[-max_bytes:]}

    # internal helpers -------------------------------------------------

    def _session_summary(self, session_id: str):
        try:
            return self.repo.session_summary(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
