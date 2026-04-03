import sys
from pathlib import Path

# Ensure project root is importable when running as a script (for uvicorn reload).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Add ProtocolConverterAgent directory to path for build_kb import
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import time
import json
import traceback
import logging
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from flask import Flask, request, jsonify
from openai import OpenAI

try:
    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware
except ImportError:
    uvicorn = None
    WSGIMiddleware = None

from build_kb import OpenAICompatEmbedding, load_config

logger = logging.getLogger("protocol_converter")
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
logger.addHandler(_handler)


def log_debug(msg: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} DEBUG: {msg}")


def load_agent_config() -> Dict[str, Any]:
    config_path = Path(__file__).with_name("config.json")
    return load_config(config_path)


config = load_agent_config()
app = Flask(__name__)

# Agent Metadata
AGENT_ID = config.get("agent", {}).get("id", "protocol_converter")
AGENT_NAME = config.get("agent", {}).get("name", "protocol_converter")
AGENT_DESCRIPTION = config.get("agent", {}).get("description", "Convert manual experimental steps to automated workflow steps")
AGENT_VERSION = config.get("agent", {}).get("version", "1.0")

# Initialize clients and collection (lazy initialization)
_embedding_client: Optional[OpenAI] = None
_chat_client: Optional[OpenAI] = None
_collection: Optional[Any] = None

# Session management: session_id -> conversation history
_sessions: Dict[str, List[Dict[str, Any]]] = {}


# -------------------------
# Init helpers (from qa_app.py)
# -------------------------

def init_embedding(cfg):
    emb_cfg = cfg["local_embedding"]
    client = OpenAI(
        base_url=emb_cfg["base_url"],
        api_key=emb_cfg["api_key"],
    )
    model = emb_cfg["model"]
    return client, model


def init_chat(cfg):
    chat_cfg = cfg["remote_chat"]
    client = OpenAI(
        base_url=chat_cfg["base_url"],
        api_key=chat_cfg["api_key"],
    )
    model = chat_cfg["model"]
    return client, model



def init_collection(cfg, emb_client, emb_model):
    # 把相对路径转成相对于 AGENT_DIR 的绝对路径
    raw_db_path = cfg["db_path"]            # 比如 "chroma_db"
    db_path = str((AGENT_DIR / raw_db_path).resolve())

    col_name = cfg["collection_name"]

    chroma_client = chromadb.PersistentClient(path=db_path)
    embedding_fn = OpenAICompatEmbedding(emb_client, emb_model)

    try:
        collection = chroma_client.get_collection(
            name=col_name,
            embedding_function=embedding_fn,
        )
        log_debug(f"Using existing collection: {col_name} at {db_path} (count: {collection.count()})")
    except Exception:
        collection = chroma_client.create_collection(
            name=col_name,
            embedding_function=embedding_fn,
        )
        log_debug(f"Created new collection: {col_name} at {db_path}")

    return collection



def init_clients():
    global _embedding_client, _chat_client, _collection
    if _collection is not None:
        return

    _embedding_client, _ = init_embedding(config)
    _chat_client, _ = init_chat(config)
    _collection = init_collection(config, _embedding_client, config["local_embedding"]["model"])

    log_debug(
        f"Initialized ChromaDB collection: {config['collection_name']} "
        f"at {config['db_path']}, count={_collection.count()}"
    )


asgi_app = WSGIMiddleware(app) if WSGIMiddleware else None


# -------------------------
# Retrieval (from qa_app.py)
# -------------------------

def retrieve_docs(collection, query: str, top_k: int = 10) -> List[Tuple[str, dict, str]]:
    res = collection.query(query_texts=[query], n_results=top_k)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    ids = res["ids"][0]
    return list(zip(docs, metas, ids))


def summarize_hits(hits: List[Tuple[str, dict, str]], snippet_len: int = 200) -> str:
    """Turn search hits into a compact text the model can read."""
    lines = []
    for i, (doc, meta, doc_id) in enumerate(hits, start=1):
        path = meta.get("path", "") if isinstance(meta, dict) else ""
        snippet = doc[:snippet_len].replace("\n", " ")
        lines.append(
            f"[{i}] id={doc_id} path={path} snippet={snippet}"
        )
    return "\n".join(lines)


