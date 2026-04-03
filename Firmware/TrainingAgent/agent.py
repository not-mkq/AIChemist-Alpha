import os
import sys
import time
from typing import Optional

import pandas as pd
from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import JSONResponse

try:
    import uvicorn  # type: ignore
except ImportError:  # pragma: no cover - optional dependency at runtime
    uvicorn = None

# Support both `python -m TrainingAgent.agent` (preferred) and direct script execution.
try:
    from .utils import bayesian_optimization, theo_exp_pipeline
except ImportError:
    from utils import bayesian_optimization, theo_exp_pipeline

# =========================
# 基本信息
# =========================
AGENT_ID = "ml_training_agent"
AGENT_NAME = "ml_training_agent"
AGENT_DESCRIPTION = (
    "ML training agent that merges reagent ratio data with performance, "
    "prepares input CSV for ML pipeline, runs models locally, and returns text results. "
    "Both ratio CSV and performance CSV filenames must be provided by the caller."
)
AGENT_VERSION = "1.7-random"

# Use os.path.abspath to ensure absolute paths regardless of invocation method
CURRENT_FILE_PATH = os.path.abspath(__file__)
AGENT_DIR = os.path.dirname(CURRENT_FILE_PATH)  # e.g., .../TrainingAgent
PROJECT_ROOT = os.path.dirname(AGENT_DIR)       # e.g., .../Re-Re-MA

FILES_ROOT = os.path.join(PROJECT_ROOT, "files")
UPLOAD_DIR = FILES_ROOT
MODEL_DIR = os.path.join(PROJECT_ROOT, "models")

app = FastAPI(title=AGENT_NAME, version=AGENT_VERSION)

