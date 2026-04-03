import time
import json
import os
import sys
from typing import Optional, Tuple, Union
from pathlib import Path
from flask import Flask, request, jsonify
import requests

try:
    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware
except ImportError:
    uvicorn = None
    WSGIMiddleware = None

app = Flask(__name__)
asgi_app = WSGIMiddleware(app) if WSGIMiddleware else None

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AGENT_ID = "synthesis_robot"
AGENT_NAME = "synthesis_robot"
AGENT_DESCRIPTION = "A robotic agent that executes synthesis procedures"
AGENT_VERSION = "1.8.1"

AGENT_DIR = Path(__file__).resolve().parent
SAVE_DIR = str(AGENT_DIR / "steps")
COMPILED_DIR = str(AGENT_DIR / "compiled")
os.makedirs(SAVE_DIR, exist_ok=True)
os.makedirs(COMPILED_DIR, exist_ok=True)

FILES_ROOT = (Path(__file__).resolve().parent.parent / "files").resolve()
os.makedirs(FILES_ROOT, exist_ok=True)

try:
    from compile_workflow import compile_to_fixed
except Exception:
    compile_to_fixed = None


def log_debug(msg: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} DEBUG: {msg}")


RESULT_BASE_URL = os.getenv("RESULT_BASE_URL", "http://192.168.90.114:8018")
RESULT_AUTH_BEARER = os.getenv("RESULT_AUTH_BEARER", "")
RESULT_COOKIES = os.getenv("RESULT_COOKIES", "")

POST_COMPILE_URL = os.getenv(
    "POST_COMPILE_URL",
    "http://114.214.215.131:8018/manager/model-template/create-template",
)
POST_IDENTIFIES = os.getenv("POST_IDENTIFIES", "691c9f24af764bd6ac955a0e8dd0dba9")


