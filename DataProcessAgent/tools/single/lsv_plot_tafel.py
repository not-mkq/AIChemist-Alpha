# tools/lsv_plot_tafel.py
"""
根据 LSV / Tafel 区间数据绘制 Tafel 图，并在同一图中绘制拟合直线：
- 输入 CSV 中的电流密度单位为 A/cm²
- 内部将电流密度换算为 mA/cm² 用于：
  - tafel_range 过滤（区间单位为 mA/cm²）
  - log10(j) 计算（j 以 mA/cm² 计）
- x 轴：log10(j)（j in mA/cm²）
- y 轴：电位（可选择 IR 补偿前 / 后）
"""

from pathlib import Path
import csv
import math
import re

import numpy as np
import matplotlib.pyplot as plt

from tool_runtime import (
    regist_tool,
    return_file,
)


def _find_col_index(header: list[str], candidates: list[str], default_idx: int | None = None) -> int:
    """
    在 header 中根据候选关键字（大小写不敏感、子串匹配）寻找列索引。
    如果 default_idx 为 None 且找不到候选列，则抛 ValueError。
    """
    lower = [h.strip().lower() for h in header]
    for cand in candidates:
        cand = cand.lower()
        for i, h in enumerate(lower):
            if cand in h:
                return i
    if default_idx is not None:
        return default_idx
    raise ValueError(f"无法在表头 {header} 中找到匹配列：{candidates}")


def _parse_tafel_range(tafel_range: str) -> tuple[float, float]:
    """
    解析 tafel_range 字符串，形如 "1-10" 或 "0.5 - 5"。
    返回 (min_abs_j_mAcm2, max_abs_j_mAcm2)，单位为 mA/cm²。
    """
    s = tafel_range.strip()
    if not s:
        raise ValueError("tafel_range 为空字符串")
    m = re.match(r"\s*([+-]?\d+(?:\.\d*)?)\s*-\s*([+-]?\d+(?:\.\d*)?)\s*", s)
    if not m:
        raise ValueError(f"无法解析 tafel_range 参数: {tafel_range!r}")
    lo = float(m.group(1))
    hi = float(m.group(2))
    if lo > hi:
        lo, hi = hi, lo
    if lo <= 0 or hi <= 0:
        raise ValueError(f"tafel_range 必须为正数区间（mA/cm²），当前为: {lo} - {hi}")
    return lo, hi