def build_context_for_model(hits: List[Tuple[str, dict, str]], snippet_len: int = 800) -> str:
    """A richer version used when we show the model some content."""
    parts = []
    for i, (doc, meta, doc_id) in enumerate(hits, start=1):
        path = meta.get("path", "") if isinstance(meta, dict) else ""
        snippet = doc[:snippet_len]
        parts.append(
            f"### Document {i}\n"
            f"ID: {doc_id}\n"
            f"Path: {path}\n"
            f"Content:\n{snippet}\n"
        )
    return "\n\n".join(parts)


# -------------------------
# Agent Core (from qa_app.py)
# -------------------------

AGENT_SYSTEM_PROMPT = """
You are a protocol converter agent that converts manual experimental steps into automated workflow steps for robotic synthesis workstations.

You have access to a vector-database search tool containing documentation about available workstations and their capabilities.

------------------------------------------------------------
AVAILABLE WORKSTATIONS & THEIR CAPABILITIES
------------------------------------------------------------

1. solution-preparation
- Can manipulate liquids according to a ratio_table CSV.
- The ONLY workstation that can open or close tube caps.
- Accepts open or closed tubes; outputs cap state exactly as specified.
- Cannot handle solids; all reagents must already be prepared as solutions.
- Tube volume limit: ≤ 25 mL added total.

2. centrifuge-purification
- Accepts CLOSED tubes only; outputs CLOSED tubes.
- Performs centrifugation up to 10,000 rpm.
- Removes supernatant or retains precipitate.
- Can perform 1–5 washing cycles using operator-provided solvent.

3. ultrasonic-treatment
- Accepts OPEN tubes only; outputs OPEN tubes.
- Performs ultrasonic mixing for a specified duration and power level.

4. oven-station
- Accepts CLOSED tubes only; outputs CLOSED tubes.
- Performs heating/drying at specified temperature and duration.

5. electrochemistry-station
- Accepts OPEN tubes only; outputs OPEN tubes.
- Assumes Nafion has been added and ultrasonic mixing is complete.
- Uses a fixed catalyst coating area of 1 cm².
- Runs pre-written electrochemical programs (CV/LSV/EIS/etc.).

------------------------------------------------------------
RETRIEVAL PROTOCOL
------------------------------------------------------------

ACTION 1 — "search"
Request retrieval from the manual.
JSON format:
{
"action": "search",
"query": "short English query",
"top_k": 10,
"reason": "why the search is needed"
}

ACTION 2 — "final_answer"
When enough evidence is retrieved, convert the manual steps to automated workflow.
JSON format:
{
"action": "final_answer",
"answer": {
  "steps": [
    {
      "step_id": 1,
      "workstation_id": "solution-preparation",
      "batch_time_s": 1800,
      "parameters": {...}
    }
  ]
},
"used_doc_ids": ["id1", "id2"],
"reason": "how the documents informed the conversion"
}

------------------------------------------------------------
MANDATORY RULES
------------------------------------------------------------
- Always search first when converting manual steps to understand workstation requirements.
- Never invent undocumented robot capabilities.
- Always enforce tube cap constraints.
- Keep queries short and focused.
- Return workflow steps in the exact format required by synthesis_robot agent.
- Stop and answer as soon as you have sufficient evidence.
""".strip()


