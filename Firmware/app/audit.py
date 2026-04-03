from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

import requests


@dataclass
class AuditDecision:
    approved: bool
    reason: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    ticket_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    user_note: Optional[str] = None


class AuditManager:
    """Audit gateway: always delegates to the external audit_agent /task API."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        docs: Dict[str, Any],
        logger,
        emit_event: Callable[[Dict[str, Any]], None],
        decision_provider: Optional[Callable[[AuditDecision], None]] = None,
    ):
        self.cfg = cfg
        self.docs = docs
        self.logger = logger
        self.emit_event = emit_event
        self.decision_provider = decision_provider

    def resolve_ticket(self, audit_id: str, approved: bool, actor: str, note: Optional[str]) -> AuditDecision:
        auditor_cfg = self.cfg.get("auditor") or {}
        audit_url = auditor_cfg.get("audit_url")
        if not audit_url:
            self.logger.warning(f"resolve_ticket called but audit_url not configured. audit_id={audit_id}")
            return AuditDecision(approved=approved, ticket_id=audit_id)

        # Transform ".../task" to ".../ui/tasks/{audit_id}/resolved"
        base_url = audit_url
        if base_url.endswith("/task"):
            base_url = base_url[:-5]
        
        resolve_url = f"{base_url.rstrip('/')}/ui/tasks/{audit_id}/resolved"
        payload = {
            "approved": approved,
            "actor": actor,
            "note": note
        }

        try:
            self.logger.info(f"Resolving remote audit ticket {audit_id} via {resolve_url}")
            resp = requests.post(resolve_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            res = data.get("result") or {}
            
            return AuditDecision(
                approved=res.get("approved", approved),
                reason=res.get("reason"),
                ticket_id=res.get("ticket_id", audit_id),
                detail=res.get("detail") or res,
                payload=res.get("ai_decision"),
                user_note=res.get("note") or note,
            )
        except Exception as exc:
            self.logger.error(f"Failed to resolve audit ticket {audit_id}: {exc}")
            raise RuntimeError(f"Audit agent communication failed: {exc}")

    def pending_tickets(self) -> List[Any]:
        """No local tickets when using audit_agent."""
        return []

    def _call_audit_service(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        session_id: Optional[str] = None,
        call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        auditor_cfg = self.cfg.get("auditor") or {}
        audit_url = auditor_cfg.get("audit_url")
        if not audit_url:
            self.logger.debug("Audit disabled (no auditor.audit_url); bypass.")
            return {"approved": True}

        agent_doc = self.docs.get(tool_name)
        if not agent_doc:
            self.logger.warning(f"No agent_doc for {tool_name}; bypass audit.")
            return {"approved": True}

        rules = (auditor_cfg.get("user_rules", {}) or {}).get(tool_name, [])
        payload = {
            "tool_name": tool_name,
            "agent_doc": agent_doc,
            "arguments": arguments,
            "user_rules": rules,
            "session_id": session_id,
            "call_id": call_id,
        }
        try:
            task_payload = {"type": "audit_service", "input": payload}
            self.logger.debug(f"[AUDIT] → POST {audit_url} (task api only)")
            resp = requests.post(audit_url, json=task_payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            self.logger.debug(f"[AUDIT] ← {data}")
            raw = {"format_ok": True, "ai_decision": data.get("ai_decision") or {}}
            res: Dict[str, Any] = {
                "approved": data.get("approved", True),
                "raw": raw,
                "rules": data.get("rules") or rules,
                "ticket_id": data.get("ticket_id") or data.get("call_id") or uuid.uuid4().hex,
                "reason": data.get("reason"),
                "detail": data.get("detail"),
                "note": data.get("note"),
                "mode": data.get("mode"),
                "actor": data.get("actor"),
            }
            return res
        except Exception as exc:
            self.logger.warning(f"Audit service error: {exc}; bypass audit.")
            return {"approved": True}

    def _analyze_rejection(self, tool_name: str, arguments: Dict[str, Any], ai_decision: Dict[str, Any], note: Optional[str]) -> Optional[Dict[str, Any]]:
        auditor_cfg = self.cfg.get("auditor") or {}
        audit_url = auditor_cfg.get("audit_url")
        if not audit_url:
            return None
        analysis_url = urljoin(audit_url.rstrip("/") + "/", "analyze_rejection")
        payload = {
            "tool_name": tool_name,
            "arguments": arguments,
            "ai_decision": ai_decision,
            "user_note": note,
        }
        try:
            resp = requests.post(analysis_url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            self.logger.debug(f"[AUDIT] rejection analysis ← {data}")
            return data
        except Exception as exc:
            self.logger.warning(f"Rejection analysis failed: {exc}")
            return None

    def request(self, tool_name: str, arguments: Dict[str, Any]) -> AuditDecision:
        res = self._call_audit_service(tool_name, arguments)
        raw = res.get("raw") or {}
        ai = raw.get("ai_decision") or {}
        return AuditDecision(
            approved=bool(res.get("approved", True)), 
            payload=ai, 
            ticket_id=res.get("ticket_id"),
            user_note=res.get("note")
        )

    def request_with_confirmation(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        session_id: Optional[str] = None,
        call_id: Optional[str] = None,
    ) -> AuditDecision:
        res = self._call_audit_service(tool_name, arguments, session_id=session_id, call_id=call_id)
        approved = bool(res.get("approved", True))
        raw_payload = res.get("raw") or {}
        ai = raw_payload.get("ai_decision") or {}
        rules = res.get("rules") or []
        detail = res.get("detail")
        if not detail and ai:
            detail = {
                "ai_summary": ai.get("summary"),
                "ai_doubts": ai.get("doubts"),
                "risk_score": ai.get("risk_score"),
                "rules": rules,
                "user_note": res.get("note") or "",
            }
        reason = res.get("reason")
        if not approved and not reason:
            reason = "Audit rejected by audit_service"
        ticket_id = res.get("ticket_id") or uuid.uuid4().hex

        decision = AuditDecision(
            approved=approved,
            reason=reason,
            payload=ai or raw_payload,
            ticket_id=ticket_id,
            detail=detail,
            user_note=res.get("note"),
        )

        if not approved and not detail:
            decision.detail = self._analyze_rejection(tool_name, arguments, ai, res.get("note"))
        if self.decision_provider:
            self.decision_provider(decision)
        return decision