def _now_ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def download_experiment_results(
    task_id: int,
    save_dir: str = FILES_ROOT,
    base_url: str = RESULT_BASE_URL,
    bearer: str = RESULT_AUTH_BEARER,
    raw_cookies: str = RESULT_COOKIES,
) -> Tuple[bool, str]:
    if not task_id:
        return False, "Missing taskId."
    os.makedirs(save_dir, exist_ok=True)

    url = f"{base_url.rstrip('/')}/worker/expr-result/instance/data"
    params = {"taskId": task_id}
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": f"synthesis_robot/{AGENT_VERSION}",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if bearer:
        headers["Authorization"] = bearer
    if raw_cookies:
        headers["Cookie"] = raw_cookies

    try:
        resp = requests.get(
            url, params=params, headers=headers, timeout=30, verify=False
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        if not isinstance(data, dict):
            return False, "Unexpected response JSON."

        fname = f"result_task_{task_id}_{_now_ts()}.json"
        fpath = os.path.join(FILES_ROOT, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, fname
    except Exception as e:
        return False, f"Exception: {e}"


def _wait_user_manual_artifact_name() -> str:
    print(f"Please put the result file/folder into:\n  {os.path.abspath(FILES_ROOT)}")
    while True:
        name = input(
            "Type the saved name (file or folder, under the shared files folder): "
        ).strip()
        if not name:
            print("Name cannot be empty.")
            continue
        base = os.path.basename(name)
        full_path = os.path.join(FILES_ROOT, base)
        if os.path.exists(full_path):
            return base
        print(
            f"Not found: {full_path}. Please ensure it exists, then re-enter the name."
        )


def interactive_result_download(task_id: Optional[int]) -> Tuple[bool, str]:
    if task_id is None:
        name = _wait_user_manual_artifact_name()
        print(f"[OK] Manual result collected: {name}")
        return True, name

    while True:
        ans = input("Has the experiment finished? (y/n): ").strip().lower()
        if ans in ("y", "yes"):
            break
        if ans in ("n", "no"):
            print("Okay, I'll wait. When it's done, type 'y' next time.")
            continue
        print("Please answer with 'y' or 'n'.")

    ok, name_or_err = download_experiment_results(task_id, save_dir=FILES_ROOT)
    if ok:
        print(f"[OK] Results downloaded: {name_or_err}")
        return True, name_or_err

    print(f"[WARN] Auto download failed: {name_or_err}")
    name = _wait_user_manual_artifact_name()
    print(f"[OK] Manual result collected: {name}")
    return True, name


def interactive_post_compiled(fixed_obj: dict) -> Tuple[bool, str, Optional[int]]:
    if not isinstance(fixed_obj, dict):
        return False, "No compiled JSON to post.", None
    while True:
        ans = input("Post compiled workflow to server? (yes/no): ").strip().lower()
        if ans in ("yes", "y"):
            break
        if ans in ("no", "n"):
            print("Skip posting.")
            return True, "Skipped by user.", None
        print("Please answer with 'yes' or 'no'.")

    url = POST_COMPILE_URL
    headers = {"Content-Type": "application/json", "identifies": POST_IDENTIFIES}
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(fixed_obj, ensure_ascii=False).encode("utf-8"),
            timeout=60,
            verify=False,
        )
        status = resp.status_code
        body = resp.text[:500]
        if 200 <= status < 300:
            print(f"[POST OK] HTTP {status}")
            return True, f"HTTP {status}: {body}", status
        else:
            print(f"[POST FAIL] HTTP {status}: {body}")
            return False, f"HTTP {status}: {body}", status
    except Exception as e:
        print(f"[POST EXCEPTION] {e}")
        return False, f"Exception: {e}", None


@app.route("/", methods=["GET"])
def metadata():
    log_debug("Received metadata request")
    return jsonify(
        {
            "id": AGENT_ID,
            "name": AGENT_NAME,
            "description": AGENT_DESCRIPTION,
            "version": AGENT_VERSION,
            "endpoints": ["/task"],
        }
    )


@app.route("/task", methods=["POST"])
def handle_task():
    payload = request.json or {}
    log_debug(f"Received task request: {json.dumps(payload, ensure_ascii=False)}")

    task_type = payload.get("type")
    steps = payload.get("input", {}).get("steps", [])

    task_id_raw: Optional[Union[str, int]] = (
        payload.get("taskId") or payload.get("id") or payload.get("task_id")
    )
    task_id: Optional[int] = None
    if isinstance(task_id_raw, int):
        task_id = task_id_raw
    elif isinstance(task_id_raw, str) and task_id_raw.isdigit():
        task_id = int(task_id_raw)

    if task_type != "synthesis_robot":
        return jsonify({"error": f"Unsupported task type: {task_type}"}), 400

    print("\n=== Executing synthesis task ===")
    for i, step in enumerate(steps):
        print(f"\n--- Step {i + 1} ---")
        print(json.dumps(step, indent=2, ensure_ascii=False))
    print("\n=== Execution completed ===")

    ts = _now_ts()
    simple_path = os.path.join(SAVE_DIR, f"steps_{ts}.json")
    with open(simple_path, "w", encoding="utf-8") as f:
        json.dump(steps, f, ensure_ascii=False, indent=2)
    log_debug(f"Saved simplified steps to {simple_path}")

    fixed = None
    if compile_to_fixed:
        csv_path = None
        for st in steps:
            if st.get("workstation_id") == "solution-preparation":
                ratio = (st.get("parameters") or {}).get("ratio_table")
                if ratio:
                    p1 = os.path.join(FILES_ROOT, ratio)
                    p2 = ratio
                    if os.path.isfile(p1):
                        csv_path = p1
                    elif os.path.isfile(p2):
                        csv_path = p2
                break
        try:
            workflow_obj = {"type": task_type, "input": {"steps": steps}}
            fixed = (
                compile_to_fixed(workflow_obj, csv_path)
                if csv_path
                else compile_to_fixed(workflow_obj, None)
            )
            compiled_path = os.path.join(COMPILED_DIR, f"compiled_{ts}.json")
            with open(compiled_path, "w", encoding="utf-8") as f:
                json.dump(fixed, f, ensure_ascii=False, indent=2)
            log_debug(f"Saved compiled workflow to {compiled_path}")
        except Exception as e:
            log_debug(f"Compile step skipped due to error: {e}")

    if fixed is not None:
        _ = interactive_post_compiled(fixed)
    else:
        print("[POST] Skipped (no compiled JSON).")

    if task_id is None:
        while True:
            ans = (
                input(
                    "No taskId provided. Enter taskId (digits) or type 'no' to skip auto-download: "
                )
                .strip()
                .lower()
            )
            if ans == "no":
                task_id = None
                break
            if ans.isdigit():
                task_id = int(ans)
                break
            print("Please enter digits for taskId or 'no'.")

    print("\n=== Result Phase (CLI) ===")
    if task_id is None:
        ok, name = interactive_result_download(None)
    else:
        ok, name = interactive_result_download(task_id)

    return jsonify({"experiment_raw_data_saved_in_dir": name}), 200


if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5002
    if uvicorn and asgi_app:
        log_debug(f"Starting SynthesisAgent (uvicorn, reload) on {host}:{port}")
        uvicorn.run("SynthesisAgent.agent:asgi_app", host=host, port=port, reload=True)
    else:
        log_debug("Uvicorn not available, falling back to Flask built-in server")
        app.run(host=host, port=port)
