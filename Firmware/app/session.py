from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import json
from openai import OpenAI

from .audit import AuditManager
from .repositories.chat_event_repository import ChatEventRepository
from .tools import (
    ToolExecutor,
    append_tool_result,
    build_tools_from_docs,
    try_jsonschema_validate,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionEvent:
    type: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)

    def as_dict(self) -> Dict[str, Any]:
        # Compatibility: Provide both a flat structure and an explicit 'payload' key
        # The frontend code heavily relies on evt.payload.xxx
        base = {
            "type": self.type, 
            "timestamp": self.timestamp, 
            "payload": self.payload,
            **self.payload
        }
        
        # Ensure there's always a descriptive content field for the UI
        if "content" not in base:
            if self.type == "tool_call":
                tool = self.payload.get("tool")
                base["content"] = f"Calling tool: {tool}"
                # Also ensure content is inside payload for frontend consistency
                if isinstance(self.payload, dict):
                    self.payload["content"] = base["content"]
            elif self.type == "audit_decision":
                approved = "Approved" if self.payload.get("approved") else "Rejected"
                note = self.payload.get("note") or ""
                base["content"] = f"Audit Decision: {approved}. {note}"
                if isinstance(self.payload, dict):
                    self.payload["content"] = base["content"]
        
        return base


