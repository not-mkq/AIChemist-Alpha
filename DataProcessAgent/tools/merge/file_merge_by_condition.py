import logging
import os
from pathlib import Path
from typing import List, Any, Optional

from merge_runtime import (
    regist_merge_tool,
    merge_return_file
)
from template_engine import render_template

logger = logging.getLogger(__name__)

def file_merge_by_condition(
    tool_name: str,
    source_files: List[str],
    
    # 5个可选的 Input Columns (对应 Result Column)
    col0: Optional[List[Any]] = None,
    col1: Optional[List[Any]] = None,
    col2: Optional[List[Any]] = None,
    col3: Optional[List[Any]] = None,
    col4: Optional[List[Any]] = None,
    
    # 参数
    title: str = "",
    condition: str = "True",
    file_header: str = "",
    separator: str = "\\n",
    output_name: str = "merged_output.txt",
    encoding: str = "utf-8"
) -> None:
    """
    根据 Python 表达式筛选并合并文件。
    """
    
    out_path = Path(output_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 建立全局上下文 (用于 title 渲染)
    # 获取第一个文件的 project/batch 作为默认全局信息
    global_p, global_b = "", ""
    if source_files:
        p = Path(source_files[0]).name.split("@")
        if len(p) >= 3:
            global_p, global_b = p[0], p[1]

    global_ctx = {
        "project": global_p, "Project": global_p,
        "batch": global_b, "Batch": global_b
    }

    # 初始化并写入 Title
    with open(out_path, "w", encoding=encoding) as f:
        if title:
            rendered_title = render_template(title, global_ctx)
            final_title = rendered_title.replace("\\n", "\n").replace("\\t", "\t")
            f.write(final_title + "\n")

    # 预处理数据列，确保是列表
    data_cols = [
        col0 if col0 is not None else [],
        col1 if col1 is not None else [],
        col2 if col2 is not None else [],
        col3 if col3 is not None else [],
        col4 if col4 is not None else []
    ]
    
    count = 0
    
    with open(out_path, "a", encoding=encoding) as outfile:
        for i, filepath_str in enumerate(source_files):
            file_path = Path(filepath_str)
            print(f"[DEBUG] Processing file: {filepath_str}")
            if not file_path.exists():
                logger.warning(f"File not found: {file_path}")
                continue

            # 1. 解析上下文 (根据 merge_runtime 命名规则)
            parts = file_path.name.split("@")
            print(f"[DEBUG] Filename parts: {parts}")
            ctx_project, ctx_batch, ctx_item = "", "", ""
            real_filename = file_path.name
            
            if len(parts) >= 4:
                ctx_project, ctx_batch, ctx_item = parts[0], parts[1], parts[2]
                real_filename = "@".join(parts[3:])
            elif len(parts) == 3:
                ctx_project, ctx_batch = parts[0], parts[1]
                real_filename = parts[2]
            
            print(f"[DEBUG] Parsed: prj={ctx_project}, batch={ctx_batch}, item={ctx_item}, file={real_filename}")

            # 获取对应的数值
            current_vals = [c[i] if i < len(c) else None for c in data_cols]

            # 构建上下文
            ctx = {
                "val": current_vals,
                "filename": real_filename,
                "project": ctx_project,
                "Project": ctx_project,
                "batch": ctx_batch,
                "Batch": ctx_batch,
                "item": ctx_item,
                "Item": ctx_item,
                "i": i
            }
            
            # 打平 val 列表以便模板引擎访问 (val_0, val_1, ...)
            for idx, v in enumerate(current_vals):
                ctx[f"val_{idx}"] = v
            
            # 2. 条件评估
            try:
                should_merge = eval(condition, {"__builtins__": {}}, ctx)
            except Exception as e:
                logger.error(f"Condition error for {file_path.name}: {e}")
                should_merge = False
            
            if not should_merge:
                continue
                
            # 3. 读取并合并
            try:
                content = file_path.read_text(encoding=encoding)
                
                # 写入分隔符
                if count > 0 and separator:
                    outfile.write(separator.replace("\\n", "\n").replace("\\t", "\t"))
                
                # 写入带变量替换和转义处理的 Header
                if file_header:
                    # 先替换变量，后替换换行符
                    rendered = render_template(file_header, ctx)
                    final_header = rendered.replace("\\n", "\n").replace("\\t", "\t")
                    outfile.write(final_header)
                
                outfile.write(content)
                count += 1
                
            except Exception as e:
                logger.error(f"Merge error for {file_path.name}: {e}")

    logger.info(f"Merged {count} files.")
    try:
        merge_return_file(output_name)
    except:
        pass

regist_merge_tool(file_merge_by_condition)