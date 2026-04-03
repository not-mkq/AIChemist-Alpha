
import os
import sys
import json
import zipfile
import logging
import traceback
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from flask import Flask, request, jsonify
from agent_runtime import should_enable_reload

try:
    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware
except ImportError:  # pragma: no cover - optional dependency at runtime
    uvicorn = None
    WSGIMiddleware = None

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
CFG = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))


def resolve_path(raw: str | None, base: Path) -> Path:
    """Resolve a path to absolute, using `base` when the input is relative."""
    if not raw:
        return base
    p = Path(raw)
    if not p.is_absolute():
        p = (base / raw).resolve()
    return p


# =============================
# Agent Metadata & Constants
# =============================
AGENT_ID = "data_processing_agent"
AGENT_NAME = "electrochem_data_agent"
AGENT_DESCRIPTION = "Zip a dataset directory, merge config, POST to processing server, and extract key results."
AGENT_VERSION = "1.2"

# Processing server endpoint
PROCESS_ENDPOINT = CFG.get("process_endpoint", "http://127.0.0.1:33231/api/v1/agent/messages")
BACKEND_PROVIDER = CFG.get("provider")  # e.g., "deepseek"
MESSAGE_TEMPLATE = CFG.get("message_template", "请分析压缩包并输出质量报告（数据集：{dirname}）")
parsed_endpoint = urlparse(PROCESS_ENDPOINT)
ENDPOINT_ORIGIN = f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}" if parsed_endpoint.scheme and parsed_endpoint.netloc else ""

# Working directory where datasets live
FILES_ROOT = resolve_path(CFG.get("files_root", "files"), REPO_ROOT)
WORKDIR = str(FILES_ROOT)
os.makedirs(WORKDIR, exist_ok=True)

# Default params file (implementation detail; tools.py 不提及)
DEFAULT_PARAMS_PATH = resolve_path(CFG.get("default_params_path", "para_default.json"), BASE_DIR)

# Flask app & logger
app = Flask(__name__)
asgi_app = WSGIMiddleware(app) if WSGIMiddleware else None

# Ensure project root is importable when running as a script (for uvicorn reload).
ROOT = REPO_ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REQUIRED_TOP_LEVEL_KEYS = [
    "lsv_enabled", "cv_enabled", "eis_enabled", "ecsa_enabled",
    "lsv_target_current", "potential_offset"
]


# =============================
# Helper Functions
# =============================
def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge dict b into dict a (copy), with b overriding."""
    if not isinstance(a, dict):
        a = {}
    result = json.loads(json.dumps(a))  # deep copy
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def zip_directory(dir_path: str, zip_path: str) -> str:
    """
    Zip all files under dir_path into zip_path.
    IMPORTANT: The top-level directory itself is NOT included; only its contents.
    If zip_path exists, overwrite.
    """
    if not os.path.isdir(dir_path):
        raise FileNotFoundError(f"Directory not found: {dir_path}")

    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(dir_path):
            for fname in files:
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, start=dir_path)  # no top-level folder
                zf.write(fpath, arcname=arcname)
    return zip_path


def read_default_params() -> Dict[str, Any]:
    if not os.path.exists(DEFAULT_PARAMS_PATH):
        log.info(f"[WARN] Default params file not found: {DEFAULT_PARAMS_PATH}, using empty defaults.")
        return {}
    with open(DEFAULT_PARAMS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_request_message(dirname: str) -> str:
    try:
        return MESSAGE_TEMPLATE.format(dirname=dirname)
    except Exception:
        return MESSAGE_TEMPLATE


def _is_agent_message_endpoint() -> bool:
    return "/agent/messages" in PROCESS_ENDPOINT


def post_to_processing_server(params_dict: Dict[str, Any], zip_file_path: str, dirname: str) -> requests.Response:
    """
    Send multipart/form-data to the processing backend.
    - Legacy `/process`: params + archive → binary zip response.
    - New `/agent/messages`: message + params + file (+ provider) → JSON with download URL.
    """
    params_str_pretty = json.dumps(params_dict, ensure_ascii=False, indent=2)
    log.info(f"[DEBUG] POST {PROCESS_ENDPOINT}")
    log.info(f"[DEBUG] Params JSON (merged):\n{params_str_pretty}")
    log.info(f"[DEBUG] Uploading archive: {zip_file_path} ({os.path.getsize(zip_file_path)} bytes)")

    with open(zip_file_path, "rb") as f:
        if _is_agent_message_endpoint():
            message = build_request_message(dirname)
            files = {
                "message": (None, message, "text/plain"),
                "params": (None, json.dumps(params_dict, ensure_ascii=False), "application/json"),
                "file": (os.path.basename(zip_file_path), f, "application/zip"),
            }
            if BACKEND_PROVIDER:
                files["provider"] = (None, BACKEND_PROVIDER)
        else:
            files = {
                "params": (None, json.dumps(params_dict, ensure_ascii=False), "application/json"),
                "archive": (os.path.basename(zip_file_path), f, "application/zip"),
            }
        resp = requests.post(PROCESS_ENDPOINT, files=files)

    log.info(f"[DEBUG] Response status: {resp.status_code}")
    preview = resp.text[:2000] if resp.text else "<binary>"
    log.info(f"[DEBUG] Response text preview:\n{preview}")
    resp.raise_for_status()
    return resp


def save_response_zip(resp: requests.Response, dest_zip_path: str) -> str:
    """Save response binary as ZIP to dest_zip_path (overwrite if exists)."""
    if os.path.exists(dest_zip_path):
        os.remove(dest_zip_path)
    with open(dest_zip_path, "wb") as f:
        f.write(resp.content)
    log.info(f"[DEBUG] Saved response ZIP to {dest_zip_path} ({len(resp.content)} bytes)")
    return dest_zip_path


def extract_csv_from_zip(zip_path: str, csv_name: str = "LSV_results.csv") -> pd.DataFrame:
    """
    Read a CSV (csv_name) from zip_path into DataFrame without extracting.
    Try exact name; else endswith matching (case-insensitive) for nested paths.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        target_name = None

        if csv_name in namelist:
            target_name = csv_name
        else:
            lower_csv = csv_name.replace("\\", "/").lower()
            for nm in namelist:
                if nm.replace("\\", "/").lower().endswith(lower_csv):
                    target_name = nm
                    break

        if not target_name:
            raise FileNotFoundError(f"CSV '{csv_name}' not found in zip: {zip_path}\nAvailable: {namelist}")

        with zf.open(target_name, "r") as f:
            df = pd.read_csv(f)
            log.info(f"[DEBUG] Loaded CSV '{target_name}' from zip: shape={df.shape}, columns={list(df.columns)}")
            return df


