import os
import sys
import time
import json
import traceback
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, request, jsonify
from ragflow_sdk import RAGFlow
try:
    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware
except ImportError:
    uvicorn = None
    WSGIMiddleware = None


def load_config() -> Dict[str, Any]:
    config_path = Path(__file__).with_name("config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


config = load_config()

app = Flask(__name__)

# Agent Metadata
AGENT_ID = config["agent"]["id"]
AGENT_NAME = config["agent"]["name"]
AGENT_DESCRIPTION = config["agent"]["description"]
AGENT_VERSION = config["agent"]["version"]

# RAGFlow Configuration
API_KEY = os.getenv("RAGFLOW_API_KEY", config["ragflow"].get("api_key", ""))
RAW_BASE_URL = config["ragflow"]["base_url"]
ASSISTANT_NAME = config["ragflow"]["assistant_name"]
STREAM_RESPONSE = config["ragflow"].get("stream", True)
REQUEST_TIMEOUT = config["ragflow"].get("request_timeout_seconds", 60)
INCLUDE_REFERENCES = bool(config["ragflow"].get("include_references", True))

def normalize_base_url(raw_url: str) -> str:
    parsed = urlparse(raw_url if "://" in raw_url else f"http://{raw_url}")
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    if ":" not in netloc.split("@")[-1]:
        netloc = f"{netloc}:9380"
    return urlunparse((scheme, netloc, path, "", "", ""))


BASE_URL = normalize_base_url(RAW_BASE_URL)

rag = RAGFlow(api_key=API_KEY, base_url=BASE_URL)
asgi_app = WSGIMiddleware(app) if WSGIMiddleware else None

# Ensure project root is importable when running as a script (for uvicorn reload).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def log_debug(msg: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} DEBUG: {msg}")


def patch_requests_timeout(timeout_seconds: int):
    """Inject a default timeout into requests.Session.request if none is provided."""
    original_request = requests.sessions.Session.request
    if getattr(original_request, "_ragflow_timeout_patched", False):
        return

    def _request_with_timeout(self, method, url, **kwargs):
        kwargs.setdefault("timeout", timeout_seconds)
        return original_request(self, method, url, **kwargs)

    _request_with_timeout._ragflow_timeout_patched = True
    requests.sessions.Session.request = _request_with_timeout


def run_with_retries(func, *args, retries: int = 2, delay: float = 1.0, **kwargs):
    last_err: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as err:  # noqa: BLE001
            last_err = err
            log_debug(f"{func.__name__} failed ({attempt + 1}/{retries + 1}): {err}")
            if attempt < retries:
                time.sleep(delay)
    if last_err:
        raise last_err


def get_assistant():
    assistant_list = run_with_retries(rag.list_chats, name=ASSISTANT_NAME)
    if not assistant_list:
        raise ValueError(f"No assistant found with name: {ASSISTANT_NAME}")
    return assistant_list[0]


def get_session(assistant, session_id: Optional[str]):
    if session_id:
        sessions = run_with_retries(assistant.list_sessions, id=session_id)
        if sessions:
            return sessions[0]
        raise ValueError(f"Session not found: {session_id}")
    return run_with_retries(assistant.create_session)


def reshape_reference(reference: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not reference:
        return []

    # RagFlow may return {"chunks": [...]} or a raw list.
    if isinstance(reference, dict):
        if "chunks" in reference and isinstance(reference["chunks"], list):
            reference = reference["chunks"]
        else:
            return []

    if not isinstance(reference, list):
        return []

    normalized = []
    for chunk in reference:
        if not isinstance(chunk, dict):
            continue
        normalized.append(
            {
                "id": chunk.get("id") or chunk.get("chunk_id"),
                "content": chunk.get("content") or chunk.get("content_with_weight"),
                "document_id": chunk.get("document_id") or chunk.get("doc_id"),
                "document_name": chunk.get("document_name") or chunk.get("docnm_kwd"),
                "dataset_id": chunk.get("dataset_id") or chunk.get("kb_id"),
                "similarity": chunk.get("similarity"),
                "vector_similarity": chunk.get("vector_similarity"),
                "term_similarity": chunk.get("term_similarity"),
                "positions": chunk.get("positions"),
            }
        )
    return normalized


def ask_completion_stream(session, question: str):
    """Stream RagFlow completion, yielding parsed data chunks."""
    payload = {"question": question, "stream": True, "session_id": session.id}
    resp = rag.post(f"/chats/{session.chat_id}/completions", json=payload, stream=True)
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if line.startswith("{"):
            try:
                json_data = json.loads(line)
                message = json_data["message"] if isinstance(json_data, dict) and "message" in json_data else str(json_data)
            except Exception:  # noqa: BLE001
                message = line
            raise Exception(message)
        if not line.startswith("data:"):
            continue
        try:
            json_data = json.loads(line[5:])
        except Exception as parse_err:  # noqa: BLE001
            log_debug(f"Stream parse warning: {parse_err}")
            continue
        data = json_data.get("data") if isinstance(json_data, dict) else None
        if data is True or data is None:
            continue
        yield data


def ask_completion_once(session, question: str) -> Dict[str, Any]:
    """Non-stream RagFlow completion."""
    payload = {"question": question, "stream": False, "session_id": session.id}
    resp = rag.post(f"/chats/{session.chat_id}/completions", json=payload, stream=False)
    data_json = resp.json()
    if data_json.get("code") != 0:
        raise Exception(data_json.get("message", "RagFlow error"))
    return data_json.get("data", {}) or {}


def ask_with_optional_stream(session, question: str, stream_preferred: bool):
    """Stream if possible; on chunk errors, retry once with non-stream."""
    full_content = ""
    references: List[Dict[str, Any]] = []
    warning: Optional[str] = None

    if stream_preferred:
        try:
            streamed = ask_completion_stream(session, question)
            for chunk in streamed:
                if isinstance(chunk, dict):
                    chunk_content = chunk.get("answer", "") or chunk.get("content", "")
                    chunk_reference = reshape_reference(chunk.get("reference"))
                else:  # handle raw string chunks
                    chunk_content = str(chunk)
                    chunk_reference = []
                if chunk_reference:
                    references = chunk_reference
                print(chunk_content[len(full_content):], end="", flush=True)
                full_content = chunk_content
            return full_content, references, warning
        except requests.exceptions.ChunkedEncodingError as stream_err:
            warning = f"Stream interrupted: {stream_err}"
            log_debug(warning)
        except Exception as err:  # noqa: BLE001
            warning = f"Stream failed: {err}"
            log_debug(warning)

    # Fallback to non-stream
    data = ask_completion_once(session, question)
    if isinstance(data, dict):
        full_content = data.get("answer", "") or full_content
        references = reshape_reference(data.get("reference"))
    elif isinstance(data, str):
        full_content = data
    else:
        full_content = str(data)
    return full_content, references, warning


patch_requests_timeout(REQUEST_TIMEOUT)


@app.route("/", methods=["GET"])
def metadata():
    """Return agent metadata following A2A protocol."""
    log_debug("Received metadata request")
    return jsonify({
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "version": AGENT_VERSION,
        "endpoints": ["/task"]
    })


@app.route("/task", methods=["POST"])
def handle_task():
    """Handle A2A task request with optional session reuse and citations."""
    payload = request.json
    log_debug(f"Received task request: {json.dumps(payload, ensure_ascii=False)}")

    task_type = payload.get("type")
    input_data = payload.get("input", {})

    if task_type != "synthesis_expert":
        result = {"error": f"Unknown task type: {task_type}"}
        log_debug(f"Task result: {json.dumps(result, ensure_ascii=False)}")
        return jsonify(result)

    full_content = ""
    references: List[Dict[str, Any]] = []
    session_id = input_data.get("session_id")
    question = input_data.get("question", "")
    stream_response = input_data.get("stream", STREAM_RESPONSE)

    try:
        assistant = get_assistant()
        session = get_session(assistant, session_id)

        question_to_ask = question
        full_content, references, stream_error = ask_with_optional_stream(
            session,
            question_to_ask,
            stream_preferred=stream_response,
        )

        result = {
            "session_id": session.id,
            "answer": full_content,
        }
        if INCLUDE_REFERENCES:
            result["references"] = references
        if stream_error:
            result["warning"] = stream_error

    except Exception as e:  # noqa: BLE001
        log_debug(f"Error during processing: {e}\n{traceback.format_exc()}")
        result = {
            "error": {
                "message": str(e),
                "type": e.__class__.__name__,
            }
        }
        if session_id:
            result["session_id"] = session_id

    log_debug(f"Task result: {json.dumps(result, ensure_ascii=False)}")
    return jsonify(result)


if __name__ == "__main__":
    server_host = config["server"].get("host", "0.0.0.0")
    server_port = config["server"].get("port", 5001)
    if uvicorn and asgi_app:
        log_debug(f"Starting RAGAgent service (uvicorn, reload) on {server_host}:{server_port}")
        uvicorn.run("ReadingAgent.agent:asgi_app", host=server_host, port=server_port, reload=True)
    else:
        log_debug("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=server_host, port=server_port)
