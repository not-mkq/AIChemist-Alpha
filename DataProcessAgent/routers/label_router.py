from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
import json
import logging
import sqlite3
from labeler import set_label_for_file, label_all_projects, label_project

logger = logging.getLogger(__name__)

router = APIRouter()

class LabelRequest(BaseModel):
    project: str
    batch: str
    item: str
    filename: str
    label: str

@router.post("/set-label")
def set_label_endpoint(body: LabelRequest):
    """
    手动设置某个文件的 label：
    - label 必须出现在 config/label-config.json 中
    - 若合法：删除该文件原有所有 label，再写入新 label
    """
    try:
        set_label_for_file(
            project_name=body.project,
            batch_name=body.batch,
            item_name=body.item,
            filename=body.filename,
            label=body.label,
        )
        return {"status": "ok"}
    except sqlite3.IntegrityError as e:
        logger.error(f"设置标签失败（外键约束）: {e}")
        return JSONResponse(
            {"status": "error", "reason": "integrity_error", "detail": "Target file or label not found in database"},
            status_code=400
        )
    except Exception as e:
        logger.error(f"设置标签失败: {e}", exc_info=True)
        return JSONResponse(
            {"status": "error", "reason": "internal_error", "detail": str(e)},
            status_code=500
        )

@router.post("/relabel-all")
def relabel_all_endpoint():
    """为所有项目的文件重打标签（覆盖模式）。"""
    stats = label_all_projects()
    return {"status": "ok", **stats}

@router.post("/project/{project}/relabel")
def relabel_project_endpoint(project: str):
    """为指定项目的所有文件重打标签（覆盖模式）。"""
    stats = label_project(project)
    return {"status": "ok", "project": project, **stats}

@router.get("/labels")
def list_labels():
    """
    列出所有可用的标签（从 config/label-config.json 读取）。
    """
    label_config_path = Path("config/label-config.json")
    if not label_config_path.exists():
        return {"status": "error", "reason": "label_config_not_found"}
    
    with open(label_config_path, "r", encoding="utf-8") as f:
        labels = json.load(f)
    
    return {"status": "ok", **labels}
