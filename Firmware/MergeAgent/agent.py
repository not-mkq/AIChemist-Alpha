
import sys
from pathlib import Path
import pandas as pd
from flask import Flask, request, jsonify
import time
import os

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

AGENT_ID = "merge_csv_agent"
AGENT_NAME = "merge_csv_agent"
AGENT_DESCRIPTION = (
    "Merges multiple CSV files given by their filenames into a single CSV. "
    "All CSVs must have identical headers; otherwise, returns an error. "
    "Removes duplicate rows and can limit the output to a specified number of data rows."
)
AGENT_VERSION = "1.1"

FILES_ROOT = (Path(__file__).resolve().parent.parent / "files").resolve()
INPUT_DIR = str(FILES_ROOT)
OUTPUT_DIR = str(FILES_ROOT)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def log_debug(msg):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} DEBUG: {msg}")

ERROR_USAGE_MSG = (
    "Usage example:\n"
    "{\n"
    "  \"input\": {\n"
    "    \"csv_files\": [\"file1.csv\", \"file2.csv\"],\n"
    "    \"line_num\": 100\n"
    "  }\n"
    "}"
)

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
    try:
        payload = request.json
        log_debug(f"Received payload: {payload}")

        input_data = payload.get("input", {})
        csv_files = input_data.get("csv_files", [])
        line_num = input_data.get("line_num", None)

        if not isinstance(csv_files, list) or len(csv_files) == 0:
            raise ValueError("'csv_files' must be a non-empty list.")

        if line_num is not None and (not isinstance(line_num, int) or line_num < 1):
            raise ValueError("'line_num' must be a positive integer if provided.")

        dfs = []
        expected_columns = None

        for filename in csv_files:
            filepath = os.path.join(INPUT_DIR, filename)
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"File not found: {filename}")

            df = pd.read_csv(filepath)

            if expected_columns is None:
                expected_columns = list(df.columns)
            else:
                if list(df.columns) != expected_columns:
                    raise ValueError(f"Header mismatch found in file: {filename}")

            dfs.append(df)

        # 合并
        merged_df = pd.concat(dfs, ignore_index=True)

        # 去重
        merged_df = merged_df.drop_duplicates()

        # 截断
        if line_num is not None:
            merged_df = merged_df.head(line_num)

        # —— 关键改动：合并后重新编号第一列 “Index” ——
        if len(merged_df.columns) > 0 and merged_df.columns[0] == "Index":
            merged_df["Index"] = range(len(merged_df))  # 0,1,2,...,N-1
            # 确保 Index 仍在第一列（防止列顺序意外变化）
            cols = merged_df.columns.tolist()
            cols.remove("Index")
            merged_df = merged_df[["Index"] + cols]
        # ——————————————————————————————

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        merged_filename = f"merged_{timestamp}.csv"
        merged_filepath = os.path.join(OUTPUT_DIR, merged_filename)
        merged_df.to_csv(merged_filepath, index=False)

        result = {
            "status": "success",
            "merged_filename": merged_filename,
            "rows": len(merged_df),
            "columns": list(merged_df.columns)
        }

        log_debug(f"Merged file saved: {merged_filename}, rows: {len(merged_df)}, columns: {list(merged_df.columns)}")
        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        log_debug(f"Error in handle_task: {error_msg}")
        return jsonify({"error": error_msg, "usage": ERROR_USAGE_MSG})

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5005
    if uvicorn and asgi_app:
        log_debug(f"Starting MergeCSVAgent (uvicorn, reload) on {host}:{port}")
        uvicorn.run("MergeAgent.agent:asgi_app", host=host, port=port, reload=True)
    else:
        log_debug("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=host, port=port)
