"""Audit agent service.

This server keeps the legacy /audit endpoints for compatibility and adds
an A2A-style /task + /ui/tasks protocol so audit can behave like other
interactive agents (file_agent, etc.). The caller is the backend, not the
LLM; the agent itself can hang while waiting for user confirmation via UI.
"""

from __future__ import annotations

import copy
import json
import logging
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, request
from openai import OpenAI
from common import extract_longest_json
from agent_runtime import should_enable_reload

try:
    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware
except Exception:
    uvicorn = None
    WSGIMiddleware = None

# local optional schema check
try:
    from jsonschema import ValidationError, validate as jsonschema_validate

    HAVE_JSONSCHEMA = True
except Exception:
    HAVE_JSONSCHEMA = False

HERE = Path(__file__).parent.resolve()
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def resolve_files_root(config_path: str | None) -> Path:
    """
    Normalize files_root to an absolute path. If config provides a relative path,
    interpret it relative to the repository root (parent of Audit/).
    """
    raw = config_path or "files"
    root = Path(raw)
    if not root.is_absolute():
        root = (HERE.parent / root).resolve()
    return root


def dbg(msg: str):
    # super-simple debug print; keep timestamps to your runner if needed
    print(f"[AUDIT] {msg}")

class Non200Filter(logging.Filter):
    """Filter uvicorn access logs to only show non-200 responses."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args or ()
            if len(args) >= 5:
                status = int(args[4])
                return status != 200
        except Exception:
            return True
        return True


def build_uvicorn_log_config():
    if uvicorn is None:
        return None
    try:
        cfg = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
        cfg.setdefault("filters", {})
        cfg["filters"]["non200"] = {"()": Non200Filter}
        access_logger = cfg.get("loggers", {}).get("uvicorn.access")
        if access_logger is not None:
            access_logger["filters"] = ["non200"]
        return cfg
    except Exception as exc:
        dbg(f"build log config failed: {exc}")
        return None


# ---------- Agent metadata ----------
AGENT_ID = "audit_service_agent"
AGENT_NAME = "audit_service"
AGENT_VERSION = "0.2"

# ---------- OpenAI client ----------
def build_client() -> OpenAI:
    base_url = CFG.get("openai", {}).get("base_url")
    return OpenAI(base_url=base_url) if base_url else OpenAI()


client = build_client()

FILES_ROOT = resolve_files_root(CFG.get("policy", {}).get("files_root"))
MANUAL_THRESHOLD = int(CFG.get("policy", {}).get("manual_threshold", 50))
TASK_TIMEOUT_S = int(CFG.get("policy", {}).get("task_timeout_s", 60 * 60))

# In-memory audit tasks registry: task_id -> task info
TASKS: Dict[str, Dict[str, Any]] = {}

AI_PROMPT = """You are a rigorous tool call auditor (AI layer).
You will receive:
- tool_name
- agent_intro
- agent_examples (may be many)
- agent_schema (JSON Schema for "arguments")
- call_arguments (the parameters to be called this time)
- user_rules (user-defined fuzzy rules associated with this tool, in natural language)
- workspace_files (list of filenames visible to this tool; do not expose real paths; compare only names/relative paths)

Tasks:
1) Judge whether call_arguments "semantically conforms" to the schema based on agent_schema. Pay attention to allOf/anyOf/if-then-else/enum/required/type, etc.
2) Use user_rules as soft constraints to flag potential violations/conflicts/risks.
3) Compare filenames mentioned in call_arguments with workspace_files:
   - Files appearing in arguments but not in workspace_files are treated as "possibly new/invisible", allowed but increase risk.
4) Output strict JSON (only JSON, no extra text), format:
{
  "approve": true/false,                 // AI suggestion (final decision is up to human)
  "risk_score": 0..100,                  // Integer risk score
  "summary": "English summary under 300 words, summarizing what this call does, feasibility, key assumptions, and points to note",
  "doubts": ["Short English point 1", "Short English point 2"],     // Possible doubts/precautions
  "reasoning": "Short English reasoning under 400 words",    // Optional but recommended
  "checks": {
    "schema_suspicions": ["Doubts about schema (even if formally passed)"],
    "file_presence": {
      "mentioned": ["Filenames mentioned in arguments (deduplicated)"],
      "missing": ["Filenames in arguments but not in workspace"],
      "present": ["Filenames in arguments and in workspace"]
    },
    "rule_hits": ["Short English description of rule hits or potential conflicts"]
  }
}

