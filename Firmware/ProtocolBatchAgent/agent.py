
import os
import sys
import json
import zipfile
import logging
import traceback
import threading
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from flask import Flask, request, jsonify

# Ensure project root is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime import should_enable_reload

BASE_DIR = Path(__file__).resolve().parent
CFG = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))

# =============================
# Agent Metadata
# =============================
AGENT_ID = "protocol_batch_agent"
AGENT_NAME = "szx_batch_processor"
AGENT_DESCRIPTION = "Sequentially executes SZX backend pipeline: upload, batch process, plot, and AI report."
AGENT_VERSION = "1.0"

# Config
BACKEND_URL = CFG.get("backend_url", "http://127.0.0.1:8001").rstrip("/")
PROJECT = CFG.get("project", "SZX")
FILES_ROOT = (ROOT / CFG.get("files_root", "files")).resolve()
COUNTER_FILE = BASE_DIR / CFG.get("counter_file", "batch_counter.txt")
_LOCK = threading.Lock()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# =============================
# Helpers
# =============================

def get_and_inc_counter() -> int:
    with _LOCK:
        if not COUNTER_FILE.exists():
            count = 0
        else:
            try:
                count = int(COUNTER_FILE.read_text().strip())
            except Exception:
                count = 0
        COUNTER_FILE.write_text(str(count + 1))
        return count

def zip_directory_contents(dir_path: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(dir_path):
            for file in files:
                fpath = Path(root) / file
                arcname = fpath.relative_to(dir_path)
                zf.write(fpath, arcname)

def run_tool(tool_name: str, batch_id: Optional[str], scope: str):
    url = f"{BACKEND_URL}/run-tool"
    payload = {
        "project": PROJECT,
        "tool": tool_name,
        "scope": scope
    }
    if batch_id:
        payload["batch"] = batch_id
    
    log.info(f"Running tool {tool_name} (scope={scope}, batch={batch_id})")
    resp = requests.post(url, json=payload, timeout=600)
    resp.raise_for_status()
    return resp.json()

def download_file(filename: str, level: str, batch_id: Optional[str] = None) -> bytes:
    url = f"{BACKEND_URL}/project/{PROJECT}/file-download"
    params = {"filename": filename, "level": level}
    if batch_id:
        params["batch"] = batch_id
    
    log.info(f"Downloading {filename} (level={level}, batch={batch_id})")
    resp = requests.get(url, params=params, timeout=120)
    resp.raise_for_status()
    return resp.content

# =============================
# API
# =============================

@app.route("/", methods=["GET"])
def metadata():
    return jsonify({
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "version": AGENT_VERSION,
        "endpoints": ["/task"]
    })

@app.route("/task", methods=["POST"])
def handle_task():
    """
    Input: { "type": "szx_process_batch", "input": { "dirname": "..." } }
    """
    payload = request.json or {}
    input_data = payload.get("input") or {}
    dirname = input_data.get("dirname")

    if not dirname:
        return jsonify({"error": "dirname is required"}), 400

    data_dir = FILES_ROOT / dirname
    if not data_dir.is_dir():
        return jsonify({"error": f"Directory not found: {data_dir}"}), 404

    try:
        # Step 0: Prepare Zip
        zip_path = FILES_ROOT / f"{dirname}_temp.zip"
        zip_directory_contents(data_dir, zip_path)
        
        # Step 1: Upload
        counter = get_and_inc_counter()
        batch_prefix = f"batch_{counter}"
        log.info(f"Step 1: Uploading with prefix {batch_prefix}")
        
        with open(zip_path, "rb") as f:
            files = {"files": (f"{dirname}.zip", f, "application/zip")}
            data = {
                "project": PROJECT,
                "upload_type": "batch",
                "batch_prefix": batch_prefix
            }
            resp = requests.post(f"{BACKEND_URL}/upload", data=data, files=files, timeout=300)
        
        resp.raise_for_status()
        batch_id = resp.json().get("batch")
        if not batch_id:
            return jsonify({"error": "Failed to get batch ID from upload response", "details": resp.json()}), 502
        
        log.info(f"Generated Batch ID: {batch_id}")

        # Step 2: Run M5-BatchProcess
        log.info("Step 2: M5-BatchProcess")
        run_tool("M5-BatchProcess", batch_id, "batch")

        # Step 3: Get Batch Report MD
        log.info("Step 3: Download Batch Report MD")
        batch_report_content = ""
        try:
            batch_md_bytes = download_file("Batch_Report_airpt.md", "batch", batch_id)
            batch_report_content = batch_md_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            log.warning(f"Failed to download batch report MD: {e}")

        # Step 4: Run M2-plot_batches
        log.info("Step 4: M2-plot_batches")
        run_tool("M2-plot_batches", None, "batch->project")

        # Step 5: Run M8-AI_PRJ_RPT
        log.info("Step 5: M8-AI_PRJ_RPT")
        run_tool("M8-AI_PRJ_RPT", None, "project")

        # Step 6: Get Final Result Files
        log.info("Step 6: Final Results")
        
        # 6.1 png
        png_bytes = download_file("rendered_points.png", "project")
        png_path = FILES_ROOT / "rendered_points.png"
        png_path.write_bytes(png_bytes)
        
        # 6.2 Project AI MD
        project_md_content = ""
        try:
            prj_md_bytes = download_file("rendered_points.md", "project")
            project_md_content = prj_md_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            log.warning(f"Failed to download project MD: {e}")

        # 6.3 Aggregated CSV (Batch level)
        csv_bytes = download_file("aggregated_results.csv", "batch", batch_id)
        temp_csv = FILES_ROOT / f"{batch_id}_raw.csv"
        temp_csv.write_bytes(csv_bytes)
        
        df = pd.read_csv(temp_csv)
        # Rename columns: Item -> Index, Potential(V)@10mA/cm2 -> Performance
        rename_map = {
            "Item": "Index",
            "Potential(V)@10mA/cm2": "Performance"
        }
        # Check if columns exist before renaming
        df = df.rename(columns=rename_map)
        
        if "Index" in df.columns and "Performance" in df.columns:
            df = df[["Index", "Performance"]]
            # Sort by Index
            try:
                # Try numeric sort if possible
                df["Index"] = pd.to_numeric(df["Index"], errors='ignore')
                df = df.sort_values(by="Index")
            except Exception:
                df = df.sort_values(by="Index")
        
        final_csv_name = f"{batch_id}.csv"
        final_csv_path = FILES_ROOT / final_csv_name
        df.to_csv(final_csv_path, index=False)
        
        # Cleanup temp files
        if zip_path.exists():
            os.remove(zip_path)
        if temp_csv.exists():
            os.remove(temp_csv)

        # Merge MD contents for AI
        combined_md = f"### Batch Report ({batch_id})\n\n{batch_report_content}\n\n### Project AI Analysis\n\n{project_md_content}"

        return jsonify({
            "status": "success",
            "batch_id": batch_id,
            "files_saved": ["rendered_points.png", final_csv_name],
            "report_content": combined_md,
            "message": f"Processed batch {batch_id}. PNG and CSV saved to workspace."
        })

    except Exception as e:
        log.error(f"Error in batch processing: {e}")
        log.error(traceback.format_exc())
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == "__main__":
    server_cfg = CFG.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = int(server_cfg.get("port", 5010))
    use_reload = should_enable_reload("protocol_batch")
    app.run(host=host, port=port, debug=use_reload)

if __name__ == "__main__":
    server_cfg = CFG.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = int(server_cfg.get("port", 5010))
    use_reload = should_enable_reload("protocol_batch")
    app.run(host=host, port=port, debug=use_reload)
