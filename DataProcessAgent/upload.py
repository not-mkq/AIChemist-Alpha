from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import os
import shutil
import tempfile
import uuid
import zipfile
import inspect
from functools import wraps

from db import (
    get_connection,
    init_db,
    create_project,
    create_batch,
    create_item,
    create_file,
)
from labeler import label_files_for_batch

app = FastAPI()

# =========================
# 全局 DB 连接 & 初始化
# =========================

# 简单版：整个进程共用一个 SQLite 连接
GLOBAL_CONN = get_connection()
init_db(GLOBAL_CONN)

# 工作区根目录，可以改成你的实际路径
WORKSPACE_ROOT = os.path.abspath("workspace")


# ========== 工具函数 ==========

def short_uuid() -> str:
    """生成一个短 UUID 字符串，用作后缀。"""
    return uuid.uuid4().hex[:8]


def ensure_dir(path: str) -> None:
    """确保目录存在。"""
    os.makedirs(path, exist_ok=True)


def secure_name(name: str) -> str:
    """
    非严格安全处理：只简单去掉路径分隔符，避免 ../ 之类。
    """
    return name.replace("/", "_").replace("\\", "_")


def make_db_wrapper(real_func):
    """
    给 db.py 里的函数套一层：
    - 自动注入 GLOBAL_CONN 作为第一个参数
    - 打印除 conn 之外的所有参数
    使用方式：
        db_create_batch(project_name=..., batch_name=..., upload_type=...)
    """
    sig = inspect.signature(real_func)

    @wraps(real_func)
    def inner(*args, **kwargs):
        # real_func 的签名一般是 (conn, project_name, ...)
        bound = sig.bind_partial(None, *args, **kwargs)
        bound.apply_defaults()

        # 打印除 conn 之外的参数
        log_args = {k: v for k, v in bound.arguments.items() if k != "conn"}
        print(f"[DB] {real_func.__name__}:", log_args)

        # 真正调用时，用 GLOBAL_CONN 作为 conn
        return real_func(GLOBAL_CONN, *args, **kwargs)

    return inner


# 包一层对外的 db_* 接口
db_create_project = make_db_wrapper(create_project)
db_create_batch = make_db_wrapper(create_batch)
db_create_item = make_db_wrapper(create_item)
db_create_file = make_db_wrapper(create_file)





# ========== FastAPI 生命周期：关闭时把连接关掉（可选） ==========

@app.on_event("shutdown")
def shutdown_event():
    print("[DB] closing GLOBAL_CONN")
    GLOBAL_CONN.close()


# ========== 核心上传逻辑 ==========

@app.post("/upload")
async def upload_data(
    project: str = Form(...),
    upload_type: str = Form(...),  # "batch" | "item" | "files"
    batch_prefix: str = Form("Batch"),
    item_prefix: str = Form("Item"),
    files: List[UploadFile] = File(...),
):
    """
    上传接口：
    - project: prj 名称（全局唯一）
    - upload_type: "batch" | "item" | "files"
    - batch_prefix, item_prefix: 前缀，可配置
    - files: 上传的文件
    """
    upload_type = upload_type.lower()
    if upload_type not in {"batch", "item", "files"}:
        raise HTTPException(status_code=400, detail="upload_type must be one of: batch, item, files")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    # 确保项目存在（INSERT OR IGNORE）
    db_create_project(name=project, description=None)

    # 准备临时目录
    tmp_root = tempfile.mkdtemp(prefix="upload_")
    print("[UPLOAD] temp root:", tmp_root)

    try:
        if upload_type in {"batch", "item"}:
            # 这两种我们期望是一个 zip
            if len(files) != 1:
                raise HTTPException(status_code=400, detail="batch/item upload expects exactly one file (zip)")
            uploaded_zip = files[0]
            if not uploaded_zip.filename.lower().endswith(".zip"):
                raise HTTPException(status_code=400, detail="batch/item upload expects a .zip file")

            tmp_zip_path = os.path.join(tmp_root, secure_name(uploaded_zip.filename))
            with open(tmp_zip_path, "wb") as f:
                content = await uploaded_zip.read()
                f.write(content)

            # 解压
            unzip_dir = os.path.join(tmp_root, "unzipped")
            ensure_dir(unzip_dir)
            with zipfile.ZipFile(tmp_zip_path, "r") as zf:
                zf.extractall(unzip_dir)

            # 分析解压后的结构
            result = handle_zip_upload(
                project_name=project,
                upload_type=upload_type,
                unzip_dir=unzip_dir,
                batch_prefix=batch_prefix,
                item_prefix=item_prefix,
            )
        else:
            # upload_type == "files"：多文件散装
            result = handle_files_upload(
                project_name=project,
                upload_type=upload_type,
                tmp_root=tmp_root,
                uploaded_files=files,
                batch_prefix=batch_prefix,
                item_prefix=item_prefix,
            )

        return JSONResponse(result)

    finally:
        # 清理临时目录
        shutil.rmtree(tmp_root, ignore_errors=True)