# Ensure project root is importable when running as a script (for uvicorn reload).
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# =========================
# 工具与日志
# =========================
def log_debug(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{ts} DEBUG: {msg}", flush=True)

# Log configured paths on startup
log_debug(f"PROJECT_ROOT: {PROJECT_ROOT}")
log_debug(f"UPLOAD_DIR:   {UPLOAD_DIR}")
log_debug(f"MODEL_DIR:    {MODEL_DIR}")


# =========================
# 元数据端点
# =========================
@app.get("/", response_class=JSONResponse)
def metadata():
    return {
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "version": AGENT_VERSION,
        "endpoints": ["/task"],
    }


# =========================
# ML管线核心
# =========================
def run_pipeline_core(
    df_ml_input: pd.DataFrame,
    iteration: int,
    use_theoretical: bool,
    theoretical_xlsx_path: str,
) -> pd.DataFrame:

    if df_ml_input.shape[1] < 2:
        raise ValueError("CSV must have at least 2 columns (metals + params).")

    data_x = df_ml_input.iloc[:, :-1].values
    data_y = df_ml_input.iloc[:, -1:].values

    mod = (data_x % 0.05)
    mx = mod.max()
    grid_step = 1 if 1e-8 < mx < 0.05 - 1e-8 else 5

    if not os.path.exists(theoretical_xlsx_path):
        raise ValueError(f"Theoretical XLSX not found: {theoretical_xlsx_path}")

    if use_theoretical:
        data_x_theo = pd.read_excel(theoretical_xlsx_path, sheet_name="metals").values
        data_y_theo = pd.read_excel(theoretical_xlsx_path, sheet_name="params").values
        models, norms = theo_exp_pipeline(
            iteration, [data_x, data_y], [data_x_theo, data_y_theo], MODEL_DIR
        )
    else:
        models, norms = theo_exp_pipeline(
            iteration, [data_x, data_y], model_saved_dir=MODEL_DIR
        )

    best = bayesian_optimization([data_x, data_y], models=models, norms=norms, grid_step=grid_step)
    if best is None and grid_step == 5:
        best = bayesian_optimization([data_x, data_y], models=models, norms=norms, grid_step=1)

    if best is None:
        raise RuntimeError("Bayesian optimization returned None for both grid steps.")

    return pd.DataFrame(best)


# =========================
# /task 主逻辑
# =========================
@app.post("/task", response_class=JSONResponse)
def handle_task(payload: dict = Body(...)):
    try:
        log_debug(f"Received task request: {payload}")
        input_data = (payload or {}).get("input", {})

        ratio_csv = input_data.get("ratio_percent_csv")
        performance_csv = input_data.get("performance_csv")
        theoretical_xlsx = input_data.get("theoretical_xlsx")
        iteration = int(input_data.get("iteration", 0))

        # === 检查必填字段 ===
        missing_params = []
        if not ratio_csv:
            missing_params.append("ratio_percent_csv")
        if not performance_csv:
            missing_params.append("performance_csv")
        if not theoretical_xlsx:
            missing_params.append("theoretical_xlsx")
        
        if missing_params:
            msg = f"Missing required input parameters: {', '.join(missing_params)}. Please check your input."
            raise HTTPException(status_code=400, detail=msg)

        # === 构造文件路径 ===
        ratio_csv_path = os.path.join(UPLOAD_DIR, ratio_csv)
        performance_csv_path = os.path.join(UPLOAD_DIR, performance_csv)
        theoretical_xlsx_path = os.path.join(UPLOAD_DIR, theoretical_xlsx)

        missing_files = []
        for p, name in [
            (ratio_csv_path, f"Ratio CSV ({ratio_csv})"),
            (performance_csv_path, f"Performance CSV ({performance_csv})"),
            (theoretical_xlsx_path, f"Theoretical XLSX ({theoretical_xlsx})"),
        ]:
            if not os.path.exists(p):
                missing_files.append(name)
        
        if missing_files:
            msg = (
                f"The following required files are missing in the workspace: {', '.join(missing_files)}. "
                "Please upload them using the File Agent before running the training task."
            )
            raise HTTPException(status_code=400, detail=msg)

        # === 读取 CSV ===
        try:
            df_ratio = pd.read_csv(ratio_csv_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read Ratio CSV '{ratio_csv}': {str(e)}")

        try:
            df_perf = pd.read_csv(performance_csv_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read Performance CSV '{performance_csv}': {str(e)}")

        if "Index" not in df_perf.columns:
            raise HTTPException(
                status_code=400, 
                detail=f"The Performance CSV '{performance_csv}' is missing the required 'Index' column. Please ensure it matches the ratio file structure."
            )
        
        # Check if ratio csv has Index (it should, usually)
        if "Index" not in df_ratio.columns:
             pass

        df_ratio["Index"] = df_perf["Index"]
        df_merged = pd.merge(df_ratio, df_perf, on="Index").drop(columns=["Index"], errors="ignore")
        
        if df_merged.empty:
             raise HTTPException(status_code=400, detail="Merged dataset is empty. Please check if the inputs have matching data.")

        ratio_columns = [c for c in df_ratio.columns if c != "Index"]
        performance_col: Optional[str] = (
            "Performance" if "Performance" in df_merged.columns else df_merged.columns[-1]
        )

        # 生成 ML 输入
        df_ml_input = df_merged.copy()
        for col in df_ml_input.columns:
            if col != performance_col:
                try:
                    df_ml_input[col] = pd.to_numeric(df_ml_input[col]) / 100.0
                except ValueError:
                     raise HTTPException(status_code=400, detail=f"Column '{col}' in merged data contains non-numeric values. Please ensure ratio data is numeric.")

        # 基于 performance_csv 生成文件名
        name = os.path.splitext(performance_csv)[0]

        # 审计输入（无表头）
        tmp_csv_name = f"ml_input_{name}.csv"
        tmp_csv_path = os.path.join(UPLOAD_DIR, tmp_csv_name)
        df_ml_input.to_csv(tmp_csv_path, index=False, header=False)

        use_theoretical = (iteration == 0)

        try:
            df_best = run_pipeline_core(
                df_ml_input=df_ml_input,
                iteration=iteration,
                use_theoretical=use_theoretical,
                theoretical_xlsx_path=theoretical_xlsx_path,
            )
        except Exception as e:
             raise HTTPException(status_code=500, detail=f"ML Pipeline Execution Failed: {str(e)}")


        log_debug("Local ML pipeline finished.")

        ml_result_df = (df_best * 100).round(0).astype(int)
        if len(ratio_columns) != ml_result_df.shape[1]:
            ratio_columns = [f"Ratio_{i}" for i in range(ml_result_df.shape[1])]
            log_debug("Ratio column count mismatch; using fallback names.")
        ml_result_df.columns = ratio_columns

        output_filename = f"predict_percent_{name}.csv"
        output_path = os.path.join(UPLOAD_DIR, output_filename)
        ml_result_df.to_csv(output_path, index=False)

        return {
            "status": "success",
            "ml_result_percent_csv": output_filename,
            "used_file": tmp_csv_name,
            "iteration": iteration,
            "use_theoretical": use_theoretical,
        }

    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Error in /task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# 启动入口
# =========================
if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5007
    if uvicorn is None:
        raise SystemExit("uvicorn is required to run MLTrainingAgent.")
    log_debug("Starting MLTrainingAgent (randomized) on port 5007 via uvicorn --reload")
    uvicorn.run("TrainingAgent.agent:app", host=host, port=port, reload=True)
