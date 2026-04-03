import pandas as pd
import json
from pathlib import Path
import matplotlib.colors as mcolors

from tool_runtime import (
    regist_tool,
    return_file,
)

def _is_color(val: str) -> bool:
    """判断字符串是否为合法颜色"""
    try:
        mcolors.to_rgba(val.strip())
        return True
    except ValueError:
        return False

def _parse_additional_columns(raw: any, num_files: int) -> dict[str, list[any]]:
    """解析自定义列配置"""
    if not raw:
        return {}
    
    # 如果已经是字典（从实例配置 JSON 传入）
    if isinstance(raw, dict):
        res = raw
    else:
        # 尝试解析 JSON 字符串
        try:
            res = json.loads(raw)
        except:
            # 尝试解析自定义格式: "Name1: v1,v2; Name2: v3,v4"
            res = {}
            blocks = [b.strip() for b in str(raw).split(";") if b.strip()]
            for block in blocks:
                if ":" not in block: continue
                name, vals_str = block.split(":", 1)
                vals = [v.strip() for v in vals_str.split(",") if v.strip()]
                res[name.strip()] = vals

    # 验证长度
    for name, vals in res.items():
        if len(vals) != num_files:
            raise ValueError(f"Custom column '{name}' has {len(vals)} values, but {num_files} files were provided.")
    
    return res

def csv_merge_with_metadata(
    tool_name: str,
    source_csvs: list[str] | str,
    metadata_list: str,
    new_col_name: str = "Metadata",
    filter_query: str = "",
    additional_columns: any = None,
    encoding: str = "utf-8",
) -> None:
    """
    合并多个 CSV 文件并根据标签或颜色列表新增一列。支持自定义多列。
    """
    if isinstance(source_csvs, str):
        source_csvs = [source_csvs]
    
    file_paths = [Path(p) for p in source_csvs]
    num_files = len(file_paths)
    
    if num_files == 0:
        raise ValueError("No input CSV files provided.")

    # 1. 解析元数据和自定义列
    meta_items = [item.strip() for item in metadata_list.split(",") if item.strip()]
    extra_cols = _parse_additional_columns(additional_columns, num_files)
    
    # 2. 确定主元数据值（支持颜色插值）
    all_colors = all(_is_color(item) for item in meta_items)
    final_values = []
    if all_colors:
        if len(meta_items) == num_files:
            final_values = meta_items
        elif len(meta_items) >= 2:
            cmap = mcolors.LinearSegmentedColormap.from_list("custom", meta_items)
            final_values = [mcolors.to_hex(cmap(i / (num_files - 1))) for i in range(num_files)]
        elif len(meta_items) == 1:
            final_values = meta_items * num_files
    else:
        if len(meta_items) != num_files:
            raise ValueError(f"Metadata count ({len(meta_items)}) != file count ({num_files}).")
        final_values = meta_items

    # 3. 读取、筛选并合并
    all_dfs = []
    for idx, path in enumerate(file_paths):
        if not path.exists():
            print(f"[WARN] File not found: {path}")
            continue
            
        try:
            df = pd.read_csv(path, encoding=encoding)
        except Exception as e:
            print(f"[WARN] Failed to read {path}: {e}")
            continue
            
        if df.empty: continue

        if filter_query:
            try:
                df = df.query(filter_query)
            except Exception as e:
                print(f"[WARN] Filter error in {path}: {e}")
                continue
        
        if df.empty: continue

        # 添加主元数据列
        df[new_col_name] = final_values[idx]
        
        # 添加自定义列
        for col_name, col_vals in extra_cols.items():
            df[col_name] = col_vals[idx]
            
        all_dfs.append(df)

    if not all_dfs:
        raise ValueError("No data found to merge after filtering.")

    merged_df = pd.concat(all_dfs, ignore_index=True)

    # 4. 保存输出
    out_name = "merged_data.csv"
    merged_df.to_csv(out_name, index=False, encoding="utf-8-sig")

    return_file(out_name)

regist_tool(csv_merge_with_metadata)
