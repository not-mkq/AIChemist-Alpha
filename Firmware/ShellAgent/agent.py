import os
import sys
import time
import json
import shutil
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify

try:
    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware
except ImportError:  # pragma: no cover - optional dependency at runtime
    uvicorn = None
    WSGIMiddleware = None

app = Flask(__name__)
asgi_app = WSGIMiddleware(app) if WSGIMiddleware else None

# Ensure project root is importable when running as a script (for uvicorn reload).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Agent Metadata
AGENT_ID = "shell_exec_agent"
AGENT_NAME = "shell_exec"
AGENT_DESCRIPTION = "Execute Bash commands and return results via HTTP."
AGENT_VERSION = "1.0"

MAX_OUTPUT_LINES = 200
MAX_OUTPUT_CHARS = 10_000

# Working directory
FILES_ROOT = (Path(__file__).resolve().parent.parent / "files").resolve()
WORKDIR = str(FILES_ROOT)
os.makedirs(WORKDIR, exist_ok=True)

def log_debug(msg):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} DEBUG: {msg}", flush=True)

@app.route("/", methods=["GET"])
def metadata():
    """Return agent metadata following A2A protocol"""
    log_debug("Received metadata request")
    return jsonify({
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "version": AGENT_VERSION,
        "endpoints": ["/task"],
        "workdir": os.path.abspath(WORKDIR),
        "shell": shutil.which("bash") or "bash"
    })

def _truncate_output(text: str) -> str:
    if text is None:
        return ""
    lines = text.splitlines()
    truncated = False
    if len(lines) > MAX_OUTPUT_LINES:
        text = "\n".join(lines[:MAX_OUTPUT_LINES]) + f"\n...[truncated {len(lines) - MAX_OUTPUT_LINES} lines]"
        truncated = True
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + f"...[truncated to {MAX_OUTPUT_CHARS} chars]"
        truncated = True
    return text if truncated else text

def run_bash(command, timeout_s=120, stdin_text=None, extra_env=None):
    """Execute a bash command with bash -lc, in WORKDIR."""
    env = os.environ.copy()
    if isinstance(extra_env, dict):
        # Only allow str->str merges
        for k, v in extra_env.items():
            if isinstance(k, str) and isinstance(v, str):
                env[k] = v

    start = time.time()
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=WORKDIR,
            input=stdin_text if stdin_text is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env
        )
        duration = time.time() - start
        return {
            "stdout": _truncate_output(proc.stdout),
            "stderr": _truncate_output(proc.stderr),
            "exit_code": proc.returncode,
            "duration_s": round(duration, 3)
        }
    except subprocess.TimeoutExpired as e:
        duration = time.time() - start
        return {
            "stdout": _truncate_output(e.stdout or ""),
            "stderr": _truncate_output((e.stderr or "") + f"\n[timeout] Command exceeded {timeout_s}s."),
            "exit_code": 124,
            "duration_s": round(duration, 3)
        }
    except Exception as e:
        duration = time.time() - start
        return {
            "stdout": "",
            "stderr": _truncate_output(f"[error] {type(e).__name__}: {str(e)}"),
            "exit_code": 1,
            "duration_s": round(duration, 3)
        }

@app.route("/task", methods=["POST"])
def handle_task():
    payload = request.json or {}
    log_debug(f"Received task request: {json.dumps(payload, ensure_ascii=False)}")

    task_type = payload.get("type")
    input_data = payload.get("input", {}) or {}

    if task_type == "shell_exec":
        command = input_data.get("command")
        timeout_s = input_data.get("timeout_s", 120)
        stdin_text = input_data.get("stdin")
        env = input_data.get("env")

        if not command or not isinstance(command, str):
            result = {"error": "Invalid input: 'command' (string) is required."}
        else:
            result = run_bash(command, timeout_s=timeout_s, stdin_text=stdin_text, extra_env=env)
    else:
        result = {"error": f"Unknown task type: {task_type}"}

    log_debug(f"Task result: {json.dumps(result, ensure_ascii=False)[:2000]}")
    return jsonify(result)

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5008
    if uvicorn and asgi_app:
        log_debug(f"Starting ShellExec agent (uvicorn, reload) on {host}:{port}")
        uvicorn.run("ShellAgent.agent:asgi_app", host=host, port=port, reload=True)
    else:
        log_debug("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=host, port=port)
