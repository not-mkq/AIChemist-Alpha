from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from typing import Optional
from pathlib import Path
import tempfile
import zipfile
import shutil
import logging

from db import (
    get_connection,
    list_projects as db_list_projects,
    list_batches,
    list_items,
    list_files,
    list_batch_files,
    list_prj_files,
    list_file_labels,
    list_batch_file_labels,
    list_prj_file_labels,
)

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/projects")
def list_projects_endpoint():
    """
    列出所有项目名称。
    """
    conn = get_connection()
    try:
        projects = db_list_projects(conn)
        return {"projects": projects}
    finally:
        conn.close()

@router.get("/project/{project}/file-tree")
def get_project_file_tree(project: str):
    """
    获取项目的文件树结构。
    """
    conn = get_connection()
    try:
        batches_data = list_batches(conn, project)
        result = {"project": project, "batches": []}
        
        for batch_row in batches_data:
            batch_name = batch_row["name"]
            items_data = list_items(conn, project, batch_name)
            batch_info = {"batch_name": batch_name, "items": [], "batch_files": []}

            for bf in list_batch_files(conn, project, batch_name):
                batch_info["batch_files"].append({
                    "filename": bf["filename"],
                    "rel_path": bf["rel_path"],
                    "created_at": bf["created_at"],
                })

            for item_row in items_data:
                item_name = item_row["name"]
                files_data = list_files(conn, project, batch_name, item_name)
                item_info = {
                    "item_name": item_name,
                    "files": [
                        {"filename": f["filename"], "rel_path": f["rel_path"], "created_at": f["created_at"]}
                        for f in files_data
                    ],
                }
                batch_info["items"].append(item_info)
            result["batches"].append(batch_info)

        result["project_files"] = [
            {"filename": pf["filename"], "rel_path": pf["rel_path"], "created_at": pf["created_at"]}
            for pf in list_prj_files(conn, project)
        ]
        return result
    finally:
        conn.close()

@router.get("/project/{project}/export-zip")
def export_project_zip(project: str, background_tasks: BackgroundTasks):
    """
    将 workspace/<project> 目录压缩为 zip 供下载。
    """
    project_dir = Path("workspace") / project
    if not project_dir.exists() or not project_dir.is_dir():
        return JSONResponse(
            {"status": "error", "reason": "project_dir_not_found", "detail": f"{project_dir} missing"},
            status_code=404,
        )

    conn = get_connection()
    try:
        cur = conn.execute("SELECT 1 FROM projects WHERE name = ? LIMIT 1;", (project,))
        if not cur.fetchone():
            return JSONResponse(
                {"status": "error", "reason": "project_not_found", "detail": f"project '{project}' not in database"},
                status_code=404,
            )
    finally:
        conn.close()

    tmp_dir = Path(tempfile.mkdtemp(prefix="export_project_"))
    zip_path = tmp_dir / f"{project}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(project_dir, arcname=project)
            for path in sorted(project_dir.rglob("*")):
                arcname = Path(project) / path.relative_to(project_dir)
                if path.is_dir():
                    zf.write(path, arcname=str(arcname) + "/")
                else:
                    zf.write(path, arcname=arcname)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return JSONResponse(
            {"status": "error", "reason": "export_failed", "detail": str(e)},
            status_code=500,
        )

    background_tasks.add_task(shutil.rmtree, tmp_dir, ignore_errors=True)
    return FileResponse(zip_path, media_type="application/zip", filename=f"{project}.zip")