Rules:
- Strictly return JSON (not markdown!), never output extra text/code blocks.
- If obviously not conforming to schema (e.g., missing required, wrong type, enum mismatch), strictly "approve": false, and highlight the issue in doubts/summary.
- Risk score suggestions: No obvious issues -> <20; Minor doubts -> 20~49; Large uncertainty or many missing external files -> 50~79; Obvious serious issues/high risk -> >=80.
"""

REJECTION_PROMPT = """You are an audit analyst. A tool call was rejected by a human during the audit phase.
You will receive:
- tool_name
- call_arguments
- ai_decision (summary/doubts from the initial AI audit)
- user_note (filled by human upon rejection, can be empty)

Please output JSON:
{
  "analysis": "Short English summary (<=150 words), speculating the core reason for rejection.",
  "possible_causes": ["Point 1", "Point 2"],
  "recommendations": ["Next step suggestion 1", "Next step suggestion 2"]
}
If information is insufficient, indicate "insufficient to judge". Output must be valid JSON.
"""


# ---------- helpers ----------
def list_workspace_files() -> List[str]:
    if not FILES_ROOT.exists():
        dbg(f"files_root missing: {FILES_ROOT}")
        return []
    out: List[str] = []
    for p in FILES_ROOT.iterdir():
        try:
            rel = p.relative_to(FILES_ROOT).as_posix()
        except Exception:
            rel = p.name
        out.append(rel)
    out.sort()
    dbg(f"workspace entries: {len(out)} items (top-level)")
    return out


def clamp_text(s: str, n: int) -> str:
    return s if len(s) <= n else (s[:n] + f"...(truncated/{len(s)})")


def capture_tree_snapshot(max_chars: int = 4000) -> str:
    if not FILES_ROOT.exists():
        return ""
    try:
        proc = subprocess.run(
            ["tree", "-ah", "--noreport", "."],
            cwd=str(FILES_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        dbg(str(FILES_ROOT))
        output = proc.stdout or ""
        return clamp_text(output, max_chars)
    except Exception as exc:
        dbg(f"tree snapshot failed: {exc}")
        return ""


def extract_filenames_from_arguments(arguments: Any) -> List[str]:
    """遍历 arguments 中的所有字符串，粗略抽取可能是文件名的值。"""
    found: List[str] = []

    def walk(x: Any):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            lowered = x.lower()
            for suf in (".csv", ".xlsx", ".zip", ".txt", ".json", ".log", ".gpx", ".xye", ".instprm"):
                if lowered.endswith(suf):
                    found.append(x)
                    break

    walk(arguments)
    return sorted(set(found))


def _run_ai_audit(tool_name: str, agent_doc: Dict[str, Any], arguments: Dict[str, Any], user_rules: List[str]) -> Dict[str, Any]:
    """核心审计逻辑，供 /audit 和 /task 共用。"""
    params_schema = agent_doc.get("interface", {}).get("function", {}).get("parameters", None)
    if not params_schema:
        dbg("missing_parameters_schema")
        return {"format_ok": False, "error": "missing_parameters_schema"}

    if CFG.get("debug", {}).get("echo_payload", True):
        intro = agent_doc.get("intro", "")
        examples = agent_doc.get("examples", [])
        dbg(f"tool={tool_name} | rules={len(user_rules)} | examples={len(examples)}")
        if intro:
            dbg("intro.preview=" + clamp_text(intro, CFG["debug"]["max_preview_chars"]))
        if examples:
            max_ex = int(CFG.get("debug", {}).get("max_examples", 3))
            dbg(
                "examples.preview="
                + clamp_text(json.dumps(examples[:max_ex], ensure_ascii=False), CFG["debug"]["max_preview_chars"])
            )
        dbg("arguments=" + clamp_text(json.dumps(arguments, ensure_ascii=False), CFG["debug"]["max_preview_chars"]))

    if HAVE_JSONSCHEMA:
        try:
            jsonschema_validate(instance=arguments, schema=params_schema)
            dbg("local schema check: PASS")
        except ValidationError as ve:
            dbg(f"local schema check: FAIL | {ve.message}")
            return {
                "format_ok": False,
                "error": "schema_invalid",
                "comment": f"Arguments do not conform to schema: {ve.message}",
            }
    else:
        dbg("jsonschema not installed: skip local check (AI will judge).")

    workspace_files = list_workspace_files()
    workspace_tree = capture_tree_snapshot(int(CFG.get("debug", {}).get("max_preview_chars", 1200)))
    mentioned = extract_filenames_from_arguments(arguments)
    dbg(f"files mentioned in args: {mentioned}")

    payload = {
        "tool_name": tool_name,
        "agent_intro": agent_doc.get("intro", ""),
        "agent_examples": agent_doc.get("examples", []),
        "agent_schema": params_schema,
        "call_arguments": arguments,
        "user_rules": user_rules,
        "workspace_files": workspace_files,
        "workspace_tree": workspace_tree,
    }

    comp = client.chat.completions.create(
        model=CFG.get("openai", {}).get("model", "gpt-4.1"),
        temperature=float(CFG.get("openai", {}).get("temperature", 0.0)),
        messages=[
            {"role": "system", "content": AI_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    txt = comp.choices[0].message.content or "{}"
    dbg("AI raw=" + clamp_text(txt, CFG["debug"]["max_preview_chars"]))

    try:
        try:
            ai = json.loads(txt)
        except Exception:
            fallback = extract_longest_json(txt)
            if not fallback:
                raise
            ai = fallback[1]
        need = ("approve", "risk_score", "summary", "doubts", "checks")
        if not all(k in ai for k in need):
            raise ValueError("missing required keys")
        if not isinstance(ai["approve"], bool):
            raise ValueError("approve must be bool")
        ai["risk_score"] = int(ai["risk_score"])
        if not isinstance(ai.get("doubts", []), list):
            ai["doubts"] = [str(ai["doubts"])]
    except Exception as exc:
        dbg(f"AI output invalid: {exc}")
        return {"format_ok": False, "error": "ai_output_invalid", "comment": str(exc)}

    return {"format_ok": True, "ai_decision": ai, "rules": user_rules}


def _needs_manual(ai_decision: Dict[str, Any]) -> bool:
    # 新约定：无论 AI 建议如何，都需要人工确认；AI 输出仅做参考。
    return True


def _task_public_view(task: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in task.items() if k not in ("wait_event", "result")}


# ---------- Flask app ----------
app = Flask(__name__)
asgi_app = WSGIMiddleware(app) if WSGIMiddleware else None


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.get("/")
def metadata():
    return jsonify(
        {
            "id": AGENT_ID,
            "name": AGENT_NAME,
            "version": AGENT_VERSION,
            "description": "Audit agent (interactive-ready).",
            "endpoints": ["/task", "/audit", "/audit/analyze_rejection"],
        }
    )


@app.post("/audit")
def audit():
    """
    Legacy audit endpoint (kept for compatibility).
    Request JSON:
    {
      "tool_name": "...",
      "agent_doc": { "intro": "...", "examples": [...], "interface": {...} },
      "arguments": { ... },
      "user_rules": ["..."]  // optional
    }
    """
    try:
        req = request.get_json(force=True)
    except Exception:
        dbg("bad_request: cannot parse JSON")
        return jsonify({"format_ok": False, "error": "bad_request"}), 400

    tool_name = (req.get("tool_name") or "").strip()
    agent_doc: Dict[str, Any] = req.get("agent_doc") or {}
    arguments: Dict[str, Any] = req.get("arguments") or {}
    user_rules: List[str] = req.get("user_rules") or []

    if not tool_name:
        dbg("missing_tool_name")
        return jsonify({"format_ok": False, "error": "missing_tool_name"}), 200

    res = _run_ai_audit(tool_name, agent_doc, arguments, user_rules)
    return jsonify(res), 200


@app.post("/task")
def handle_task():
    """A2A /task 入口，支持交互式（需要人工确认）或自动决策两种路径。"""
    try:
        req = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "bad_request", "reason": "Invalid JSON"}), 400

    if req.get("type") != AGENT_NAME:
        return jsonify({"error": "invalid_type", "reason": f"type must be '{AGENT_NAME}'"}), 400

    input_payload = req.get("input") or {}
    tool_name = (input_payload.get("tool_name") or "").strip()
    agent_doc: Dict[str, Any] = input_payload.get("agent_doc") or {}
    arguments: Dict[str, Any] = input_payload.get("arguments") or {}
    user_rules: List[str] = input_payload.get("user_rules") or []
    session_id = input_payload.get("session_id") or req.get("session_id")
    call_id = input_payload.get("call_id") or req.get("call_id")

    if not tool_name:
        return jsonify({"error": "missing_tool_name"}), 200

    res = _run_ai_audit(tool_name, agent_doc, arguments, user_rules)
    ai = res.get("ai_decision") or {}
    rules = res.get("rules") or []
    risk_score = ai.get("risk_score")

    # 当 AI 审计输出不合规时，仍然进入人工确认，但附带错误提示。
    if not res.get("format_ok"):
        ai = ai or {
            "approve": False,
            "summary": res.get("comment") or res.get("error") or "Audit check failed",
            "doubts": [res.get("comment") or res.get("error") or "audit_agent format error"],
            "risk_score": 100,
        }
        risk_score = ai.get("risk_score")

    # 新约定：无论 AI 建议如何，均需人工确认。
    task_id = call_id or f"audit_{uuid.uuid4().hex}"
    wait_event = threading.Event()
    now = time.time()
    task = {
        "task_id": task_id,
        "session_id": session_id,
        "call_id": call_id,
        "tool_name": tool_name,
        "arguments": arguments,
        "ai_decision": ai,
        "rules": rules,
        "risk_score": risk_score,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "announced": False,
        "wait_event": wait_event,
        "result": None,
    }
    TASKS[task_id] = task
    dbg(f"registered audit task {task_id} for tool={tool_name}, session={session_id}")

    waited = wait_event.wait(timeout=TASK_TIMEOUT_S)
    if not waited:
        task["status"] = "timeout"
        task["updated_at"] = time.time()
        return jsonify({"mode": "manual", "approved": False, "ticket_id": task_id, "error": "audit_timeout"}), 200

    result = task.get("result") or {}
    return jsonify(result), 200


@app.get("/ui/tasks")
def list_ui_tasks():
    """前端轮询审计 Agent 获取待人工决策的任务，仅返回尚未下发过的 pending 任务。"""
    session_id = request.args.get("session_id")
    now = time.time()
    tasks: List[Dict[str, Any]] = []
    for task in TASKS.values():
        if task.get("status") != "pending":
            continue
        if session_id and task.get("session_id") != session_id:
            continue
        if task.get("announced"):
            continue
        task["announced"] = True
        task["updated_at"] = now
        tasks.append(_task_public_view(task))
    return jsonify({"tasks": tasks})


@app.post("/ui/tasks/<task_id>/resolved")
def resolve_task(task_id: str):
    """前端在审计决策完成后通知审计 Agent，Agent 决定最终审计结果并唤醒 /task。"""
    task = TASKS.get(task_id)
    if not task:
        return jsonify({"error": "task_not_found"}), 404

    payload = request.get_json(force=True) or {}
    approved = bool(payload.get("approved"))
    note = payload.get("note")
    actor = payload.get("actor") or "user"

    # 如果有用户备注，尝试调用 AI 生成一个最终总结（对齐备注与初审意见）
    detail = task.get("ai_decision", {})
    if note:
        analysis_payload = {
            "tool_name": task.get("tool_name"),
            "arguments": task.get("arguments"),
            "ai_decision": task.get("ai_decision"),
            "user_note": note,
            "approved": approved
        }
        try:
            # 复用 REJECTION_PROMPT 的逻辑，但在 prompt 中适配 approve 情况
            prompt = REJECTION_PROMPT if not approved else """You are an audit analyst. A tool call was approved by a human during the audit phase.
