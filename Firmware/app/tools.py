from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import requests

from .audit import AuditManager


def _join_description(intro: str, examples: List[dict]) -> str:
    """Build a rich description that includes intro + up to 3 examples (pretty-printed JSON)."""
    parts = []
    intro = (intro or "").strip()
    if intro:
        parts.append(intro)
    if examples:
        parts.append("\nExamples:")
        for i, ex in enumerate(examples[:3], 1):
            pretty = json.dumps(ex, ensure_ascii=False, indent=2)
            parts.append(f"Example {i}:\n{pretty}")
    return "\n".join(parts).strip()


def build_tools_from_docs(docs: dict) -> List[dict]:
    tools = []
    for name, spec in docs.items():
        iface = spec.get("interface", {})
        fn = (iface or {}).get("function", {})
        params = (fn or {}).get("parameters")
        if not params:
            continue
        desc = _join_description(spec.get("intro") or "", spec.get("examples") or [])
        tools.append(
            {
                "type": "function",
                "function": {"name": name, "description": desc, "parameters": params},
            }
        )
    return tools


def try_jsonschema_validate(args: dict, interface_schema: dict, logger, enabled: bool) -> Optional[str]:
    if not enabled:
        return None
    try:
        import jsonschema  # type: ignore
    except Exception:
        logger.debug("jsonschema not installed; skipping strict validation.")
        return None

    try:
        params_schema = interface_schema["function"]["parameters"]
    except Exception as exc:
        return f"Invalid interface: missing function.parameters ({exc})"

    try:
        import jsonschema

        jsonschema.validate(instance=args, schema=params_schema)
        return None
    except Exception as exc:  # pragma: no cover - best effort message
        return f"Arguments do not conform to schema: {exc}"


def append_tool_result(messages: List[Dict[str, Any]], tool_call_id: str, tool_name: str, result_obj: Any):
    if isinstance(result_obj, str):
        content = result_obj
    else:
        content = json.dumps(result_obj, ensure_ascii=False)
    
    messages.append(
        {
            "role": "tool",
            "name": tool_name,
            "tool_call_id": tool_call_id,
            "content": content,
        }
    )


class ToolExecutor:
    def __init__(
        self,
        agents_map: Dict[str, str],
        logger,
        audit_manager: AuditManager,
        retries: int = 1,
        backoff_s: float = 1.0,
    ):
        self.agents_map = agents_map
        self.logger = logger
        self.audit_manager = audit_manager
        self.retries = retries
        self.backoff_s = backoff_s

    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        session_id: Optional[str] = None,
        call_id: Optional[str] = None,
    ) -> Any:
        decision = self.audit_manager.request_with_confirmation(tool_name, arguments, session_id=session_id, call_id=call_id)
        if not decision.approved:
            # Extract comprehensive high-value information for the AI
            reason_str = decision.reason or "Audit rejected."
            user_comment = decision.user_note
            detail = decision.detail or {}
            
            # 1. High-level Doubts & Analysis
            doubts = detail.get("doubts", [])
            res_analysis = detail.get("resolution_analysis") or {}
            analysis_text = res_analysis.get("analysis", "")
            recommendations = res_analysis.get("recommendations", [])

            # 2. Detailed Checks
            checks = detail.get("checks", {})
            schema_suspicions = checks.get("schema_suspicions", [])
            rule_hits = checks.get("rule_hits", [])
            
            file_checks = checks.get("file_presence", {})
            missing_files = file_checks.get("missing", [])
            present_files = file_checks.get("present", [])

            # 3. Construct a comprehensive plain-text guidance message
            lines = [f"ERROR: Tool call '{tool_name}' was REJECTED by the audit system."]
            lines.append(f"Ticket ID: {decision.ticket_id}")
            lines.append(f"Primary Reason: {reason_str}")
            
            if user_comment:
                lines.append(f"Human Auditor Comment: {user_comment}")
            
            if doubts:
                lines.append(f"System Doubts: {'; '.join(doubts)}")
            
            if schema_suspicions:
                lines.append(f"Schema Violations/Suspicions: {'; '.join(schema_suspicions)}")
            
            if rule_hits:
                lines.append(f"Rule Violations: {'; '.join(rule_hits)}")

            if present_files:
                lines.append(f"Confirmed Files: {', '.join(present_files)}")
            if missing_files:
                lines.append(f"MISSING FILES: {', '.join(missing_files)}")

            if analysis_text:
                lines.append(f"Technical Analysis: {analysis_text}")
            if recommendations:
                lines.append(f"Recommendations for you: {'; '.join(recommendations)}")
            
            lines.append("\nINSTRUCTION: Your request cannot be executed as-is. Please analyze the feedback above, fix your parameters (especially filenames or schema mismatches), and provide a new corrected tool call. If the rejection seems to require human intervention, inform the user about the Ticket ID.")
            
            # Return the raw string to be used as message content
            return "\n".join(lines)

        url = self.agents_map.get(tool_name) or self.agents_map.get("default")
        if not url:
            return {"error": f"No URL configured for '{tool_name}' and no default URL."}

        payload: Dict[str, Any] = {"type": tool_name, "input": arguments}
        # 对于交互式 Agent（例如 file_service），我们把 session_id/call_id 作为元数据附加，
        # Agent 在返回最终 tool result 之前不会再与后端通信。
        if tool_name == "file_service":
            if session_id:
                payload["session_id"] = session_id
            if call_id:
                payload["call_id"] = call_id
        self.logger.debug(f"CALL TOOL → {tool_name} | Arguments: {json.dumps(payload, ensure_ascii=False)}")

        last_err: Optional[Exception] = None
        timeout_seconds = 36000 if tool_name == "ml_training_agent" else 300
        for attempt in range(self.retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=timeout_seconds)
                resp.raise_for_status()
                data = resp.json()
                # 若前面经过了审计确认，且产生了 ticket_id，则在成功的工具结果中补充审计元信息，
                # 方便前端基于 tool_result 与 audit_request/audit_decision 组装完整 AuditBundle。
                if isinstance(data, dict) and getattr(decision, "ticket_id", None):
                    ticket_id = decision.ticket_id
                    if ticket_id and "audit_ticket_id" not in data:
                        data["audit_ticket_id"] = ticket_id
                self.logger.debug(f"TOOL RESPONSE ← {tool_name} | Return: {data}")
                return data
            except Exception as exc:
                last_err = exc
                self.logger.warning(f"Tool call failed (attempt {attempt+1}/{self.retries+1}): {exc}")
                if attempt < self.retries:
                    time.sleep(self.backoff_s * (2 ** attempt))

        safe_err = self._summarize_error(last_err)
        soft_err = {"error": safe_err, "tool_name": tool_name, "arguments": arguments}
        self.logger.debug(f"TOOL RESPONSE ← {tool_name} | Return: {soft_err}")
        return soft_err

    def _summarize_error(self, err: Optional[Exception]) -> str:
        if err is None:
            return "Unknown error"
        msg = str(err)
        # Hide host/port details, keep root cause
        if "Failed to establish a new connection" in msg:
            return "Failed to establish a new connection: [Errno 111] Connection refused"
        if "Max retries exceeded" in msg:
            return "Request failed: service unreachable"
        return msg