@router.get("/project/{project}/file-preview")
def get_project_file_preview(
    project: str,
    filename: str,
    batch: Optional[str] = None,
    item: Optional[str] = None,
    level: str = "item",
    mode: str = "meta",
):
    """
    获取文件预览或元数据。
    """
    project_root = Path("workspace") / project
    conn = get_connection()
    try:
        rel_path: Optional[Path] = None
        labels: list[str] = []

        if level == "item":
            cur = conn.execute(
                """
                SELECT rel_path FROM files
                WHERE project_name=? AND batch_name=? AND item_name=? AND filename=?
                """,
                (project, batch, item, filename),
            )
            row = cur.fetchone()
            if row and row["rel_path"]:
                rel_path = Path(row["rel_path"])
                labels = list_file_labels(conn, project, batch, item, filename)
        elif level == "batch":
            cur = conn.execute(
                """
                SELECT rel_path FROM batch_files
                WHERE project_name=? AND batch_name=? AND filename=?
                """,
                (project, batch, filename),
            )
            row = cur.fetchone()
            if row and row["rel_path"]:
                rel_path = Path(row["rel_path"])
                labels = list_batch_file_labels(conn, project, batch, filename)
        else:  # project level
            cur = conn.execute(
                """
                SELECT rel_path FROM prj_files
                WHERE project_name=? AND filename=?
                """,
                (project, filename),
            )
            row = cur.fetchone()
            if row and row["rel_path"]:
                rel_path = Path(row["rel_path"])
                labels = list_prj_file_labels(conn, project, filename)

        if rel_path is None:
            return JSONResponse(
                {"status": "error", "reason": "file_not_found", "detail": "path missing"},
                status_code=404,
            )

        file_path = project_root / rel_path
        if not file_path.exists() or not file_path.is_file():
            return JSONResponse(
                {"status": "error", "reason": "file_not_found", "detail": str(file_path)},
                status_code=404,
            )

        ext = file_path.suffix.lower().lstrip(".")
        stat = file_path.stat()
        meta = {
            "status": "ok",
            "project": project,
            "batch": batch,
            "item": item,
            "filename": filename,
            "rel_path": str(rel_path),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "kind": "meta",
            "labels": labels,
            "level": level,
        }

        import base64
        import json
        text_types = {"txt", "csv", "json", "md"}
        image_types = {"png", "jpg", "jpeg"}

        if mode == "content":
            if ext in text_types:
                try:
                    content = file_path.read_text(encoding="utf-8")
                except Exception:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                if ext == "json":
                    try:
                        parsed = json.loads(content)
                        content = json.dumps(parsed, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                meta.update({"kind": "text", "content": content})
            elif ext in image_types:
                data = file_path.read_bytes()
                b64 = base64.b64encode(data).decode("ascii")
                meta.update(
                    {"kind": "image", "content_base64": b64, "mime": f"image/{'jpeg' if ext in {'jpg','jpeg'} else 'png'}"}
                )
            else:
                return JSONResponse(
                    {"status": "error", "reason": "unsupported_preview_type", "detail": ext},
                    status_code=400,
                )

        return meta
    finally:
        conn.close()

@router.get("/project/{project}/file-download")
def download_project_file(
    project: str,
    filename: str,
    batch: Optional[str] = None,
    item: Optional[str] = None,
    level: str = "item",
):
    """
    下载文件。
    """
    project_root = Path("workspace") / project
    conn = get_connection()
    try:
        rel_path: Optional[Path] = None

        if level == "item":
            cur = conn.execute(
                """
                SELECT rel_path FROM files
                WHERE project_name=? AND batch_name=? AND item_name=? AND filename=?
                """,
                (project, batch, item, filename),
            )
            row = cur.fetchone()
            if row and row["rel_path"]:
                rel_path = Path(row["rel_path"])
        elif level == "batch":
            cur = conn.execute(
                """
                SELECT rel_path FROM batch_files
                WHERE project_name=? AND batch_name=? AND filename=?
                """,
                (project, batch, filename),
            )
            row = cur.fetchone()
            if row and row["rel_path"]:
                rel_path = Path(row["rel_path"])
        else:  # project level
            cur = conn.execute(
                """
                SELECT rel_path FROM prj_files
                WHERE project_name=? AND filename=?
                """,
                (project, filename),
            )
            row = cur.fetchone()
            if row and row["rel_path"]:
                rel_path = Path(row["rel_path"])

        if rel_path is None:
            return JSONResponse(
                {"status": "error", "reason": "file_not_found", "detail": "path missing"},
                status_code=404,
            )

        file_path = project_root / rel_path
        if not file_path.exists() or not file_path.is_file():
            return JSONResponse(
                {"status": "error", "reason": "file_not_found", "detail": str(file_path)},
                status_code=404,
            )

        return FileResponse(file_path, filename=filename)
    finally:
        conn.close()

from pydantic import BaseModel
from typing import Literal

class DeleteEntryRequest(BaseModel):
    target_type: Literal["item_file", "batch_file", "project_file", "item", "batch"]
    batch: Optional[str] = None
    item: Optional[str] = None
    filename: Optional[str] = None

def _delete_workspace_entry(project: str, rel_path: str, is_dir: bool = False):
    """
    内部辅助：物理删除 workspace 中的文件或目录。
    """
    from tool_runtime import WORKSPACE_ROOT
    target = Path(WORKSPACE_ROOT) / project / rel_path
    if not target.exists():
        return
    if is_dir and target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif not is_dir and target.is_file():
        target.unlink(missing_ok=True)

@router.post("/project/{project}/delete-entry")
def delete_project_entry(project: str, body: DeleteEntryRequest):
    """
    删除文件或文件夹，并清理数据库记录。
    """
    conn = get_connection()
    try:
        target = body.target_type
        if target == "item_file":
            if not (body.batch and body.item and body.filename):
                return JSONResponse({"status": "error", "reason": "missing_params"}, status_code=400)
            cur = conn.execute(
                """
                SELECT rel_path FROM files
                WHERE project_name=? AND batch_name=? AND item_name=? AND filename=?
                """,
                (project, body.batch, body.item, body.filename),
            )
            row = cur.fetchone()
            if row is None:
                return JSONResponse({"status": "error", "reason": "file_not_found"}, status_code=404)
            conn.execute(
                """
                DELETE FROM files
                WHERE project_name=? AND batch_name=? AND item_name=? AND filename=?
                """,
                (project, body.batch, body.item, body.filename),
            )
            rel_path = row["rel_path"]
            if rel_path:
                _delete_workspace_entry(project, rel_path, is_dir=False)
            conn.commit()
            return {"status": "ok", "deleted": "item_file"}

        if target == "batch_file":
            if not (body.batch and body.filename):
                return JSONResponse({"status": "error", "reason": "missing_params"}, status_code=400)
            cur = conn.execute(
                """
                SELECT rel_path FROM batch_files
                WHERE project_name=? AND batch_name=? AND filename=?
                """,
                (project, body.batch, body.filename),
            )
            row = cur.fetchone()
            if row is None:
                return JSONResponse({"status": "error", "reason": "file_not_found"}, status_code=404)
            conn.execute(
                """
                DELETE FROM batch_files
                WHERE project_name=? AND batch_name=? AND filename=?
                """,
                (project, body.batch, body.filename),
            )
            rel_path = row["rel_path"]
            if rel_path:
                _delete_workspace_entry(project, rel_path, is_dir=False)
            conn.commit()
            return {"status": "ok", "deleted": "batch_file"}

        if target == "project_file":
            if not body.filename:
                return JSONResponse({"status": "error", "reason": "missing_params"}, status_code=400)
            cur = conn.execute(
                """
                SELECT rel_path FROM prj_files
                WHERE project_name=? AND filename=?
                """,
                (project, body.filename),
            )
            row = cur.fetchone()
            if row is None:
                return JSONResponse({"status": "error", "reason": "file_not_found"}, status_code=404)
            conn.execute(
                """
                DELETE FROM prj_files
                WHERE project_name=? AND filename=?
                """,
                (project, body.filename),
            )
            rel_path = row["rel_path"]
            if rel_path:
                _delete_workspace_entry(project, rel_path, is_dir=False)
            conn.commit()
            return {"status": "ok", "deleted": "project_file"}

        if target == "item":
            if not (body.batch and body.item):
                return JSONResponse({"status": "error", "reason": "missing_params"}, status_code=400)
            cur = conn.execute(
                """
                SELECT 1 FROM items
                WHERE project_name=? AND batch_name=? AND name=?
                """,
                (project, body.batch, body.item),
            )
            if cur.fetchone() is None:
                return JSONResponse({"status": "error", "reason": "item_not_found"}, status_code=404)
            conn.execute(
                """
                DELETE FROM items
                WHERE project_name=? AND batch_name=? AND name=?
                """,
                (project, body.batch, body.item),
            )
            rel_path = str(Path(body.batch) / body.item)
            _delete_workspace_entry(project, rel_path, is_dir=True)
            conn.commit()
            return {"status": "ok", "deleted": "item"}

        if target == "batch":
            if not body.batch:
                return JSONResponse({"status": "error", "reason": "missing_params"}, status_code=400)
            cur = conn.execute(
                """
                SELECT 1 FROM batches
                WHERE project_name=? AND name=?
                """,
                (project, body.batch),
            )
            if cur.fetchone() is None:
                return JSONResponse({"status": "error", "reason": "batch_not_found"}, status_code=404)
            conn.execute(
                """
                DELETE FROM batches
                WHERE project_name=? AND name=?
                """,
                (project, body.batch),
            )
            _delete_workspace_entry(project, body.batch, is_dir=True)
            conn.commit()
            return {"status": "ok", "deleted": "batch"}

        return JSONResponse({"status": "error", "reason": "invalid_target"}, status_code=400)
    except Exception as e:
        conn.rollback()
        return JSONResponse({"status": "error", "reason": "delete_failed", "detail": str(e)}, status_code=500)
    finally:
        conn.close()

@router.get("/project/{project}/results")
def get_results(project: str, scope: str, batch: Optional[str] = None, item: Optional[str] = None):
    """
    获取 prj_results / batch_results / item_results 某行的结果键值。
    """
    scope = scope.lower()
    table_map = {
        "project": ("prj_results", "project_name"),
        "batch": ("batch_results", "project_name, batch_name"),
        "item": ("item_results", "project_name, batch_name, item_name"),
    }
    if scope not in table_map:
        return JSONResponse({"status": "error", "reason": "invalid_scope"}, status_code=400)

    table, key_cols = table_map[scope]
    if scope == "project":
        params = (project,)
        where = "project_name=?"
    elif scope == "batch":
        if not batch:
            return JSONResponse({"status": "error", "reason": "missing_batch"}, status_code=400)
        params = (project, batch)
        where = "project_name=? AND batch_name=?"
    else:
        if not batch or not item:
            return JSONResponse({"status": "error", "reason": "missing_item"}, status_code=400)
        params = (project, batch, item)
        where = "project_name=? AND batch_name=? AND item_name=?"

    conn = get_connection()
    try:
        cur = conn.execute(f"PRAGMA table_info({table});")
        cols = [r["name"] for r in cur.fetchall()]
        if not cols:
            return {"status": "ok", "entries": []}

        cur = conn.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 1;", params)
        row = cur.fetchone()
        if not row:
            return {"status": "ok", "entries": []}

        skip_keys = {"project_name", "batch_name", "item_name"}
        entries = [{"key": col, "value": row[col]} for col in cols if col not in skip_keys]
        return {"status": "ok", "entries": entries}
    finally:
        conn.close()

@router.get("/result-columns")
def list_result_columns():
    """
    返回结果表的列名（不含主键列）。
    """
    conn = get_connection()
    try:
        def _cols(table: str) -> list[str]:
            cur = conn.execute(f"PRAGMA table_info({table});")
            cols = [r["name"] for r in cur.fetchall()]
            return [c for c in cols if c not in {"project_name", "batch_name", "item_name"}]

        return {
            "status": "ok",
            "item": _cols("item_results"),
            "batch": _cols("batch_results"),
            "project": _cols("prj_results"),
        }
    finally:
        conn.close()

