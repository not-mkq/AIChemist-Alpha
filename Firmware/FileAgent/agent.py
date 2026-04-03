
import base64
import copy
import csv
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from flask import Flask, request, jsonify

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

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
AGENT_ID = "file_service_agent"
AGENT_NAME = "file_service"
AGENT_DESCRIPTION = (
    "Proxy/translator for file ops. Supports uploadAndValidate/write/read/list under the workspace; "
    "uploadAndValidate uses a blocking flow to coordinate user uploads via the frontend. "
    "Automatically probes files and returns tags/comments based on FileAgent/config.json rules."
)
AGENT_VERSION = "2.3"

# File storage path
FILE_DIR = (Path(__file__).resolve().parent.parent / "files").resolve()
FILE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory task registry: task_id -> task info (only for uploadAndValidate)
_TASKS: Dict[str, Dict[str, Any]] = {}
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
PRIVATE_WORKSPACE_ROOT = (Path(__file__).resolve().parent / ".private_workspace").resolve()
PRIVATE_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# Cache: filename -> {sha256, tags, comment}
_FILE_TAG_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log", ".py", ".toml", ".ini"}
MAX_PREVIEW_CHARS = 1200
MAX_LISTING = 30
DEFAULT_MODEL = "gpt-4o-mini"
AI_TIMEOUT_S = 12
LOG_LIMIT = 1600
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def log_debug(msg: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} DEBUG: {msg}")


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
    except Exception as exc:  # noqa: BLE001
        log_debug(f"Failed to build log config: {exc}")
        return None

def safe_path(filename: str) -> Path:
    """Prevent path traversal and ensure the target stays under FILE_DIR."""
    path = (FILE_DIR / filename).resolve()
    if not str(path).startswith(str(FILE_DIR)):
        raise ValueError("Invalid filename: outside workspace.")
    return path

def load_rule_config() -> Dict[str, Any]:
    """Load user-defined tagging rules from config.json if present."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        return {"rules": []}
    except Exception as exc:  # noqa: BLE001
        log_debug(f"Failed to load config.json: {exc}")
    return {"rules": []}

def build_ai_client(cfg: Dict[str, Any]) -> Optional["OpenAI"]:
    """Create an OpenAI client using env or config overrides."""
    if OpenAI is None:
        return None
    openai_cfg = cfg.get("openai") or {}
    api_key = openai_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = openai_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")
    try:
        if base_url:
            return OpenAI(api_key=api_key, base_url=base_url)
        return OpenAI(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        log_debug(f"Failed to init OpenAI client: {exc}")
        return None

def run_command(cmd: List[str]) -> str:
    """Run a shell command and return combined output (best effort)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
        output = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        return output if output else err
    except FileNotFoundError:
        return ""
    except Exception as exc:  # noqa: BLE001
        log_debug(f"Command failed {cmd}: {exc}")
        return ""

def compute_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def compute_dir_digest(dir_path: Path) -> str:
    """Compute a stable digest for a directory based on immediate child names (non-recursive)."""
    entries = sorted(
        [p.name + ("/" if p.is_dir() else "") for p in dir_path.iterdir()]
    )
    sha256 = hashlib.sha256()
    sha256.update("\n".join(entries).encode("utf-8"))
    return sha256.hexdigest()

