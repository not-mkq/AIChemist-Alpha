import re
import logging
from pathlib import Path
from typing import List, Optional
import pandas as pd

from tool_runtime import regist_tool, return_json

logger = logging.getLogger(__name__)

def _find_col_index(header: List[str], col_name: str) -> int:
    # 兼容 csv_generic_plot 的模糊查找逻辑
    target = col_name.strip().lower()
    lower = [h.strip().lower() for h in header]
    
    # 1. 精确匹配 (忽略大小写)
    if target in lower:
        return lower.index(target)
        
    # 2. 模糊匹配 (包含)
    for i, h in enumerate(lower):
        if target in h:
            return i
            
    raise ValueError(f"Cannot find column '{col_name}' in header: {header}")

def csv_stat(
    tool_name: str,
    source_csv: str,
    y_col: str,
    stat_type: str,  # max, min, mean, median
    x_col: Optional[str] = None,
    encoding: Optional[str] = None,
) -> None:
    """
    计算 CSV 指定列的统计值，并支持简单的过滤条件。
    返回 JSON: {"x": val, "y": val, "stat_type": str}
    """
    encoding = encoding if encoding is not None else "utf-8"
    src = Path(source_csv)

    # 1. 读取 CSV
    try:
        # 预读取一行以获取 header (用于 _find_col_index 的模糊匹配逻辑)
        # 也可以直接用 pandas 读取，然后处理 columns
        df = pd.read_csv(src, encoding=encoding)
    except Exception as e:
        raise RuntimeError(f"Failed to read CSV file: {e}")

    header = list(df.columns)
    
    # 2. 解析 y_col 和 过滤条件
    # 格式: ColumnName@FilterExpr (参考 csv_generic_plot)
    # FilterExpr: Col == Val
    filter_expr = None
    y_col_name = y_col
    
    if "@" in y_col:
        y_col_name, filter_part = y_col.rsplit("@", 1)
        # 解析表达式: FilterCol op Value
        # 支持: ==, !=, >=, <=, >, <, =
        match = re.match(r"(.+?)\s*(==|!=|>=|<=|>|<|=)\s*(.+)", filter_part)
        if match:
            f_col_raw, f_op, f_val = match.groups()
            if f_op == "=": f_op = "=="
            
            # 找到 f_col 对应的真实列名
            try:
                f_col_idx = _find_col_index(header, f_col_raw)
                f_col_real = header[f_col_idx]
                
                # 尝试转换 value 为数字
                try:
                    f_val_num = float(f_val)
                    # 构建 query string (反引号包裹列名以处理空格)
                    filter_expr = f"`{f_col_real}` {f_op} {f_val_num}"
                except ValueError:
                    # 字符串比较
                    filter_expr = f"`{f_col_real}` {f_op} '{f_val}'"
            except ValueError:
                logger.warning(f"Filter column '{f_col_raw}' not found, ignoring filter.")
        else:
             logger.warning(f"Unsupported filter expression format: {filter_part}")

    # 找到 Y 列真实名称
    y_idx = _find_col_index(header, y_col_name)
    y_real = header[y_idx]

    # 找到 X 列真实名称 (如果存在)
    x_real = None
    if x_col:
        try:
            x_idx = _find_col_index(header, x_col)
            x_real = header[x_idx]
        except ValueError:
            logger.warning(f"X column '{x_col}' not found, ignoring X value return.")

    # 3. 应用过滤
    if filter_expr:
        try:
            original_len = len(df)
            df = df.query(filter_expr)
            logger.info(f"Filter applied: '{filter_expr}', rows {original_len} -> {len(df)}")
        except Exception as e:
            raise RuntimeError(f"Failed to apply filter '{filter_expr}': {e}")
            
    if df.empty:
         # 数据为空时，能否返回 None? 或者报错？
         # 报错比较安全，防止静默错误
         raise RuntimeError(f"Data is empty after filtering (or file is empty). Filter: {filter_expr}")

    # 4. 计算统计值
    # 确保 Y 列是数值
    y_series = pd.to_numeric(df[y_real], errors='coerce')
    
    # 移除 NaN (转换失败或原本缺失)
    valid_mask = y_series.notna()
    if not valid_mask.any():
        raise RuntimeError(f"Column '{y_real}' contains no valid numeric data")
        
    # 如果我们需要找对应的 X，我们需要保留原始索引，或者同步过滤 X
    df_clean = df.loc[valid_mask].copy()
    df_clean["__y_numeric__"] = y_series[valid_mask]
    
    stat_type = stat_type.lower()
    result_y = None
    result_x = None
    
    if stat_type == "max":
        # 找到 Y 最大值
        max_idx = df_clean["__y_numeric__"].idxmax()
        result_y = df_clean.loc[max_idx, "__y_numeric__"]
        if x_real:
            result_x = df_clean.loc[max_idx, x_real]
            
    elif stat_type == "min":
        # 找到 Y 最小值
        min_idx = df_clean["__y_numeric__"].idxmin()
        result_y = df_clean.loc[min_idx, "__y_numeric__"]
        if x_real:
            result_x = df_clean.loc[min_idx, x_real]
            
    elif stat_type == "mean":
        result_y = df_clean["__y_numeric__"].mean()
        if x_real:
             # 计算 X 的平均值
             x_series = pd.to_numeric(df_clean[x_real], errors='coerce')
             result_x = x_series.mean()
             
    elif stat_type == "median":
        result_y = df_clean["__y_numeric__"].median()
        if x_real:
             # 计算 X 的中位数
             x_series = pd.to_numeric(df_clean[x_real], errors='coerce')
             result_x = x_series.median()
    
    else:
        raise ValueError(f"Unknown stat_type: {stat_type}. Supported: max, min, mean, median")

    # 5. 构造输出
    output = {
        "y": float(result_y) if result_y is not None else None,
        "stat_type": stat_type
    }
    
    if result_x is not None:
        try:
            if pd.isna(result_x):
                output["x"] = None
            else:
                output["x"] = float(result_x)
        except (ValueError, TypeError):
             # 如果 X 无法转为 float (比如是分类标签)，返回字符串
             output["x"] = str(result_x)

    # 补充元数据，方便调试
    output["_meta"] = {
        "rows_used": len(df_clean),
        "y_col": y_real,
        "x_col": x_real if x_real else "N/A"
    }

    return_json(output)

regist_tool(csv_stat)
