#!/usr/bin/env python3
"""
csv_column_to_color.py

CSV 颜色映射工具：
- 根据参考列的值（数值或类别），在颜色渐变带中进行插值。
- 支持“数值区间线性映射”和“唯一值排序索引映射”两种模式。
- 输出包含新颜色列的 CSV。
"""

import csv
import re
from pathlib import Path

import numpy as np
import matplotlib.colors as mcolors

from tool_runtime import (
    regist_tool,
    return_file,
)

def _find_col_index(header: list[str], pattern: str) -> int:
    if pattern in header:
        return header.index(pattern)
    for i, h in enumerate(header):
        if re.fullmatch(pattern, h):
            return i
    raise ValueError(f"Column '{pattern}' not found in {header}")

def _is_numeric(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False

def csv_column_to_color(
    tool_name: str,
    source_csv: str,
    ref_col: str,
    colors: str = "blue, red",
    new_col_name: str = "Color",
    mode: str = "auto",  # auto, numeric, discrete
    encoding: str = "utf-8",
) -> None:
    """
    将 CSV 的某一列映射为颜色。
    """
    src = Path(source_csv)
    
    with src.open("r", encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        header = [c.strip() for c in next(reader)]
        ref_idx = _find_col_index(header, ref_col)
        rows = [row for row in reader if row]

    if not rows:
        raise ValueError("Input CSV is empty")

    # 1. 提取参考值
    raw_vals = [r[ref_idx] for r in rows]
    
    # 2. 准备颜色渐变带
    color_list = [c.strip() for c in colors.split(",")]
    if len(color_list) < 2:
        cmap = mcolors.ListedColormap(color_list * 2)
    else:
        cmap = mcolors.LinearSegmentedColormap.from_list("custom_gradient", color_list)

    # 3. 确定模式并计算映射
    # 判断是否全是数字
    all_numeric = all(_is_numeric(v) for v in raw_vals)
    effective_mode = mode
    if mode == "auto":
        effective_mode = "numeric" if all_numeric else "discrete"

    final_colors = []
    
    if effective_mode == "numeric":
        vals = np.array([float(v) for v in raw_vals])
        v_min, v_max = np.min(vals), np.max(vals)
        range_v = v_max - v_min
        for v in vals:
            frac = (v - v_min) / range_v if range_v > 0 else 0.0
            final_colors.append(mcolors.to_hex(cmap(frac)))
    else:
        # 离散模式：排序去重后按 index 映射
        unique_vals = sorted(list(set(raw_vals)), key=lambda x: float(x) if _is_numeric(x) else x)
        val_to_idx = {val: i for i, val in enumerate(unique_vals)}
        n_unique = len(unique_vals)
        
        # 特殊情况：如果唯一值数量恰好等于颜色数量，尝试一一对应
        # 只有在 colors 给出的颜色足够多时生效
        one_to_one = (n_unique == len(color_list))
        
        for v in raw_vals:
            idx = val_to_idx[v]
            if one_to_one:
                # 直接取对应位置的颜色
                final_colors.append(mcolors.to_hex(color_list[idx]))
            else:
                frac = idx / (n_unique - 1) if n_unique > 1 else 0.0
                final_colors.append(mcolors.to_hex(cmap(frac)))

    # 4. 生成输出
    out_name = "colored_data.csv"
    new_header = header + [new_col_name]
    with open(out_name, "w", encoding=encoding, newline="") as f:
        writer = csv.writer(f)
        writer.writerow(new_header)
        for i, row in enumerate(rows):
            writer.writerow(row + [final_colors[i]])

    return_file(out_name)

regist_tool(csv_column_to_color)
