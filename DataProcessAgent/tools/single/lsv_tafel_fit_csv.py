# tools/lsv_tafel_fit_csv.py
"""
从归一化后的 LSV CSV 中根据用户选择的电位来源(raw / ir)做 Tafel 拟合。

约定：
- CSV 中的电流密度单位是 **A/cm²**。
- 参数 tafel_range 使用 **mA/cm²** 输入，例如 "1-10" 表示 1~10 mA/cm²。
- 内部会将 mA/cm² 转换为 A/cm² 再进行筛选。
"""

from pathlib import Path
import csv
import json
import math
from typing import List, Tuple

from tool_runtime import (
    regist_tool,
    return_file,
    return_value,
)


def _find_exact_col(header: List[str], candidates: List[str]) -> int | None:
    """
    在 header 中根据候选关键字（大小写不敏感）寻找确切列。
    找不到返回 None。
    """
    lower = [h.strip().lower() for h in header]
    for cand in candidates:
        cand = cand.lower()
        for i, h in enumerate(lower):
            if cand == h:
                return i
    return None


def _parse_tafel_range_mA(tafel_range: str | None) -> Tuple[float | None, float | None]:
    """
    解析类似 '1-10' 的 tafel_range，单位 **mA/cm²**。
    返回 (j_min_mA, j_max_mA)，任一端缺失则为 None。
    """
    if not tafel_range:
        return None, None
    text = tafel_range.strip()
    if not text:
        return None, None
    if "-" not in text:
        j_min_mA = float(text)
        return j_min_mA, None
    left, right = text.split("-", 1)
    left = left.strip()
    right = right.strip()
    j_min_mA = float(left) if left else None
    j_max_mA = float(right) if right else None
    return j_min_mA, j_max_mA


def lsv_tafel_fit_csv(
    tool_name: str,
    source_csv: str,
    potential_source: str,          # "raw" | "ir"
    tafel_range: str | None = None, # 单位 mA/cm²
    use_abs_current: bool = True,
    encoding: str = "utf-8",
) -> None:
    """
    对 LSV 曲线做 Tafel 拟合。
    - CSV 中电流密度单位为 A/cm²。
    - tafel_range 使用 mA/cm² 输入。
    - 电位列由 potential_source 决定（必须指定 raw 或 ir）。
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    # 解析 tafel_range（mA/cm²）
    j_min_mA, j_max_mA = _parse_tafel_range_mA(tafel_range)
    # 转换为 A/cm² 用于筛选
    j_min_A = j_min_mA / 1000.0 if j_min_mA is not None else None
    j_max_A = j_max_mA / 1000.0 if j_max_mA is not None else None

    with src.open("r", encoding=encoding, newline="") as f_in:
        reader = csv.reader(f_in)

        header = next(reader, None)
        if header is None:
            raise ValueError("输入 CSV 为空")

        header = [c.strip() for c in header]

        # -------- 电位列选择严格由 potential_source 决定 --------
        pot_idx = None
        if potential_source == "ir":
            pot_idx = _find_exact_col(header, ["potential_ir_v"])
            if pot_idx is None:
                raise ValueError("选择了 potential_source='ir'，但 CSV 中没有列 potential_ir_V")
        elif potential_source == "raw":
            pot_idx = _find_exact_col(header, ["potential_v", "potential"])
            if pot_idx is None:
                raise ValueError("选择了 potential_source='raw'，但 CSV 中没有原始电位列 potential_V 或 potential")
        else:
            raise ValueError(f"未知的 potential_source 值：{potential_source}")

        # 电流列：自动找一个含 current / density 的列，单位视为 A/cm²
        lower_header = [h.lower() for h in header]
        cur_idx = None
        for i, h in enumerate(lower_header):
            if ("current" in h) or ("density" in h) or h.startswith("j_"):
                cur_idx = i
                break
        if cur_idx is None:
            raise ValueError("无法找到电流或电流密度列（单位应为 A/cm²）")

        # -------- 读取数据点 --------
        potentials: List[float] = []
        currents_A: List[float] = []  # A/cm²

        for row in reader:
            if not row:
                continue
            if len(row) <= max(pot_idx, cur_idx):
                continue

            E = float(row[pot_idx])
            j_A = float(row[cur_idx])  # A/cm²

            if use_abs_current:
                j_A = abs(j_A)
            if j_A <= 0:
                continue

            # tafel_range 过滤：输入是 mA/cm²，这里用 A/cm² 对比
            if j_min_A is not None and j_A < j_min_A:
                continue
            if j_max_A is not None and j_A > j_max_A:
                continue

            potentials.append(E)
            currents_A.append(j_A)

    n = len(potentials)
    if n < 2:
        raise ValueError(f"用于 Tafel 拟合的有效点不足 (n={n})")

    # log10(j) vs E 拟合；j 单位 A/cm²，但 log10 不关心单位
    xs = [math.log10(j) for j in currents_A]
    ys = potentials

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    sxx = 0.0
    sxy = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        sxx += dx * dx
        sxy += dx * dy

    if sxx == 0.0:
        raise ValueError("Tafel 拟合失败：log10(j) 无变化，无法线性回归")

    slope_V_per_dec = sxy / sxx
    intercept_V = mean_y - slope_V_per_dec * mean_x

    # R²
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope_V_per_dec * x + intercept_V)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 1.0

    tafel_slope_mV_per_dec = slope_V_per_dec * 1000.0

    # 用到的电流 / 电位范围（同时给出 A/cm² 和 mA/cm²）
    j_min_used_A = min(currents_A) if currents_A else None
    j_max_used_A = max(currents_A) if currents_A else None
    j_min_used_mA = j_min_used_A * 1000.0 if j_min_used_A is not None else None
    j_max_used_mA = j_max_used_A * 1000.0 if j_max_used_A is not None else None
    e_min_used = min(potentials) if potentials else None
    e_max_used = max(potentials) if potentials else None

    # -------- 写报告文件 --------
    report = {
        "tafel_slope_mV_per_dec": tafel_slope_mV_per_dec,
        "slope_V_per_dec": slope_V_per_dec,
        "intercept_V": intercept_V,
        "r_squared": r_squared,
        "n_points": n,

        # 参数 & 单位信息
        "source_csv": src.name,
        "potential_source": potential_source,
        "potential_column": header[pot_idx],
        "current_column": header[cur_idx],
        "current_unit": "A/cm^2",
        "tafel_range_input_mAcm2": tafel_range,
        "tafel_range_effective_Acm2": [j_min_A, j_max_A],
        "use_abs_current": use_abs_current,

        # 实际用于拟合的数据范围
        "current_used_range_Acm2": [j_min_used_A, j_max_used_A],
        "current_used_range_mAcm2": [j_min_used_mA, j_max_used_mA],
        "potential_used_range_V": [e_min_used, e_max_used],
    }

    report_path = src.with_name(f"{src.stem}_tafel_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 主返回值
    return_value(tafel_slope_mV_per_dec)
    # 报告文件
    return_file(report_path.name)


regist_tool(lsv_tafel_fit_csv)
