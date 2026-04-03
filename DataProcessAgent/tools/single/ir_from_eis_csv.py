# tools/ir_from_eis_csv.py
"""
从 EIS 数据 CSV 中估算溶液电阻 R_solution (欧姆)，并生成 IR 补偿质量报告。
- 输入：EIS 数据 CSV（freq_Hz, Z_real_ohm, Z_imag_ohm）
- 输出：
  1) return_value: r_solution_ohm (float)
  2) 报告文件：{basename}_ir_quality.json
"""

from pathlib import Path
import csv
import json
from math import sqrt

from tool_runtime import (
    regist_tool,
    return_file,
    return_value,
)


def ir_from_eis_csv(
    tool_name: str,
    source_eis: str,
    ir_method: str = "mean_high_freq",
    points: int = 5,
    z_imag_max_abs: float = 10.0,
    encoding: str = "utf-8",
) -> None:
    """
    从 EIS CSV 中估算溶液电阻 R_solution。

    参数
    ----
    tool_name : str
        运行时框架传入的工具实例名（不参与逻辑，只用于上下文）。
    source_eis : str
        EIS 数据 CSV 文件路径。约定：
        - 第 1 列：频率 (Hz)
        - 第 2 列：Z_real (Ohm)
        - 第 3 列：Z_imag (Ohm)
    ir_method : str
        估算方法：
        - "mean_high_freq": 按频率从高到低选前 N 个点，取 Z_real 平均
        - "mean_low_Z":    按 |Z| 从小到大选前 N 个点，取 Z_real 平均，
                           并可用 z_imag_max_abs 过滤 |Z_imag| 过大的点
    points : int
        拟合/平均所用的点数 N。如果有效点不足 N，则使用全部有效点。
    z_imag_max_abs : float
        在 "mean_low_Z" 方法中，允许的 |Z_imag| 最大值（过滤严重电容区点）。
    encoding : str
        输入 CSV 编码，默认 utf-8。
    """
    src = Path(source_eis)
    if not src.is_file():
        raise FileNotFoundError(f"EIS CSV not found: {source_eis}")

    # 读取并解析数据行
    freqs: list[float] = []
    z_reals: list[float] = []
    z_imags: list[float] = []

    with src.open("r", encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            if len(row) < 3:
                continue
            try:
                freq = float(row[0])
                z_real = float(row[1])
                z_imag = float(row[2])
            except ValueError:
                # 可能是表头或无效行
                continue
            freqs.append(freq)
            z_reals.append(z_real)
            z_imags.append(z_imag)

    n_total = len(freqs)
    if n_total == 0:
        raise ValueError(f"No valid numeric EIS data found in {source_eis}")

    # 根据方法选择用于计算的索引
    indices = list(range(n_total))

    if ir_method == "mean_high_freq":
        # 按频率从高到低排序
        indices.sort(key=lambda i: freqs[i], reverse=True)
        selected_idx = indices[: max(1, points)]
    elif ir_method == "mean_low_Z":
        # 先过滤 |Z_imag| 过大的点
        filtered = []
        for i in indices:
            if abs(z_imags[i]) <= z_imag_max_abs:
                z_abs = sqrt(z_reals[i] ** 2 + z_imags[i] ** 2)
                filtered.append((i, z_abs))
        if not filtered:
            # 如果过滤后一个点都没有，就退化为使用全部点
            filtered = [
                (i, sqrt(z_reals[i] ** 2 + z_imags[i] ** 2))
                for i in indices
            ]
        # 按 |Z| 从小到大排序
        filtered.sort(key=lambda t: t[1])
        selected_idx = [t[0] for t in filtered[: max(1, points)]]
    else:
        raise ValueError(f"Unknown ir_method: {ir_method}")

    # 计算 R_solution 为选中点的 Z_real 平均
    used_z_reals = [z_reals[i] for i in selected_idx]
    r_solution_ohm = float(sum(used_z_reals) / len(used_z_reals))

    used_freqs = [freqs[i] for i in selected_idx]
    used_z_imags = [z_imags[i] for i in selected_idx]

    report = {
        "success": True,
        "method": ir_method,
        "r_solution_ohm": r_solution_ohm,
        "points_param": points,
        "z_imag_max_abs": z_imag_max_abs,
        "n_total_points": n_total,
        "n_used_points": len(selected_idx),
        "used_indices": selected_idx,
        "used_freq_range": {
            "min_Hz": min(used_freqs),
            "max_Hz": max(used_freqs),
        },
        "used_z_real_stats": {
            "min": min(used_z_reals),
            "max": max(used_z_reals),
            "mean": r_solution_ohm,
        },
        "used_z_imag_abs_max": max(abs(v) for v in used_z_imags),
        "source_file": src.name,
    }

    # 写质量报告文件 {basename}_ir_quality.json
    report_path = src.with_name(f"{src.stem}_ir_quality.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 返回：文件 + r_solution_ohm
    return_file(report_path.name)
    return_value(r_solution_ohm)


regist_tool(ir_from_eis_csv)
