#!/usr/bin/env python3
"""
cv_cycle_detect.py

CV 曲线圈数检测工具：
- 识别电位换向点，自动划分 Cycle 序号。
- 输出包含 Cycle 列的新 CSV。
"""

import csv
import re
from pathlib import Path

import numpy as np

from tool_runtime import (
    regist_tool,
    return_file,
    return_value,
)

def _find_col_index(header: list[str], pattern: str) -> int:
    if pattern in header:
        return header.index(pattern)
    for i, h in enumerate(header):
        if re.fullmatch(pattern, h):
            return i
    raise ValueError(f"Column '{pattern}' not found in {header}")

def cv_cycle_detect(
    tool_name: str,
    source_csv: str,
    potential_col: str,
    cycle_col: str = "Cycle",
    noise_threshold: float = 0.0005,
    encoding: str = "utf-8",
) -> None:
    """
    通过识别电位极值点划分圈数。
    """
    src = Path(source_csv)
    
    with src.open("r", encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        header = [c.strip() for c in next(reader)]
        p_idx = _find_col_index(header, potential_col)
        rows = [row for row in reader if row]

    if not rows:
        raise ValueError("Input CSV is empty")

    potentials = np.array([float(r[p_idx]) for r in rows])
    n = len(potentials)
    
    diffs = np.diff(potentials)
    directions = []
    current_dir = 0
    for d in diffs:
        if abs(d) > noise_threshold:
            current_dir = 1 if d > 0 else -1
        directions.append(current_dir)
    directions.append(directions[-1] if directions else 0)
    
    cycle_indices = np.ones(n, dtype=int)
    reversal_count = 0
    active_cycle = 1
    last_dir = directions[0]
    
    for i in range(1, n):
        if directions[i] != 0 and directions[i] != last_dir:
            reversal_count += 1
            last_dir = directions[i]
            if reversal_count > 0 and reversal_count % 2 == 0:
                if i < n - 1:
                    active_cycle += 1
        cycle_indices[i] = active_cycle

    unique_vals, counts = np.unique(cycle_indices, return_counts=True)
    if len(counts) > 1 and counts[-1] < 5:
        bad_c = unique_vals[-1]
        real_last_c = unique_vals[-2]
        cycle_indices[cycle_indices == bad_c] = real_last_c
        active_cycle = int(real_last_c)

    max_c = int(active_cycle)

    out_name = "cycled_data.csv"
    new_header = header + [cycle_col]
    
    with open(out_name, "w", encoding=encoding, newline="") as f:
        writer = csv.writer(f)
        writer.writerow(new_header)
        for i, row in enumerate(rows):
            writer.writerow(row + [str(cycle_indices[i])])

    return_file(out_name)
    return_value(max_c)

regist_tool(cv_cycle_detect)