def lsv_plot_tafel(
    tool_name: str,
    source_csv: str,
    use_ir_potential: bool = True,
    # 可选：将已知 Rs 展示在标题中（不参与计算）
    r_solution_ohm: float | None = None,
    # 可选：按 |j| 范围裁剪数据（区间单位为 mA/cm²）
    tafel_range: str | None = None,
    # 文本类绘图参数（名字尽量向 LSV plot 对齐）
    xlabel: str = "log(j) [j in mA/cm²]",
    ylabel: str = "Potential (V)",
    title: str = "Tafel plot",
    # 字体及线型样式
    font: str = "Arial",
    fontsize: int = 12,
    line_color: str = "blue",
    line_width: float = 2.0,
    marker: str | None = "o",
    marker_size: float = 4.0,
    plot_grid: bool = True,
    # 画布尺寸
    fig_width: float = 5.0,
    fig_height: float = 4.0,
    dpi: int = 150,
    encoding: str = "utf-8",
) -> None:
    """
    读取 CSV 数据，绘制 Tafel 散点 + 拟合直线，并输出 PNG 文件。

    - source_csv: 输入 CSV 文件（Tafel 区间数据或全曲线数据），电流密度单位为 A/cm²
    - use_ir_potential: True 使用 IR 补偿电位列（potential_ir_*），False 使用原始电位列（potential_*）
    - r_solution_ohm: 可选，只用于标题展示 Rs，不参与计算
    - tafel_range: 可选，例如 "1-10"，按 |j| (mA/cm²) 区间裁剪后再拟合 / 绘图
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    # 解析 tafel_range（如果有），单位 mA/cm²
    use_range = False
    j_min_mA = j_max_mA = 0.0
    if tafel_range is not None and tafel_range.strip() != "":
        j_min_mA, j_max_mA = _parse_tafel_range(tafel_range)
        use_range = True

    with src.open("r", encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        first_row = next(reader, None)
        if first_row is None:
            raise ValueError("输入 CSV 为空")

        header = [c.strip() for c in first_row]
        if len(header) < 2:
            raise ValueError("输入 CSV 至少需要两列（电位、电流/电流密度）")

        # 选择电位列：IR 或 非 IR
        if use_ir_potential:
            pot_idx = _find_col_index(
                header,
                candidates=["potential_ir_v", "potential_ir"],
                default_idx=None,
            )
        else:
            pot_idx = _find_col_index(
                header,
                candidates=["potential_v", "potential"],
                default_idx=None,
            )

        # 电流密度 / 电流列（单位 A/cm²）
        cur_idx = _find_col_index(
            header,
            candidates=[
                "current_density",  # 建议列名中带这个
                "current_a", "current",  # 兜底
            ],
            default_idx=None,
        )

        # 收集拟合用点：x = log10(j_mAcm2), y = E
        x_vals: list[float] = []
        y_vals: list[float] = []

        for row in reader:
            if not row:
                continue
            if len(row) <= max(pot_idx, cur_idx):
                raise ValueError("数据行列数不足，无法获取电位和电流")

            pot_str = row[pot_idx].strip()
            cur_str = row[cur_idx].strip()
            if pot_str == "" or cur_str == "":
                continue

            potential = float(pot_str)
            current_a_per_cm2 = float(cur_str)  # A/cm²

            abs_j_a = abs(current_a_per_cm2)
            if abs_j_a <= 0:
                # log10(0) 无意义，跳过
                continue

            # 换算成 mA/cm²
            abs_j_mA = abs_j_a * 1000.0

            # 如果指定了 tafel_range，就按 |j| (mA/cm²) 过滤
            if use_range and not (j_min_mA <= abs_j_mA <= j_max_mA):
                continue

            # Tafel 用 j (mA/cm²)
            log_j = math.log10(abs_j_mA)

            x_vals.append(log_j)
            y_vals.append(potential)

    if len(x_vals) < 2:
        raise ValueError("用于 Tafel 拟合的数据点不足（至少需要 2 个点）")

    # 转为 numpy 做线性拟合：E = a * log(j) + b
    x_arr = np.array(x_vals, dtype=float)
    y_arr = np.array(y_vals, dtype=float)

    # polyfit 返回 [a, b]
    a, b = np.polyfit(x_arr, y_arr, 1)

    # 拟合直线 y_fit
    y_fit = a * x_arr + b

    # 计算 R²
    y_mean = y_arr.mean()
    ss_tot = np.sum((y_arr - y_mean) ** 2)
    ss_res = np.sum((y_arr - y_fit) ** 2)
    if ss_tot == 0:
        r2 = 1.0
    else:
        r2 = 1.0 - ss_res / ss_tot

    # 斜率从 V/dec 变成 mV/dec
    slope_mVdec = a * 1000.0

    # 绘图
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)

    # 字体设置（简单处理）
    plt.rcParams["font.family"] = font
    plt.rcParams["axes.unicode_minus"] = False

    # 散点（拟合使用的数据点）
    scatter_kwargs: dict = {
        "s": marker_size ** 2,
        "alpha": 0.7,
        "label": "Tafel data (fitting range)" if use_range else "Tafel data",
    }
    if line_color:
        scatter_kwargs["edgecolors"] = line_color
        scatter_kwargs["facecolors"] = "none"
    ax.scatter(x_arr, y_arr, **scatter_kwargs)

    # 拟合线：按 x 排序一下，让线是单调的
    sort_idx = np.argsort(x_arr)
    x_sorted = x_arr[sort_idx]
    y_fit_sorted = y_fit[sort_idx]

    line_label = f"Tafel fit: {slope_mVdec:.1f} mV/dec, R²={r2:.3f}"
    ax.plot(
        x_sorted,
        y_fit_sorted,
        color="red",
        linewidth=line_width,
        label=line_label,
    )

    # 轴标签 / 标题
    ax.set_xlabel(xlabel, fontsize=fontsize)
    ax.set_ylabel(ylabel, fontsize=fontsize)

    # 标题：如果用的是 IR 电位且传入了 Rs，就在标题里加 (Rs=XXΩ)
    if use_ir_potential and r_solution_ohm is not None:
        full_title = f"{title} (Rs={r_solution_ohm:.2f} Ω)"
    else:
        full_title = title
    ax.set_title(full_title, fontsize=fontsize)

    if plot_grid:
        ax.grid(True, alpha=0.3)

    ax.legend()
    fig.tight_layout()

    # 输出文件名：沿用旧命名习惯
    stem = src.stem
    if use_ir_potential:
        out_name = f"{stem}_Tafel_fit_IR.png"
    else:
        out_name = f"{stem}_Tafel_fit.png"
    out_path = src.parent / out_name

    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    return_file(out_path.name)


regist_tool(lsv_plot_tafel)