You will receive:
- tool_name
- call_arguments
- ai_decision (summary/doubts from the initial AI audit)
- user_note (filled by human upon approval, can be empty)

Please output JSON:
{
  "analysis": "Short English summary (<=150 words), summarizing the core reasons for human approval or precautions.",
  "recommendations": ["Subsequent execution suggestion 1", "Subsequent execution suggestion 2"]
}
Output must be valid JSON."""
            comp = client.chat.completions.create(
                model=CFG.get("openai", {}).get("model", "gpt-4o"),
                temperature=0.0,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(analysis_payload, ensure_ascii=False)},
                ],
            )
            txt = comp.choices[0].message.content or "{}"
            try:
                analysis = json.loads(txt)
            except Exception:
                fallback = extract_longest_json(txt)
                analysis = fallback[1] if fallback else {}
            
            detail = copy.deepcopy(detail)
            detail["resolution_analysis"] = analysis
        except Exception as exc:
            dbg(f"Resolution analysis failed: {exc}")

    result = {
        "mode": "manual",
        "approved": approved,
        "ticket_id": task_id,
        "ai_decision": task.get("ai_decision"),
        "rules": task.get("rules"),
        "risk_score": task.get("risk_score"),
        "note": note,
        "actor": actor,
        "detail": detail
    }

    task["status"] = "done"
    task["updated_at"] = time.time()
    task["result"] = result
    wait_event = task.get("wait_event")
    if isinstance(wait_event, threading.Event):
        wait_event.set()

    return jsonify({"result": result})


@app.post("/audit/analyze_rejection")
def analyze_rejection():
    try:
        req = request.get_json(force=True)
    except Exception:
        dbg("bad_request: rejection analysis cannot parse JSON")
        return jsonify({"error": "bad_request"}), 400

    payload = {
        "tool_name": req.get("tool_name"),
        "call_arguments": req.get("arguments"),
        "ai_decision": req.get("ai_decision"),
        "user_note": req.get("user_note"),
    }
    try:
        comp = client.chat.completions.create(
            model=CFG.get("openai", {}).get("model", "gpt-4.1"),
            temperature=float(CFG.get("openai", {}).get("temperature", 0.0)),
            messages=[
                {"role": "system", "content": REJECTION_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        txt = comp.choices[0].message.content or "{}"
        dbg("rejection-analysis raw=" + clamp_text(txt, CFG["debug"]["max_preview_chars"]))
        try:
            analysis = json.loads(txt)
        except Exception:
            fallback = extract_longest_json(txt)
            if not fallback:
                raise
            analysis = fallback[1]
        
        # Include original user_note in the final analysis result
        if isinstance(analysis, dict):
            analysis["user_note"] = req.get("user_note")
    except Exception as exc:
        dbg(f"rejection-analysis error: {exc}")
        return jsonify({"error": "analysis_failed", "detail": str(exc)}), 500

    return jsonify(analysis), 200


if __name__ == "__main__":
    server_host = CFG.get("server", {}).get("host", "127.0.0.1")
    server_port = int(CFG.get("server", {}).get("port", 5011))
    cfg_reload = bool(CFG.get("server", {}).get("debug", False))
    use_reload = should_enable_reload("audit", default=cfg_reload or True)
    if uvicorn and asgi_app:
        dbg(f"Starting audit agent with uvicorn (reload={use_reload}) on {server_host}:{server_port}")
        log_config = build_uvicorn_log_config()
        uvicorn.run("Audit.main:asgi_app", host=server_host, port=server_port, reload=use_reload, log_config=log_config)
    else:
        dbg("Uvicorn not available; falling back to Flask built-in server")
        app.run(host=server_host, port=server_port, debug=use_reload)