# ========== 处理 zip 的逻辑：对应 upload_type = batch / item ==========

def handle_zip_upload(
    project_name: str,
    upload_type: str,
    unzip_dir: str,
    batch_prefix: str,
    item_prefix: str,
):
    """
    处理 zip 上传后的逻辑：
    - upload_type="batch": zip 代表一个 batch (里面有多个 item 目录)
    - upload_type="item":  zip 代表一个 item (里面可能有一个目录，也可能是一堆文件)
    """
    # unzip_dir 下的第一层内容
    entries = os.listdir(unzip_dir)
    entries = [e for e in entries if not e.startswith("__MACOSX")]
    entries_paths = [os.path.join(unzip_dir, e) for e in entries]

    # ========== 决定 batch_name ==========
    # "batch" 模式，如果只有一个顶层目录，就用它当 base_name；否则用 batch_prefix
    if upload_type == "batch" and len(entries) == 1 and os.path.isdir(entries_paths[0]):
        batch_base_name = secure_name(entries[0])
        root_dir = entries_paths[0]
    else:
        batch_base_name = batch_prefix
        root_dir = unzip_dir  # 直接拿整个解压目录作为 root

    batch_name = f"{batch_base_name}-{short_uuid()}"
    batch_name = secure_name(batch_name)

    # 工作区目标目录：workspace/<project>/<batch>/
    batch_dir = os.path.join(WORKSPACE_ROOT, secure_name(project_name), batch_name)
    ensure_dir(batch_dir)

    # DB: 创建 batch
    db_create_batch(project_name=project_name, batch_name=batch_name, upload_type=upload_type)

    created_items = []

    if upload_type == "batch":
        # 视 root_dir 下每个一级子目录为一个 item
        item_entries = [
            e for e in os.listdir(root_dir)
            if os.path.isdir(os.path.join(root_dir, e))
        ]
        if not item_entries:
            raise HTTPException(status_code=400, detail="batch zip must contain at least one item directory")

        for item_entry in item_entries:
            item_src_dir = os.path.join(root_dir, item_entry)
            item_name = secure_name(item_entry)  # 直接用用户目录名
            item_dir = os.path.join(batch_dir, item_name)
            ensure_dir(item_dir)

            # 先在 DB 里创建 item（保证外键存在）
            db_create_item(
                project_name=project_name,
                batch_name=batch_name,
                item_name=item_name,
            )

            # 再拷贝 + 写 files
            copy_tree_flat(
                src_dir=item_src_dir,
                dst_dir=item_dir,
                project_name=project_name,
                batch_name=batch_name,
                item_name=item_name,
            )

            created_items.append(item_name)

    elif upload_type == "item":
        # item 模式：如果解压后只有一个目录，就用该目录名作为 item_name
        # 否则自动生成 item_name
        if len(entries) == 1 and os.path.isdir(entries_paths[0]):
            item_name = secure_name(entries[0])
            item_src_dir = entries_paths[0]
        else:
            item_name = f"{item_prefix}-{short_uuid()}"
            item_name = secure_name(item_name)
            item_src_dir = unzip_dir  # 所有内容算一个 item

        item_dir = os.path.join(batch_dir, item_name)
        ensure_dir(item_dir)

        # 先创建 item
        db_create_item(
            project_name=project_name,
            batch_name=batch_name,
            item_name=item_name,
        )

        # 再拷贝 + 写 files
        copy_tree_flat(
            src_dir=item_src_dir,
            dst_dir=item_dir,
            project_name=project_name,
            batch_name=batch_name,
            item_name=item_name,
        )

        created_items.append(item_name)

    # 打标签接口（只打印）
    label_files_for_batch(project_name, batch_name)

    return {
        "project": project_name,
        "batch": batch_name,
        "items": created_items,
    }