def _truncate(text: str, limit: int = LOG_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "... [truncated]"

def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"

def _clean_comment(text: str, limit: int = 280) -> str:
    cleaned = " ".join((text or "").replace("\r", " ").replace("\n", " ").split())
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned

def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()

def _extract_json_snippet(text: str) -> str:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return match.group(0)
    return text

def detect_mime_type(file_path: Path) -> str:
    cmd_guess = run_command(["file", "-b", "--mime-type", str(file_path)])
    if cmd_guess:
        return cmd_guess
    guess, _ = mimetypes.guess_type(file_path.name)
    return guess or "application/octet-stream"

def image_to_data_url(path: Path, mime_type: str) -> str:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            log_debug(f"Image too large for inline send ({_format_bytes(len(raw))}); skipping attach.")
            return ""
        encoded = base64.b64encode(raw).decode("ascii")
        log_debug(f"Encoded image for AI send size={_format_bytes(len(raw))}")
        return f"data:{mime_type};base64,{encoded}"
    except Exception as exc:  # noqa: BLE001
        log_debug(f"Failed to encode image for AI: {exc}")
        return ""

def is_text_like(mime_type: str, path: Path) -> bool:
    if mime_type.startswith("text/"):
        return True
    return path.suffix.lower() in TEXT_EXTS

def extract_text_preview(path: Path) -> str:
    preview = run_command(["head", "-n", "40", str(path)])
    if preview:
        return preview[:MAX_PREVIEW_CHARS]
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""
    return data[:MAX_PREVIEW_CHARS]

def extract_archive_listing(path: Path, limit: int = MAX_LISTING) -> str:
    names: List[str] = []
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        except Exception as exc:  # noqa: BLE001
            return f"zip probe failed: {exc}"
    elif tarfile.is_tarfile(path):
        try:
            with tarfile.open(path) as tf:
                names = tf.getnames()
        except Exception as exc:  # noqa: BLE001
            return f"tar probe failed: {exc}"
    if not names and path.suffix.lower() in {".zip", ".jar"}:
        listing = run_command(["unzip", "-Z1", str(path)])
        if listing:
            names = listing.splitlines()
    if not names:
        return ""
    short = names[:limit]
    suffix = " ..." if len(names) > limit else ""
    return ", ".join(short) + suffix

def describe_image(path: Path) -> str:
    try:
        from PIL import Image  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        return ""
    try:
        with Image.open(path) as img:
            return f"image {img.format} {img.width}x{img.height} mode={img.mode}"
    except Exception as exc:  # noqa: BLE001
        return f"image probe failed: {exc}"

def collect_probe_outputs(temp_path: Path, mime_type: str) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    outputs["stat"] = f"{temp_path.stat().st_size} bytes"
    outputs["file_cmd"] = run_command(["file", "-b", str(temp_path)])
    if is_text_like(mime_type, temp_path):
        outputs["preview"] = extract_text_preview(temp_path)
    elif mime_type.startswith("image/"):
        img_desc = describe_image(temp_path)
        if img_desc:
            outputs["image"] = img_desc
    archive_listing = extract_archive_listing(temp_path)
    if archive_listing:
        outputs["archive"] = archive_listing
    if "preview" not in outputs and "archive" not in outputs and "image" not in outputs:
        binary_preview = run_command(["xxd", "-l", "256", str(temp_path)])
        if binary_preview:
            outputs["binary"] = binary_preview
    return outputs

def _tokenize_for_rule(text: str) -> List[str]:
    tokens = re.split(r"[^\w\u4e00-\u9fff]+", text.lower())
    return [tok for tok in tokens if len(tok) >= 2]

def evaluate_tags(context: str, rules: List[Dict[str, Any]]) -> List[str]:
    tags: List[str] = []
    ctx = (context or "").lower()
    for rule in rules:
        tag = str((rule or {}).get("tag") or "").strip()
        desc = str((rule or {}).get("description") or "").strip()
        if not tag:
            continue
        patterns = (rule or {}).get("patterns") or (rule or {}).get("pattern") or (rule or {}).get("regex")
        if isinstance(patterns, str):
            patterns = [patterns]
        keywords = (rule or {}).get("keywords") or (rule or {}).get("includes")
        if isinstance(keywords, str):
            keywords = [keywords]
        if not keywords:
            keywords = _tokenize_for_rule(desc)

        matched = False
        if patterns:
            for pat in patterns:
                try:
                    if re.search(str(pat), context, flags=re.IGNORECASE):
                        matched = True
                        break
                except re.error:
                    continue
        if matched:
            tags.append(tag)
            continue

        if desc and desc.lower() in ctx:
            tags.append(tag)
            continue

        if keywords:
            hits = sum(1 for kw in keywords if str(kw).lower() in ctx)
            need = 1 if len(keywords) <= 3 else max(2, len(keywords) // 2)
            if hits >= need:
                tags.append(tag)
    return sorted(set(tags))

def parse_ai_response(content: Any) -> Optional[Dict[str, Any]]:
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            elif item is not None:
                parts.append(str(item))
        text = " ".join(parts)
    elif isinstance(content, str):
        text = content
    else:
        text = str(content)
    cleaned = _strip_code_fence(text)
    candidates = [cleaned, _extract_json_snippet(cleaned)]
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            tags_raw = payload.get("tags") or []
            if isinstance(tags_raw, str):
                tags_raw = [tags_raw]
            tags = [str(t) for t in tags_raw if t]
            comment = payload.get("comment")
            comment_text = _clean_comment(str(comment)) if comment is not None else ""
            return {"tags": sorted(set(tags)), "comment": comment_text}
        except Exception:
            continue
    return None

def run_ai_annotation(
    temp_path: Path,
    mime_type: str,
    outputs: Dict[str, str],
    rules: List[Dict[str, Any]],
    rel_name: str,
    sha_value: str,
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    client = build_ai_client(cfg)
    if client is None:
        return None
    ai_cfg = cfg.get("openai") or {}
    model = ai_cfg.get("model") or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    rule_text = json.dumps(
        [{"description": r.get("description"), "tag": r.get("tag")} for r in rules if r.get("tag") and r.get("description")],
        ensure_ascii=False,
    )
    rule_tags = {str(r.get("tag")) for r in rules if r.get("tag")}
    text_parts: List[str] = [
        f"Target: {rel_name}",
        f"SHA256: {sha_value}",
        f"MIME: {mime_type}",
    ]

    if mime_type.startswith("image/"):
        text_parts.append(
            "Use the attached image to summarize visible content (objects/text/scenes). "
            "Prefer visual content over metadata."
        )
    elif mime_type == "inode/directory":
        text_parts.append(f"Listing (non-recursive):\n{outputs.get('dir_listing', '(empty directory)')}")
    else:
        text_parts.extend(
            [
                f"File probe: {outputs.get('file_cmd', '')}",
                f"Stat: {outputs.get('stat', '')}",
            ]
        )
        if outputs.get("archive"):
            text_parts.append(f"Archive listing: {outputs['archive']}")
        if outputs.get("preview"):
            text_parts.append(f"Text preview: {outputs['preview']}")
        if outputs.get("binary"):
            text_parts.append(f"Binary snippet: {outputs['binary']}")
        if outputs.get("image"):
            text_parts.append(f"Image summary: {outputs['image']}")

    text_parts.append(f"Rules (description->tag): {rule_text}")
    text_parts.append(
        "Return JSON only: {\"tags\": [tags_from_rules], \"comment\": \"<=280 chars describing the content\"}. "
        "Do not invent tags outside the provided list."
    )
    user_content: List[Dict[str, Any]] = [{"type": "text", "text": "\n".join([p for p in text_parts if p])}]

    if mime_type.startswith("image/"):
        try:
            data_url = image_to_data_url(temp_path, mime_type)
            if data_url:
                user_content.append({"type": "image_url", "image_url": {"url": data_url, "detail": "high"}})
            else:
                text_parts.append("Image not attached (size too large or encoding failed).")
        except Exception as exc:  # noqa: BLE001
            log_debug(f"Image attach failed: {exc}")

    system_prompt = (
        "You summarize files or directories and assign tags from given rules. "
        "Respond strictly with JSON containing keys 'tags' and 'comment'. "
        "Never create new tags outside the provided list."
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        log_debug("[AI] system=" + _truncate(system_prompt))
        log_debug("[AI] user=" + _truncate(json.dumps(user_content, ensure_ascii=False)))
    except Exception:
        pass

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=AI_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        log_debug(f"AI annotation failed: {exc}")
        return None

    message = resp.choices[0].message
    try:
        log_debug("[AI] response=" + _truncate(json.dumps(message.to_dict_recursive(), ensure_ascii=False)))  # type: ignore
    except Exception:
        pass

    parsed = parse_ai_response(getattr(message, "content", None))
    if parsed and parsed.get("tags"):
        parsed["tags"] = sorted(t for t in parsed["tags"] if t in rule_tags)
    return parsed

def build_comment(file_path: Path, mime_type: str, outputs: Dict[str, str], tags: List[str]) -> str:
    parts: List[str] = []
    descriptor = outputs.get("file_cmd") or mime_type
    parts.append(f"{file_path.name} ({descriptor})")
    if tags:
        parts.append(f"tags: {', '.join(tags)}")
    if outputs.get("image"):
        parts.append(outputs["image"])
    if outputs.get("archive"):
        parts.append(f"archive: {outputs['archive']}")
    if outputs.get("preview"):
        preview = outputs["preview"].replace("\n", " ")
        parts.append(f"preview: {preview[:MAX_PREVIEW_CHARS]}")
    if outputs.get("binary") and not outputs.get("preview"):
        binary = outputs["binary"].splitlines()
        parts.append(f"binary snippet: {' '.join(binary[:4])}")
    return _clean_comment(" | ".join(parts))

def analyze_file_for_annotations(filename: str, sha256: Optional[str] = None) -> Dict[str, Any]:
    file_path = safe_path(filename)
    rel_name = str(file_path.relative_to(FILE_DIR))
    sha_value = sha256 or compute_sha256(file_path)
    config = load_rule_config()
    rules = config.get("rules") or []
    workspace_cfg = config.get("private_workspace")
    workspace_root = PRIVATE_WORKSPACE_ROOT
    if isinstance(workspace_cfg, str) and workspace_cfg:
        workspace_root = (Path(__file__).resolve().parent / workspace_cfg).resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="probe_", dir=workspace_root) as tmpdir:
        temp_path = Path(tmpdir) / file_path.name
        shutil.copy2(file_path, temp_path)
        mime_type = detect_mime_type(temp_path)
        outputs = collect_probe_outputs(temp_path, mime_type)
        context_parts = [
            f"filename: {rel_name}",
            f"mime: {mime_type}",
            outputs.get("file_cmd", ""),
            outputs.get("preview", ""),
            outputs.get("archive", ""),
            outputs.get("image", ""),
        ]
        context = "\n".join(part for part in context_parts if part)
        ai_result = run_ai_annotation(temp_path, mime_type, outputs, rules, rel_name, sha_value, config) or {}
        tags = ai_result.get("tags") if isinstance(ai_result, dict) else None
        if not tags:
            tags = evaluate_tags(context, rules)
        comment = ai_result.get("comment") if isinstance(ai_result, dict) else None
        if not comment:
            comment = build_comment(file_path, mime_type, outputs, tags)

    tags = sorted(set(tags or []))
    comment = _clean_comment(comment or "")
    return {"filename": rel_name, "sha256": sha_value, "tags": tags, "comment": comment}


def analyze_directory_for_annotations(rel_name: str, dir_path: Path, sha256: str) -> Dict[str, Any]:
    """Generate annotations for a directory without recursive traversal."""
    config = load_rule_config()
    rules = config.get("rules") or []

    entries_all = sorted(p.name + ("/" if p.is_dir() else "") for p in dir_path.iterdir())
    truncated = False
    entries = entries_all
    if len(entries_all) > MAX_LISTING:
        entries = entries_all[:MAX_LISTING]
        truncated = True
    listing_text = "\n".join(entries) if entries else "(empty directory)"
    if truncated:
        listing_text += f"\n...[truncated {len(entries_all) - len(entries)} entries]"

    outputs: Dict[str, str] = {
        "stat": f"{len(entries_all)} items (truncated={truncated})",
        "file_cmd": run_command(["file", "-b", "--mime-type", str(dir_path)]),
        "dir_listing": listing_text,
    }
    ai_result = run_ai_annotation(dir_path, "inode/directory", outputs, rules, rel_name, sha256, config) or {}

    try:
        log_debug(f"[DIR AI] result for {rel_name}: {json.dumps(ai_result, ensure_ascii=False)}")
    except Exception:
        pass

    tags = ai_result.get("tags") if isinstance(ai_result, dict) else None
    if not tags:
        tags = evaluate_tags(listing_text, rules)
    comment = ai_result.get("comment") if isinstance(ai_result, dict) else None
    if not comment:
        count_info = f"{len(entries_all)} item(s)" + (" (truncated)" if truncated else "")
        comment = f"Directory with {count_info}: {', '.join(entries[:5])}"

    tags = sorted(set(tags or []))
    comment = _clean_comment(comment or "")
    return {"filename": rel_name, "sha256": sha256, "type": "directory", "tags": tags, "comment": comment}

def get_annotations(filename: str) -> Dict[str, Any]:
    file_path = safe_path(filename)
    rel_name = str(file_path.relative_to(FILE_DIR))
    if file_path.is_dir():
        sha_value = compute_dir_digest(file_path)
        with _CACHE_LOCK:
            cached = _FILE_TAG_CACHE.get(rel_name)
            if cached and cached.get("sha256") == sha_value:
                return cached
        annotations = analyze_directory_for_annotations(rel_name, file_path, sha_value)
        with _CACHE_LOCK:
            _FILE_TAG_CACHE[rel_name] = annotations
        return annotations
    sha_value = compute_sha256(file_path)
    with _CACHE_LOCK:
        cached = _FILE_TAG_CACHE.get(rel_name)
        if cached and cached.get("sha256") == sha_value:
            return cached
    annotations = analyze_file_for_annotations(rel_name, sha_value)
    with _CACHE_LOCK:
        _FILE_TAG_CACHE[rel_name] = annotations
    return annotations

def validate_upload(filename: str, rules: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    if not filename:
        return {"filename": "", "valid": False, "errors": ["filename is required for validation"]}

    try:
        file_path = safe_path(filename)
    except ValueError as exc:
        return {"filename": filename, "valid": False, "errors": [str(exc)]}

    if not file_path.exists():
        return {"filename": filename, "valid": False, "errors": [f"File '{filename}' not found."]}

    ext = file_path.suffix.lower().lstrip(".")
    allowed_exts = [str(x).lstrip(".").lower() for x in rules.get("allowed_extensions", []) if x]
    if allowed_exts and ext not in allowed_exts:
        errors.append(f"Extension '.{ext}' not allowed; expected one of: {', '.join(sorted(set(allowed_exts)))}")

    if ext == "csv":
        csv_headers = rules.get("csv_headers")
        min_rows = rules.get("csv_min_rows")
        max_rows = rules.get("csv_max_rows")
        min_cols = rules.get("csv_min_cols")
        max_cols = rules.get("csv_max_cols")

        try:
            with open(file_path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                try:
                    header = next(reader)
                except StopIteration:
                    header = []
                row_count = sum(1 for _ in reader)
        except Exception as exc:  # pragma: no cover - best effort validation
            errors.append(f"Failed to read CSV: {exc}")
            return {"filename": filename, "valid": False, "errors": errors}

        col_count = len(header)
        if csv_headers is not None and header != csv_headers:
            errors.append(f"Header mismatch. Expected {csv_headers}, got {header}")
        if min_cols is not None and col_count < min_cols:
            errors.append(f"Column count {col_count} < min_cols {min_cols}")
        if max_cols is not None and col_count > max_cols:
            errors.append(f"Column count {col_count} > max_cols {max_cols}")
        if min_rows is not None and row_count < min_rows:
            errors.append(f"Row count {row_count} < min_rows {min_rows}")
        if max_rows is not None and row_count > max_rows:
            errors.append(f"Row count {row_count} > max_rows {max_rows}")

    return {"filename": filename, "valid": not errors, "errors": errors}


@app.after_request
def add_cors_headers(response):
    # Allow frontend (Svelte dev server) to talk to this agent directly.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/", methods=["GET"])
def metadata():
    """Return agent metadata following A2A protocol"""
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
    payload = request.json
    log_debug(f"Received task request: {json.dumps(payload, ensure_ascii=False)}")

    task_type = payload.get("type")
    input_data = payload.get("input", {}) or {}

    if task_type == "file_service":
        method = (input_data.get("method") or "").lower()
        filename = input_data.get("filename")
        content = input_data.get("content")
        validation_rules = input_data.get("validation") or {}
        session_id = payload.get("session_id")
        call_id = payload.get("call_id")
        user_filename = input_data.get("user_filename")
        desired_path = input_data.get("workspace_path") or input_data.get("filename")

        # 1) 交互式 uploadAndValidate：阻塞 /task，等待前端上传并由 agent 校验后一次性返回结果。
        if method == "uploadandvalidate":
            if not session_id or not call_id:
                result = {"error": "session_id and call_id are required for uploadAndValidate"}
            else:
                task_id = input_data.get("task_id") or f"task_{int(time.time() * 1000)}"
                wait_event: threading.Event = threading.Event()
                task: Dict[str, Any] = {
                    "task_id": task_id,
                    "session_id": session_id,
                    "call_id": call_id,
                    "method": "uploadAndValidate",
                    "filename": desired_path,
                    "user_filename": user_filename,
                    "validation": validation_rules,
                    "status": "pending",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                    "announced": False,
                    "wait_event": wait_event,
                    "result": None,
                }
                _TASKS[task_id] = task
                log_debug(f"Registered upload task {task_id} for session={session_id}, call_id={call_id}")

                waited = wait_event.wait(timeout=60 * 60)  # 最长等待 1 小时
                if not waited:
                    task["status"] = "timeout"
                    result = {
                        "task_id": task_id,
                        "error": "upload_timeout",
                        "message": "File upload/validation did not complete within timeout.",
                    }
                else:
                    result_obj = task.get("result") or {}
                    result = result_obj

        # 2) validate：对已经存在的 workspace 文件做一次同步校验。
        elif method == "validate":
            if not desired_path:
                result = {"error": "validate requires filename or workspace_path"}
            else:
                validation_res = validate_upload(desired_path, validation_rules)
                validation_res["user_filename"] = user_filename or filename or desired_path
                validation_res["workspace_path"] = desired_path
                validation_res["task_id"] = input_data.get("task_id")
                result = validation_res

        # 3) write：直接在 workspace 下写文件。
        elif method == "write":
            if not filename or content is None:
                result = {"error": "write requires filename and content"}
            else:
                try:
                    file_path = safe_path(filename)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    overwritten = file_path.exists()
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    result = {
                        "message": f"File '{filename}' saved successfully.",
                        "filename": filename,
                        "workspace_path": str(file_path.relative_to(FILE_DIR)),
                        "overwritten": overwritten,
                    }
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"write failed: {exc}"}

        # 4) read：读取 workspace 下的文本文件。
        elif method == "read":
            if not filename:
                result = {"error": "read requires filename"}
            else:
                try:
                    file_path = safe_path(filename)
                    if not file_path.exists():
                        result = {"error": f"File '{filename}' not found."}
                    else:
                        mime_type = detect_mime_type(file_path)
                        is_text = is_text_like(mime_type, file_path)
                        result = {
                            "filename": filename,
                            "workspace_path": str(file_path.relative_to(FILE_DIR)),
                            "mime_type": mime_type,
                        }
                        if is_text:
                            text = file_path.read_text(encoding="utf-8", errors="ignore")
                            result["content"] = text
                        else:
                            result["note"] = "Binary/image file; content omitted."
                        try:
                            annotations = get_annotations(filename)
                            result.update({
                                "tags": annotations.get("tags", []),
                                "comment": annotations.get("comment"),
                                "sha256": annotations.get("sha256"),
                            })
                        except Exception as exc:  # noqa: BLE001
                            log_debug(f"Annotation failed for read {filename}: {exc}")
                            result["annotation_error"] = str(exc)
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"read failed: {exc}"}

        # 5) list：列出 workspace 下所有文件。
        elif method == "list":
            entries = sorted(p.relative_to(FILE_DIR).as_posix() for p in FILE_DIR.iterdir())
            annotations: Dict[str, Any] = {}
            for rel_name in entries:
                try:
                    annotations[rel_name] = get_annotations(rel_name)
                except Exception as exc:  # noqa: BLE001
                    log_debug(f"Annotation failed for list {rel_name}: {exc}")
                    annotations[rel_name] = {"error": str(exc)}
            result = {"files": entries, "annotations": annotations}

        # 6) 未显式指定 method：直接报错，避免含糊推断。
        else:
            result = {"error": f"Unsupported method for file_service: {method or 'N/A'}"}
    else:
        result = {"error": f"Unknown task type: {task_type}"}

    log_debug(f"Task result: {json.dumps(result, ensure_ascii=False)}")
    return jsonify(result)


@app.route("/ui/tasks", methods=["GET"])
def list_ui_tasks():
    """前端轮询 file_agent 获取“请上传”任务（step 5）。只返回尚未下发过的任务，并标记为已下发。"""
    session_id = request.args.get("session_id")
    now = time.time()
    tasks: List[Dict[str, Any]] = []
    for task in _TASKS.values():
        if session_id and task.get("session_id") != session_id:
            continue
        if task.get("announced"):
            continue
        if task.get("status") != "pending":
            continue
        task["announced"] = True
        task["updated_at"] = now
        # 不暴露内部的 wait_event / result
        public = {k: v for k, v in task.items() if k not in ("wait_event", "result")}
        tasks.append(public)
    return jsonify({"tasks": tasks})


@app.route("/ui/tasks/<task_id>/uploaded", methods=["POST"])
def notify_uploaded(task_id: str):
    """前端在文件上传完成后通知 file_agent（step 8），由 agent 校验并唤醒等待中的 /task 调用（step 9）。"""
    task = _TASKS.get(task_id)
    if not task:
        return jsonify({"error": "task_not_found"}), 404

    payload = request.json or {}
    workspace_path = payload.get("workspace_path")
    user_filename = payload.get("user_filename") or task.get("user_filename")
    overwritten = bool(payload.get("overwritten"))

    # 校验文件
    rules = task.get("validation") or {}
    validation_res = validate_upload(workspace_path, rules)
    validation_res["user_filename"] = user_filename
    validation_res["workspace_path"] = workspace_path
    validation_res["task_id"] = task_id
    if overwritten:
        validation_res["warning"] = "Uploaded file overwrote an existing file."

    task["status"] = "done"
    task["updated_at"] = time.time()
    task["result"] = validation_res
    wait_event = task.get("wait_event")
    if isinstance(wait_event, threading.Event):
        wait_event.set()

    return jsonify({"result": validation_res})

if __name__ == "__main__":
    server_host = "0.0.0.0"
    server_port = 5003
    if uvicorn and asgi_app:
        # 使用 uvicorn + reload，便于本地开发时自动重载代码。
        log_debug(f"Starting FileService agent (uvicorn, reload) on {server_host}:{server_port}")
        log_config = build_uvicorn_log_config()
        uvicorn.run("FileAgent.agent:asgi_app", host=server_host, port=server_port, reload=True, log_config=log_config)
    else:
        log_debug("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=server_host, port=server_port)
