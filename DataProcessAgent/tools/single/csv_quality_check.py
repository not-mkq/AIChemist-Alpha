# tools/single/csv_quality_check.py
"""
通用 CSV 数据质量检查工具 (v3 - 算法优化版)

检测逻辑：
- Invalid: NaN, Inf (对应标记: mark_invalid)
- Jump: 偏离局部趋势的尖峰。计算 |val - local_median| > threshold_jump (对应标记: mark_jump)
- Noise: 曲线不顺滑。计算 |二阶导数| > threshold_noise (对应标记: mark_noise)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
from tool_runtime import regist_tool, return_file, return_json

def _parse_float(val: Any, default: float) -> float:
    try:
        if val is None or str(val).strip().lower() in ("null", ""):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

def csv_quality_check(
    tool_name: str,
    source_csv: str,
    target_col: str,
    
    # 阈值 (相对于数据整体跨度的比例)
    threshold_jump: str | None = "0.05",   # 孤立尖峰阈值
    threshold_noise: str | None = "0.02",  # 二阶导噪声阈值
    
    # 标记内容
    mark_invalid: str | None = "Invalid",
    mark_jump: str | None = "Jump",
    mark_noise: str | None = "Noise",
    mark_ok: str | None = "",
    
    # 输出配置
    output_col_name: str = "Quality_Note",
    encoding: str = "utf-8"
) -> None:
    src_path = Path(source_csv)
    
    # 解析参数
    t_jump = _parse_float(threshold_jump, 0.05)
    t_noise = _parse_float(threshold_noise, 0.02)
    m_invalid = mark_invalid if mark_invalid is not None else "Invalid"
    m_jump = mark_jump if mark_jump is not None else "Jump"
    m_noise = mark_noise if mark_noise is not None else "Noise"
    m_ok = mark_ok if mark_ok is not None else ""
    
    # 1. 读取数据
    rows = []
    header = []
    with src_path.open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        for row in reader:
            rows.append(row)
            
    if target_col not in header:
        raise ValueError(f"Column '{target_col}' not found in headers: {header}")
        
    raw_values = []
    for r in rows:
        try:
            v = r[target_col]
            raw_values.append(float(v) if v and v.strip() else np.nan)
        except (ValueError, TypeError):
            raw_values.append(np.nan)
            
    data = np.array(raw_values)
    n = len(data)
    if n == 0:
        raise ValueError("CSV has no data rows.")

    # 2. 计算质量
    notes = [m_ok] * n
    
    # A. 无效值 (最高优先级)
    invalid_mask = ~np.isfinite(data)
    for i in np.where(invalid_mask)[0]:
        notes[i] = m_invalid
        
    # 计算有效数据的跨度
    valid_data = data[np.isfinite(data)]
    if len(valid_data) > 1:
        span = np.ptp(valid_data) or 1.0
        
        # B. 尖峰检测 (Jump) - 使用中值滤波残差
        # window_size = 5
        for i in range(n):
            if notes[i] != m_ok: continue
            
            start = max(0, i - 2)
            end = min(n, i + 3)
            neighbor_data = data[start:end]
            neighbor_valid = neighbor_data[np.isfinite(neighbor_data)]
            
            if len(neighbor_valid) > 0:
                local_median = np.median(neighbor_valid)
                if abs(data[i] - local_median) > (t_jump * span):
                    notes[i] = m_jump

        # C. 噪声检测 (Noise) - 使用二阶导数
        if n > 2:
            # 二阶导数近似: d2[i] = data[i-1] - 2*data[i] + data[i+1]
            d2 = np.zeros(n)
            # 我们只计算内部点的二阶导
            d2[1:-1] = np.abs(data[:-2] - 2*data[1:-1] + data[2:])
            
            for i in range(1, n - 1):
                if notes[i] == m_ok: # 不覆盖更高优先级的 Invalid/Jump
                    if d2[i] > (t_noise * span):
                        notes[i] = m_noise

    # 3. 统计结果
    stats = {
        "count_invalid": int(np.sum([1 for x in notes if x == m_invalid])),
        "count_jump": int(np.sum([1 for x in notes if x == m_jump])),
        "count_noise": int(np.sum([1 for x in notes if x == m_noise])),
        "total_rows": n
    }
    
    # 4. 写回
    out_name = f"{src_path.stem}_checked.csv"
    new_header = header + [output_col_name]
    with open(out_name, "w", encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=new_header)
        writer.writeheader()
        for i, row in enumerate(rows):
            row[output_col_name] = notes[i]
            writer.writerow(row)
            
    return_json(stats)
    return_file(out_name)

regist_tool(csv_quality_check)