# ========== 处理散文件上传：upload_type = "files" ==========

def handle_files_upload(
    project_name: str,
    upload_type: str,
    tmp_root: str,
    uploaded_files: List[UploadFile],
    batch_prefix: str,
    item_prefix: str,
):
    """
    upload_type="files"：多个散文件，一次上传 = 一个 batch + 一个 item
    """
    batch_base_name = batch_prefix
    batch_name = f"{batch_base_name}-{short_uuid()}"
    batch_name = secure_name(batch_name)

    item_name = f"{item_prefix}-{short_uuid()}"
    item_name = secure_name(item_name)

    batch_dir = os.path.join(WORKSPACE_ROOT, secure_name(project_name), batch_name)
    item_dir = os.path.join(batch_dir, item_name)

    ensure_dir(item_dir)

    # DB: 创建 batch + item
    db_create_batch(project_name=project_name, batch_name=batch_name, upload_type=upload_type)
    db_create_item(project_name=project_name, batch_name=batch_name, item_name=item_name)

    for uf in uploaded_files:
        filename = secure_name(uf.filename)
        dst_path = os.path.join(item_dir, filename)

        with open(dst_path, "wb") as f:
            # 简单同步读
            content = uf.file.read()
            f.write(content)

        # rel_path: 从 project 根开始的相对路径
        rel_path = os.path.join(batch_name, item_name, filename)
        db_create_file(
            project_name=project_name,
            batch_name=batch_name,
            item_name=item_name,
            filename=filename,
            rel_path=rel_path,
        )

    # 打标签接口占位
    label_files_for_batch(project_name, batch_name)

    return {
        "project": project_name,
        "batch": batch_name,
        "items": [item_name],
    }


# ========== 文件拷贝工具：顺便调用 db_create_file ==========

def copy_tree_flat(
    src_dir: str,
    dst_dir: str,
    project_name: str,
    batch_name: str,
    item_name: str,
):
    """
    把 src_dir 下所有文件递归复制到 dst_dir 中，
    保持相对子目录结构，同时为每个文件调用 db_create_file。
    """
    for root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, src_dir)
        if rel_root == ".":
            rel_root = ""
        for fn in files:
            s_path = os.path.join(root, fn)
            safe_fn = secure_name(fn)

            # 在 dst 里对应的路径（保持子目录结构）
            if rel_root:
                target_subdir = os.path.join(dst_dir, rel_root)
            else:
                target_subdir = dst_dir
            ensure_dir(target_subdir)

            d_path = os.path.join(target_subdir, safe_fn)
            shutil.copy2(s_path, d_path)

            # 计算相对 project 根的路径:
            # workspace/<project>/<batch>/<item>/... -> rel_path 从 <batch>/ 开始
            rel_from_project = os.path.relpath(
                d_path,
                os.path.join(WORKSPACE_ROOT, secure_name(project_name)),
            )
            # 形如："<batch>/<item>/subdir/file"
            db_create_file(
                project_name=project_name,
                batch_name=batch_name,
                item_name=item_name,
                filename=safe_fn,
                rel_path=rel_from_project,
            )
