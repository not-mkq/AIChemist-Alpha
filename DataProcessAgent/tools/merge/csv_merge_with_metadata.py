import pandas as pd
from pathlib import Path
import matplotlib.colors as mcolors
from typing import List, Any, Optional

from merge_runtime import (
    regist_merge_tool,
    merge_return_file,
)

def _is_color(val: str) -> bool:
    try:
        mcolors.to_rgba(val.strip())
        return True
    except ValueError:
        return False

def csv_merge_with_metadata(
    tool_name: str,
    source_csvs: List[str],  # Merge 运行时会自动传入文件路径列表
    metadata_list: str,
    new_col_name: str = "Metadata",
    filter_query: str = "",
    
    # 仅支持一个来自结果列的输入向量
    extra_col_data: Optional[List[Any]] = None, 
    extra_col_name: str = "",
    
    encoding: str = "utf-8",
) -> None:
    """
    合并工具版本：利用 input_cols 直接从数据库聚合列值。
    """
    num_files = len(source_csvs)
    if num_files == 0:
        raise ValueError("No input CSV files provided.")

    # 1. 解析主元数据（支持颜色渐变）
    meta_items = [item.strip() for item in metadata_list.split(",") if item.strip()]
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

    # 2. 检查自定义列长度
    if extra_col_data is not None and extra_col_name:
        if len(extra_col_data) != num_files:
            raise ValueError(f"Extra column '{extra_col_name}' length ({len(extra_col_data)}) mismatch with files ({num_files}).")

    # 3. 读取、筛选并合并
    all_dfs = []
    for idx, path_str in enumerate(source_csvs):
        path = Path(path_str)
        if not path.exists(): continue
            
        try:
            df = pd.read_csv(path, encoding=encoding)
        except Exception: continue
            
        if df.empty: continue

        if filter_query:
            try:
                df = df.query(filter_query)
            except Exception: continue
        
        if df.empty: continue

        # 写入主元数据
        df[new_col_name] = final_values[idx]
        
        # 写入额外列（如果存在）
        if extra_col_data is not None and extra_col_name:
            df[extra_col_name] = extra_col_data[idx]
            
        all_dfs.append(df)

    if not all_dfs:
        raise ValueError("No data found to merge.")

    merged_df = pd.concat(all_dfs, ignore_index=True)

    # 4. 保存输出
    out_name = "merged_data.csv"
    merged_df.to_csv(out_name, index=False, encoding="utf-8-sig")

    merge_return_file(out_name)

regist_merge_tool(csv_merge_with_metadata)