def parse_backend_json(resp: requests.Response) -> Optional[Dict[str, Any]]:
    """Best-effort parse JSON; return None if content is not valid JSON."""
    try:
        return resp.json()
    except ValueError:
        return None


def _pick_download_entry(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("download",):
        val = data.get(key)
        if isinstance(val, dict) and (val.get("url") or val.get("path")):
            return val
    pr = data.get("processing_result")
    if isinstance(pr, dict):
        val = pr.get("download")
        if isinstance(val, dict) and (val.get("url") or val.get("path")):
            return val
    return None


def resolve_download_url(entry: Dict[str, Any]) -> Optional[str]:
    raw = entry.get("url") or entry.get("path")
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return raw
    if ENDPOINT_ORIGIN:
        return urljoin(ENDPOINT_ORIGIN + "/", raw.lstrip("/"))
    return None


def download_result_zip(url: str, dest_zip_path: str) -> str:
    resp = requests.get(url)
    resp.raise_for_status()
    if os.path.exists(dest_zip_path):
        os.remove(dest_zip_path)
    with open(dest_zip_path, "wb") as f:
        f.write(resp.content)
    log.info(f"[STEP] Downloaded result ZIP to {dest_zip_path} ({len(resp.content)} bytes)")
    return dest_zip_path


def rename_and_select(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename column 0 -> Index, column 2 -> Performance; then select [Index, Performance].
    """
    if df.shape[1] < 3:
        raise ValueError(f"Expected at least 3 columns in results CSV, got {df.shape[1]}")
    cols = list(df.columns)
    cols[0] = "Index"
    cols[2] = "Performance"
    df = df.set_axis(cols, axis=1)
    out = df[["Index", "Performance"]].copy()
    log.info(f"[DEBUG] Renamed & selected columns -> {list(out.columns)}, shape={out.shape}")
    return out


# =============================
# API Endpoints
# =============================
@app.route("/", methods=["GET"])
def metadata():
    return jsonify({
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "version": AGENT_VERSION,
        "endpoints": ["/task"],
        "workdir": os.path.abspath(WORKDIR),
        "server_endpoint": PROCESS_ENDPOINT
    })


@app.route("/task", methods=["POST"])
def handle_task():
    """
    Accept JSON payload:
    {
      "type": "process_dataset",
      "input": {
        "dirname": "<目录名>",
        "lsv_enabled": true,
        "cv_enabled": true,
        "eis_enabled": false,
        "ecsa_enabled": false,
        "lsv_target_current": "10",
        "potential_offset": 0.0,
        "params": { ... 可选扩展 ... }
      }
    }
    """
    payload = request.json or {}
    log.info(f"Received task request: {json.dumps(payload, ensure_ascii=False)}")

    task_type = payload.get("type")
    input_data = payload.get("input") or {}

    try:
        if task_type != "process_dataset":
            return jsonify({"error": f"Unknown task type: {task_type}"}), 400

        dirname = input_data.get("dirname")
        if not dirname or not isinstance(dirname, str):
            return jsonify({"error": "Invalid 'dirname'"}), 400

        # —— 顶层必选参数校验 —— #
        missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in input_data]
        if missing:
            return jsonify({"error": f"Missing required top-level keys: {missing}"}), 400

        # 顶层必选参数（显式最高优先级）
        top_level_params = {k: input_data[k] for k in REQUIRED_TOP_LEVEL_KEYS}

        # 可选扩展参数
        extra_params = input_data.get("params") or {}

        # 默认参数（实现细节）
        default_params = read_default_params()

        # 合并：defaults → params → top-level
        merged_params = deep_merge(default_params, extra_params)
        merged_params = deep_merge(merged_params, top_level_params)

        # 数据目录与打包
        data_dir = os.path.abspath(os.path.join(WORKDIR, dirname))
        if not os.path.isdir(data_dir):
            return jsonify({"error": f"Directory not found: {data_dir}"}), 400

        # 1) 压缩为 <dirname>_rawdata.zip（不包含顶层目录）
        raw_zip = os.path.abspath(os.path.join(WORKDIR, f"{dirname}_rawdata.zip"))
        zip_directory(data_dir, raw_zip)
        log.info(f"[STEP] Zipped directory to {raw_zip}")

        # 2) POST 到处理服务器
        resp = post_to_processing_server(merged_params, raw_zip, dirname)

        backend_json = parse_backend_json(resp)
        agent_reply = backend_json.get("agent_reply") if isinstance(backend_json, dict) else None
        download_url = None
        if isinstance(backend_json, dict):
            entry = _pick_download_entry(backend_json)
            if entry:
                download_url = resolve_download_url(entry)

        # 3) 获取处理结果 ZIP（优先使用后端提供的 download URL，回退为直接响应二进制）
        result_zip = os.path.abspath(os.path.join(WORKDIR, f"{dirname}_result.zip"))
        zip_ready = False
        if download_url:
            download_result_zip(download_url, result_zip)
            zip_ready = True
        else:
            content_type = resp.headers.get("content-type", "").lower()
            if "zip" in content_type or resp.content[:2] == b"PK":
                save_response_zip(resp, result_zip)
                zip_ready = True

        if not zip_ready:
            return jsonify({"error": "后端返回 JSON，但未提供下载链接或可用的 ZIP 内容。", "backend_response": backend_json}), 502

        log.info(f"[STEP] Saved server response ZIP to {result_zip}")

        # 4) 读取并处理 LSV_results.csv（可被 merged_params['csv_filename'] 覆盖）
        csv_name = merged_params.get("csv_filename", "LSV_results.csv")
        df = extract_csv_from_zip(result_zip, csv_name=csv_name)

        # 5) 只保留 Index / Performance 两列并重命名
        out_df = rename_and_select(df)

        # 6) 保存为 <dirname>.csv
        out_csv_path = os.path.abspath(os.path.join(WORKDIR, f"{dirname}.csv"))
        out_df.to_csv(out_csv_path, index=False, encoding="utf-8")
        log.info(f"[STEP] Wrote summary CSV to {out_csv_path}")

        # 返回摘要（含后端 AI 报告摘要）
        summary = {
            "message": "Processing finished successfully.",
            "agent_reply": agent_reply,
            "steps": [
                f"Packed '{dirname}' directory → {os.path.basename(raw_zip)}",
                "Merged config: defaults → params → top-level",
                f"Posted to processing server ({'agent/messages' if _is_agent_message_endpoint() else 'process'})",
                f"Retrieved result ZIP via {'download URL' if download_url else 'response binary'} → {os.path.basename(result_zip)}",
                f"Read '{csv_name}' from result ZIP, renamed columns (0→Index, 2→Performance), wrote CSV",
                f"Exported summary CSV → {os.path.basename(out_csv_path)}"
            ]
        }
        return jsonify(summary)

    except requests.HTTPError as e:
        tb = traceback.format_exc(limit=3)
        return jsonify({
            "error": f"HTTP {e.response.status_code}",
            "response_text": e.response.text[:2000],
            "traceback": tb
        }), 502
    except Exception as e:
        tb = traceback.format_exc(limit=6)
        return jsonify({
            "error": f"{type(e).__name__}: {str(e)}",
            "traceback": tb
        }), 500


if __name__ == "__main__":
    server_cfg = CFG.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = int(server_cfg.get("port", 5009))
    cfg_reload = bool(server_cfg.get("debug", False))
    use_reload = should_enable_reload("data_processing", default=cfg_reload or True)
    if uvicorn and asgi_app:
        log.info(f"Starting Data Processing agent (uvicorn, reload={use_reload}) on {host}:{port}")
        uvicorn.run("DataProcessingAgent.agent:asgi_app", host=host, port=port, reload=use_reload)
    else:
        log.info("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=host, port=port, debug=use_reload)