def validate_action(action: dict) -> Tuple[bool, str]:
    """Validate the action schema for missing or extra fields."""
    if "action" not in action:
        return False, "Missing required field: 'action'"
    
    act = action["action"]
    # Base allowed keys
    allowed_base = {"action", "reason", "used_doc_ids"} 
    
    if act == "search":
        required = {"query"}
        allowed = allowed_base | required | {"top_k"}
        current_keys = set(action.keys())
        missing = required - current_keys
        extra = current_keys - allowed
        
        if missing:
            return False, f"Action 'search' missing fields: {list(missing)}"
        if extra:
            return False, f"Action 'search' contains extra fields: {list(extra)}"
            
    elif act == "final_answer":
        required = {"answer"}
        allowed = allowed_base | required
        current_keys = set(action.keys())
        missing = required - current_keys
        extra = current_keys - allowed
        
        if missing:
            return False, f"Action 'final_answer' missing fields: {list(missing)}"
        if extra:
            return False, f"Action 'final_answer' contains extra fields: {list(extra)}"
    else:
        return False, f"Unknown action: '{act}'. Must be 'search' or 'final_answer'"
        
    return True, ""


def parse_action(raw: str) -> dict:
    """Parse the JSON action returned by the model."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return json.loads(text)


def agent_once(chat_client: OpenAI, chat_model: str, messages: List[dict]) -> dict:
    """Call chat model once and parse the JSON action."""
    resp = chat_client.chat.completions.create(
        model=chat_model,
        messages=messages,
        temperature=0.2,
    )
    content = resp.choices[0].message.content
    return parse_action(content)


def get_or_create_session(session_id: Optional[str]) -> str:
    """Get existing session or create a new one. Returns session_id."""
    if session_id and session_id in _sessions:
        return session_id
    new_session_id = session_id or f"session_{int(time.time() * 1000)}"
    _sessions[new_session_id] = []
    return new_session_id


def run_agent_loop(
    chat_client: OpenAI,
    chat_model: str,
    collection,
    user_question: str,
    session_id: Optional[str] = None,
    max_steps: int = 10,
) -> Dict[str, Any]:
    """
    Multi-step RAG loop to convert manual steps to automated workflow.
    Works like ReadingAgent: maintains conversation history in the session.
    """
    active_session_id = get_or_create_session(session_id)
    
    # Build messages from session history + system prompt + new user question
    messages = []
    
    # Add system prompt (only once per session, at the beginning)
    if not _sessions[active_session_id]:
        messages.append({"role": "system", "content": AGENT_SYSTEM_PROMPT})
    else:
        # For existing sessions, restore all previous messages
        messages = _sessions[active_session_id].copy()
    
    # Add new user question
    user_message = {
        "role": "user",
        "content": user_question if _sessions[active_session_id] else (
            f"User request:\n{user_question}\n\n"
            "Convert the manual experimental steps into automated workflow steps. "
            "Decide your first action as JSON."
        )
    }
    messages.append(user_message)

    all_hits_for_context: List[Tuple[str, dict, str]] = []

    for step in range(1, max_steps + 1):
        log_debug(f"Agent step {step}")

        try:
            # Call model directly to get raw content for error handling
            resp = chat_client.chat.completions.create(
                model=chat_model,
                messages=messages,
                temperature=0.2,
            )
            raw_content = resp.choices[0].message.content
            
            # 1. Try to parse JSON
            try:
                action = parse_action(raw_content)
            except json.JSONDecodeError as e:
                err_msg = f"JSON parsing failed: {e}. Output was: {raw_content}"
                logger.warning(err_msg)
                # Feedback to model
                messages.append({"role": "assistant", "content": raw_content})
                messages.append({
                    "role": "system", 
                    "content": f"Error: Failed to parse JSON ({str(e)}). Please return ONLY valid JSON, no extra text."
                })
                continue
            
            # 2. Validate Schema (missing/extra fields)
            is_valid, val_err = validate_action(action)
            if not is_valid:
                logger.warning(f"Invalid action schema: {val_err}")
                messages.append({"role": "assistant", "content": raw_content})
                messages.append({
                    "role": "system", 
                    "content": f"Error: {val_err}. Please correct your JSON output."
                })
                continue

        except Exception as e:
            logger.error(f"Failed to call model or processing error: {e}")
            return {"error": f"Agent loop error: {e}"}

        act = action.get("action")
        log_debug(f"Model chose action: {json.dumps(action, ensure_ascii=False)}")

        if act == "search":
            query = action.get("query") or user_question
            top_k = int(action.get("top_k") or 10)

            hits = retrieve_docs(collection, query, top_k=top_k)
            all_hits_for_context.extend(hits)

            # Log hits
            logger.info(f"Search query: {query!r}, top_k={top_k}, {len(hits)} hits:")
            logger.info(summarize_hits(hits))

            # Build context text for the model
            context_text = build_context_for_model(hits)

            tool_result_msg = (
                f"Search results for query: {query!r}\n\n"
                f"{context_text}\n\n"
                "You may call 'search' again with a refined query, "
                "or call 'final_answer' if you have enough information."
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(action),
                }
            )
            messages.append(
                {
                    "role": "system",
                    "content": tool_result_msg,
                }
            )
            continue

        elif act == "final_answer":
            answer_obj = action.get("answer", {})
            
            if isinstance(answer_obj, str):
                try:
                    answer_obj = json.loads(answer_obj)
                except Exception:
                    answer_obj = {"steps": []}

            reason = action.get("reason", "").strip()
            used_doc_ids = action.get("used_doc_ids", [])

            logger.info("Final answer reason: " + reason)
            logger.info("Final answer used_doc_ids: " + json.dumps(used_doc_ids))

            # Add assistant's final answer to messages
            messages.append({
                "role": "assistant",
                "content": json.dumps(action),
            })
            
            # Update session history with complete conversation
            _sessions[active_session_id] = messages

            return {
                **answer_obj,
                "session_id": active_session_id,
            }

        else:
            logger.warning(f"Unknown action '{act}', stopping.")
            messages.append({
                "role": "assistant",
                "content": json.dumps({"error": f"Unknown action: {act}"}),
            })
            _sessions[active_session_id] = messages
            return {"error": f"Unknown action from agent: {act}", "session_id": active_session_id}

    # Max steps reached
    messages.append({
        "role": "assistant",
        "content": json.dumps({"error": "Max steps reached"}),
    })
    _sessions[active_session_id] = messages
    return {"error": "Max steps reached without final_answer", "session_id": active_session_id}


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
    """Handle A2A task request to convert manual steps to automated workflow."""
    payload = request.json
    log_debug(f"Received task request: {json.dumps(payload, ensure_ascii=False)}")

    task_type = payload.get("type")
    input_data = payload.get("input", {})

    if task_type != "protocol_converter":
        result = {"error": f"Unknown task type: {task_type}"}
        log_debug(f"Task result: {json.dumps(result, ensure_ascii=False)}")
        return jsonify(result)

    manual_steps = input_data.get("manual_steps", "")
    if not manual_steps:
        result = {"error": "manual_steps parameter is required"}
        log_debug(f"Task result: {json.dumps(result, ensure_ascii=False)}")
        return jsonify(result)

    session_id = input_data.get("session_id")

    try:
        init_clients()
        
        chat_model = config["remote_chat"]["model"]
        result = run_agent_loop(
            _chat_client,
            chat_model,
            _collection,
            manual_steps,
            session_id=session_id,
            max_steps=10,
        )

        if "error" in result:
            log_debug(f"Task result error: {result['error']}")
            return jsonify(result)

        log_debug(f"Task result: {json.dumps(result, ensure_ascii=False)}")
        return jsonify(result)

    except Exception as e:
        log_debug(f"Error during processing: {e}\n{traceback.format_exc()}")
        result = {
            "error": {
                "message": str(e),
                "type": e.__class__.__name__,
            }
        }
        return jsonify(result)


if __name__ == "__main__":
    server_host = config.get("server", {}).get("host", "0.0.0.0")
    server_port = config.get("server", {}).get("port", 5012)
    if uvicorn and asgi_app:
        log_debug(f"Starting ProtocolConverterAgent service (uvicorn, reload) on {server_host}:{server_port}")
        uvicorn.run("ProtocolConverterAgent.agent:asgi_app", host=server_host, port=server_port, reload=True)
    else:
        log_debug("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=server_host, port=server_port)