class ChatSession:
    def __init__(
        self,
        session_id: str,
        cfg: Dict[str, Any],
        docs: Dict[str, Any],
        logger,
        client: OpenAI,
        decision_provider: Optional[Callable] = None,
        label: Optional[str] = None,
        event_repo: Optional[ChatEventRepository] = None,
    ):
        self.id = session_id
        self.label = label or session_id
        self.cfg = cfg
        self.docs = docs
        self.logger = logger
        self.client = client
        self.system_prompt = cfg["system_prompt"]
        self.messages: List[Dict[str, Any]] = self._base_messages()
        self.events: List[SessionEvent] = []
        self.context_version: int | None = None
        self.context_user_tag: str | None = None
        self.context_meta: Dict[str, Any] = {}
        self.lock = threading.Lock()

        repl_cfg = cfg.get("repl", {}) or {}
        self.strict_validate = bool(repl_cfg.get("strict_jsonschema_validation", True))
        self.max_tool_steps = int(repl_cfg.get("max_tool_steps", 50))
        retry_calls = int(repl_cfg.get("retry_calls", 1))
        backoff_s = float(repl_cfg.get("retry_backoff_s", 1.0))
        temps = cfg["openai_client"]
        self.temperature = temps.get("temperature_final")
        # Some models reject non-default temperature; treat falsy/None as unset.
        try:
            self.temperature = float(self.temperature) if self.temperature is not None else None
        except Exception:
            self.temperature = None

        self.tools_schema = build_tools_from_docs(docs)
        self.event_repo = event_repo or ChatEventRepository()
        self.save_callback: Optional[Callable[[ChatSession], None]] = None # Callback to SessionStore.save_context_version
        self.audit_manager = AuditManager(
            cfg=cfg,
            docs=docs,
            logger=logger,
            emit_event=lambda e: self.emit_event(e.get("type", "audit"), e),
            decision_provider=decision_provider,
        )
        self.tool_executor = ToolExecutor(
            agents_map=cfg["agents"],
            logger=logger,
            audit_manager=self.audit_manager,
            retries=retry_calls,
            backoff_s=backoff_s,
        )

    def emit_event(self, event_type: str, payload: Dict[str, Any], *, actor: Optional[str] = None) -> SessionEvent:
        normalized_payload = dict(payload or {})
        payload_type = normalized_payload.get("type")
        if payload_type == event_type:
            normalized_payload.pop("type", None)
        evt = SessionEvent(type=event_type, payload=normalized_payload)
        self.events.append(evt)
        self.logger.debug(f"[SESSION {self.id}] event={evt.type} payload={payload}")
        self._persist_event(evt, actor=actor)
        return evt

    def _persist_event(self, evt: SessionEvent, *, actor: Optional[str]) -> None:
        idx = self.event_repo.next_index(self.id)
        payload = evt.payload or {}
        
        # Enhanced content extraction for different event types
        content = payload.get("content")
        if not isinstance(content, str):
            if evt.type == "tool_result":
                res = payload.get("result")
                if isinstance(res, str):
                    content = res
                else:
                    content = json.dumps(res, ensure_ascii=False)
            else:
                content = None

        self.event_repo.append(
            session_id=self.id,
            index=idx,
            type_=evt.type,
            actor=actor or self._actor_for_event(evt.type, payload),
            timestamp=evt.timestamp,
            content=content,
            payload=payload,
            flags=None,
        )

    def _actor_for_event(self, event_type: str, payload: Dict[str, Any]) -> str:
        if event_type == "user_message":
            return "user"
        if event_type == "assistant_message":
            return "ai"
        if event_type == "thought":
            return "ai"
        if event_type == "tool_call":
            return payload.get("tool") or "tool"
        if event_type == "tool_result":
            return payload.get("tool") or "tool"
        if event_type.startswith("audit"):
            return "audit_guard"
        if event_type == "system_prompt":
            return "system"
        return "system"

    def list_events(self) -> List[Dict[str, Any]]:
        return [evt.as_dict() for evt in self.events]

    def summary(self) -> Dict[str, Any]:
        return {
            "session_id": self.id,
            "label": self.label,
            "events": len(self.events),
            "context_version": self.context_version,
            "context_user_tag": self.context_user_tag,
            "pending_audits": [
                {
                    "audit_id": ticket.ticket_id,
                    "tool_name": ticket.tool_name,
                    "ai_decision": ticket.ai_decision,
                    "arguments": ticket.arguments,
                }
                for ticket in self.audit_manager.pending_tickets()
            ],
        }

    def resolve_audit(self, audit_id: str, approved: bool, actor: str, note: Optional[str]) -> Dict[str, Any]:
        decision = self.audit_manager.resolve_ticket(audit_id, approved=approved, actor=actor, note=note)
        status_text = "Approved" if approved else "Rejected"
        content = f"Audit {status_text} by {actor}. Note: {note or 'N/A'}"
        
        payload = {
            "audit_id": decision.ticket_id,
            "approved": decision.approved,
            "actor": actor,
            "note": note,
            "detail": decision.detail,
            "content": content,
        }
        self.emit_event("audit_decision", payload, actor=actor)
        return payload

    def _append_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def process_user_message(self, content: str) -> List[Dict[str, Any]]:
        with self.lock:
            context_size = len(self.messages)
            self.logger.info(
                "Session %s received user input (%d chars); context=%d messages",
                self.id,
                len(content),
                context_size,
            )
            self.emit_event("user_message", {"content": content})
            self._append_message("user", content)
            self.logger.info(f"USER[{self.id}]: {content}")

            for hop in range(self.max_tool_steps):
                self.logger.debug(
                    "Session %s invoking model hop=%d/%d with %d messages",
                    self.id,
                    hop + 1,
                    self.max_tool_steps,
                    len(self.messages),
                )
                chat_kwargs = {
                    "model": self.cfg["openai_client"]["default_model"],
                    "messages": self.messages,
                    "tools": self.tools_schema,
                    "tool_choice": "auto",
                }
                if self.temperature is not None:
                    chat_kwargs["temperature"] = self.temperature
                
                # Log full context being sent to AI
                self.logger.debug(f"FULL CONTEXT TO AI:\n{json.dumps(self.messages, ensure_ascii=False, indent=2)}")

                resp = self.client.chat.completions.create(**chat_kwargs)
                msg = resp.choices[0].message

                # Capture "reasoning_content" (DeepSeek-R1 / OpenAI-compatible reasoning models)
                # Note: Official OpenAI o1 does not return reasoning text, but compatible APIs do.
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:
                    self.emit_event("thought", {"content": reasoning})
                    self.logger.info(f"THOUGHT[{self.id}]: {reasoning}")

                if msg.content:
                    self.logger.info(f"AI[{self.id}]: {msg.content}")
                    # Only append to in-memory messages if it's the final message;
                    # if there are tool calls, we'll append the combined dict later.
                    if not getattr(msg, "tool_calls", None):
                        self._append_message("assistant", msg.content)
                    self.emit_event("assistant_message", {"content": msg.content})

                if not getattr(msg, "tool_calls", None):
                    if not msg.content:
                        self.logger.warning("Empty assistant message.")
                    break

                tool_calls_payload = []
                for tc in msg.tool_calls:
                    tool_calls_payload.append(
                        {"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                    )
                self.messages.append(
                    {"role": "assistant", "content": msg.content or "", "tool_calls": tool_calls_payload}
                )

                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        arguments = json.loads(tc.function.arguments or "{}")
                    except Exception as exc:
                        arguments = {}
                        self.logger.error(f"Failed to parse tool arguments: {exc}")

                    self.emit_event("tool_call", {"tool": name, "arguments": arguments, "call_id": tc.id})
                    self.logger.info(
                        "Session %s executing tool '%s' (call_id=%s) with args=%s",
                        self.id,
                        name,
                        tc.id,
                        json.dumps(arguments, ensure_ascii=False),
                    )

                    iface = self.docs.get(name, {}).get("interface")
                    if iface and self.strict_validate:
                        err = try_jsonschema_validate(arguments, iface, self.logger, enabled=True)
                        if err:
                            self.logger.error(err)
                            append_tool_result(self.messages, tc.id, {"error": str(err)})
                            self.emit_event("tool_result", {"tool": name, "result": {"error": str(err)}, "call_id": tc.id})
                            continue

                    result = self.tool_executor.execute(name, arguments, session_id=self.id, call_id=tc.id)
                    append_tool_result(self.messages, tc.id, name, result)
                    self.emit_event("tool_result", {"tool": name, "result": result, "call_id": tc.id})
                    
                    # Persist state immediately after tool result
                    if self.save_callback:
                        self.save_callback(self)
                        self.logger.info(f"Session {self.id} auto-saved context after tool '{name}' result.")
                    self.logger.info(
                        "Session %s tool '%s' finished (call_id=%s)",
                        self.id,
                        name,
                        tc.id,
                    )

            return self.list_events()

    def _apply_event_records(self, events: List[Dict[str, Any]]) -> None:
        self.events = []
        for evt in events:
            payload = dict(evt.get("payload") or {})
            content = evt.get("content")
            
            # Reconstruct content from payload if missing (important for UI display after version switches)
            if not content and payload:
                evt_type = evt.get("type")
                if evt_type == "audit_request":
                    tool = payload.get("tool_name") or "unknown tool"
                    content = f"Audit requested for tool: {tool}"
                elif evt_type == "audit_decision":
                    approved = "Approved" if payload.get("approved") else "Rejected"
                    note = payload.get("note") or ""
                    content = f"Decision: {approved}. Note: {note}"
                elif evt_type == "tool_result":
                    res = payload.get("result")
                    if isinstance(res, str):
                        content = res
                    else:
                        content = json.dumps(res, ensure_ascii=False)
            
            if "content" not in payload and content:
                payload["content"] = content
                
            self.events.append(SessionEvent(type=evt["type"], payload=payload, timestamp=evt["timestamp"]))

    def load_from_history(self, events: List[Dict[str, Any]]) -> None:
        original_count = len(events)
        history_limit = int(self.cfg.get("history_replay_limit", 20000))
        if history_limit > 0 and original_count > history_limit:
            events = events[-history_limit:]
            self.logger.info(
                "Session %s history trimmed from %d to %d events (limit=%d)",
                self.id,
                original_count,
                len(events),
                history_limit,
            )
        else:
            self.logger.debug(
                "Session %s loading %d events (limit=%d)",
                self.id,
                original_count,
                history_limit,
            )

        self._apply_event_records(events)
        self.messages = self._base_messages()
        replay_messages = self._messages_from_events(events)
        for message in replay_messages:
            self.messages.append(message)

        self.logger.info(
            "Session %s restored from history: %d events → %d messages (replay chunk=%d)",
            self.id,
            len(self.events),
            len(self.messages),
            len(replay_messages),
        )

    def load_from_context(
        self,
        messages: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        *,
        version: int | None = None,
        user_tag: str | None = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._apply_event_records(events)
        self.messages = messages
        self.context_version = version
        self.context_user_tag = user_tag
        self.context_meta = meta or {}

    def _base_messages(self) -> List[Dict[str, Any]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": "You have access to the following tools. Use them when helpful."},
        ]

    def _messages_from_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        completed_tool_calls = {
            (evt.get("payload") or {}).get("call_id")
            for evt in events
            if evt.get("type") == "tool_result" and (evt.get("payload") or {}).get("call_id")
        }
        history: List[Dict[str, Any]] = []
        
        # Buffer for the current assistant response "turn"
        curr_asst = {"content": "", "tool_calls": [], "thought": None}
        has_asst_data = False

        def flush_asst():
            nonlocal has_asst_data
            if not has_asst_data:
                return
            
            # Only add if there is something meaningful to show
            if curr_asst["content"] or curr_asst["thought"] or curr_asst["tool_calls"]:
                msg = {"role": "assistant", "content": curr_asst["content"]}
                if curr_asst["tool_calls"]:
                    msg["tool_calls"] = curr_asst["tool_calls"]
                if curr_asst["thought"]:
                    msg["reasoning_content"] = curr_asst["thought"]
                history.append(msg)

            # Reset buffer
            curr_asst.update({"content": "", "tool_calls": [], "thought": None})
            has_asst_data = False

        for evt in events:
            evt_type = evt.get("type")
            payload = evt.get("payload") or {}
            content = payload.get("content") or evt.get("content")

            # If we hit a new role or a tool result, flush any pending assistant data
            if evt_type in ("thought", "assistant_message", "tool_call"):
                has_asst_data = True
            else:
                flush_asst()

            if evt_type == "system_prompt" and content:
                history.append({"role": "system", "content": content})
            elif evt_type == "user_message" and content:
                history.append({"role": "user", "content": content})
            elif evt_type == "thought" and content:
                curr_asst["thought"] = content
            elif evt_type == "assistant_message" and content:
                if curr_asst["content"]:
                    curr_asst["content"] += "\n" + content
                else:
                    curr_asst["content"] = content
            elif evt_type == "tool_call":
                call_id = payload.get("call_id") or f"history_{evt.get('timestamp')}"
                if call_id in completed_tool_calls:
                    curr_asst["tool_calls"].append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": payload.get("tool"),
                            "arguments": json.dumps(payload.get("arguments") or {}, ensure_ascii=False)
                        },
                    })
            elif evt_type == "tool_result":
                tool_name = payload.get("tool") or "tool"
                result = payload.get("result")
                if result is not None:
                    # If result is already a string (e.g. audit guidance), use it directly.
                    # Otherwise, format it as JSON.
                    if isinstance(result, str):
                        result_text = result
                    else:
                        result_text = json.dumps(result, ensure_ascii=False)
                        
                    history.append(
                        {
                            "role": "tool",
                            "name": tool_name,
                            "content": result_text,
                            "tool_call_id": payload.get("call_id"),
                        }
                    )
        
        flush_asst()
        return history
