import uuid
import itertools
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

AGENT_ID = "ratio_generator"
AGENT_NAME = "ratio_generator"
AGENT_DESCRIPTION = (
    "Generates reagent ratio tables in mL based on fixed volume (50mL). "
    "Supports full grid or random sampling. Also allows adding fixed-value reagent columns or creating a fixed-row template. "
    "Note: For safety, user should ensure no single reagent exceeds 20mL total (constraint not enforced automatically)."
)
AGENT_VERSION = "1.9"

FILES_ROOT = (Path(__file__).resolve().parent.parent / "files").resolve()
OUTPUT_DIR = str(FILES_ROOT)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def log_debug(msg):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} DEBUG: {msg}")

def generate_ratios(reagents, step, min_pct, max_pct, mode="full", sample_n=100, total_volume=50):
    """
    根据 reagents 列表生成所有满足百分比总和为 100% 的组合（以 step 为步长，从 min_pct 到 max_pct），
    再将百分比转换为 mL（基于 total_volume），并在最前面插入 Index 列。
    同时返回纯百分比表和体积表两个DataFrame。
    """
    values = list(range(min_pct, max_pct + 1, step))
    all_combinations = [combo for combo in itertools.product(values, repeat=len(reagents)) if sum(combo) == 100]
    #random.shuffle(all_combinations)
    if mode == "random":
        
        all_combinations = all_combinations[:sample_n]

    df_percent = pd.DataFrame(all_combinations, columns=reagents)
    df_ml = df_percent.copy(deep=True)
    df_percent.insert(0, "Index", range(0, len(df_percent)))

    
    for col in reagents:
        df_ml[col] = df_ml[col] * total_volume / 100
    df_ml.insert(0, "Index", range(0, len(df_ml)))

    return df_ml, df_percent

def create_empty_template(rows):
    """
    创建一个只有 Index 列的空模板，行数为 rows。
    """
    df = pd.DataFrame({"Index": list(range(0, rows))})
    return df

def add_fixed_reagent_column(df, reagent, value):
    """
    在 DataFrame df 上新增一列，列名为 reagent，所有行的值都为 value（mL）。
    """
    df[reagent] = value
    return df

ERROR_USAGE_MSG = (
    "Usage example:\n"
    "{\n"
    "  \"input\": {\n"
    "    \"steps\": [\n"
    "      {\n"
    "        \"action\": \"add_reagent\",\n"
    "        \"reagent\": \"HCl\",\n"
    "        \"value\": 5\n"
    "      },\n"
    "      {\n"
    "        \"action\": \"ratio\",\n"
    "        \"reagents\": [\"Co\", \"Ni\", \"Fe\"],\n"
    "        \"step\": 5,\n"
    "        \"min\": 5,\n"
    "        \"max\": 35,\n"
    "        \"sampling\": \"full\",\n"
    "        \"sample_n\": 100,\n"
    "        \"total_volume\": 50\n"
    "      },\n"
    "      {\n"
    "        \"action\": \"add_reagent\",\n"
    "        \"reagent\": \"Water\",\n"
    "        \"value\": 10\n"
    "      }\n"
    "    ],\n"
    "    \"rows\": 20  # Optional when no ratio step provided\n"
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
@app.route("/task", methods=["POST"])
def handle_task():
    try:
        payload = request.json
        log_debug(f"Received payload: {payload}")

        input_data = payload.get("input", {})
        steps = input_data.get("steps", [])
        default_rows = input_data.get("rows")  # optional when no ratio step

        if not isinstance(steps, list) or len(steps) == 0:
            raise ValueError("'steps' must be a non-empty list.")

        ratio_steps = [s for s in steps if s.get("action") == "ratio"]
        if len(ratio_steps) > 1:
            raise ValueError("Only one 'ratio' step is allowed.")

        df = None
        used_total_volume = 0
        row_count = None
        df_percent_filename = None

        file_id = str(uuid.uuid4())

        if ratio_steps:
            ratio = ratio_steps[0]

            percent_csv = ratio.get("percent_csv")
            total_volume = ratio.get("total_volume", 50)  # default 50 if not set

            if percent_csv:
                # 读取已有百分比CSV文件
                percent_filepath = os.path.join(OUTPUT_DIR, percent_csv)
                if not os.path.exists(percent_filepath):
                    raise FileNotFoundError(f"Percent CSV file not found: {percent_csv}")
                df_percent_temp = pd.read_csv(percent_filepath)
                if "Index" not in df_percent_temp.columns:
                    raise ValueError("Percent CSV missing 'Index' column.")
                reagents = [col for col in df_percent_temp.columns if col != "Index"]
                row_count = len(df_percent_temp)

                # 生成体积表
                df_ml_temp = df_percent_temp.copy()
                for col in reagents:
                    df_ml_temp[col] = df_ml_temp[col] * total_volume / 100
                df_ml_temp["Index"] = range(row_count)

                df_percent_filename = percent_csv
                used_total_volume = total_volume
            else:
                # 按之前参数生成
                reagents = ratio.get("reagents")
                step_pct = ratio.get("step")
                min_pct = ratio.get("min")
                max_pct = ratio.get("max")
                sample_n = ratio.get("sample_n", 100)
                mode = ratio.get("sampling", "full")

                if not isinstance(reagents, list) or len(reagents) == 0 or not isinstance(step_pct, int) or step_pct <= 0:
                    raise ValueError("Invalid parameters in 'ratio' step.")
                if not isinstance(min_pct, int) or not isinstance(max_pct, int) or min_pct < 0 or max_pct < min_pct:
                    raise ValueError("Invalid 'min'/'max' in 'ratio' step.")
                if mode == "random" and (not isinstance(sample_n, int) or sample_n <= 0):
                    raise ValueError("Invalid 'sample_n' for random sampling.")
                if not isinstance(total_volume, (int, float)) or total_volume <= 0:
                    raise ValueError("Invalid 'total_volume' in 'ratio' step.")


                df_ml_temp, df_percent_temp = generate_ratios(
                    reagents=reagents,
                    step=step_pct,
                    min_pct=min_pct,
                    max_pct=max_pct,
                    mode=mode,
                    sample_n=sample_n,
                    total_volume=total_volume
                )
                row_count = len(df_ml_temp)
                used_total_volume = total_volume

                # 保存百分比csv
                df_percent_filename = f"ratios_percent_{file_id}.csv"
                df_percent_filepath = os.path.join(OUTPUT_DIR, df_percent_filename)
                df_percent_temp.to_csv(df_percent_filepath, index=False)

        else:
            if default_rows is None or not isinstance(default_rows, int) or default_rows <= 0:
                raise ValueError("No 'ratio' step and 'rows' is invalid or missing.")
            row_count = default_rows

        df = create_empty_template(row_count)

        for step_item in steps:
            action = step_item.get("action")
            if action == "ratio":
                ratio_df = df_ml_temp.drop(columns=["Index"])
                df = pd.concat([df, ratio_df], axis=1)
            elif action == "add_reagent":
                reagent = step_item.get("reagent")
                value = step_item.get("value")
                if not reagent or not isinstance(value, (int, float)):
                    raise ValueError("Invalid 'add_reagent' parameters.")
                df = add_fixed_reagent_column(df, reagent, value)
                used_total_volume += value
            else:
                raise ValueError(f"Unsupported action: {action}")

        filename = f"ratios_{file_id}.csv"
        filepath = os.path.join(OUTPUT_DIR, filename)
        df.to_csv(filepath, index=False)

        result = {
            "status": "success",
            "filename": filename,
            "percent_filename": df_percent_filename,
            "rows": row_count,
            "columns": list(df.columns),
            "total_volume_per_row": used_total_volume
        }
        log_debug(f"Saved files: {filename}, percent file: {df_percent_filename}")
        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        log_debug(f"Error in handle_task: {error_msg}")
        return jsonify({"error": error_msg, "usage": ERROR_USAGE_MSG})

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5004
    if uvicorn and asgi_app:
        log_debug(f"Starting RatioAgent (uvicorn, reload) on {host}:{port}")
        uvicorn.run("RatioAgent.agent:asgi_app", host=host, port=port, reload=True)
    else:
        log_debug("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=host, port=port)
