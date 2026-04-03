# tools/lsv_plot_curve.py
"""
绘制 LSV 曲线图（原始 / IR 补偿 + target 点 + 可选 Tafel 叠加）。

约定：
- 输入 CSV 中电流单位为 A/cm²；
- 工具内部统一转换为 mA/cm² 绘图；
- 默认 Y 轴为 Current Density (mA/cm²)；
- 支持 figsize 与 dpi。
"""

from pathlib import Path
import csv
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tool_runtime import (
    regist_tool,
    return_file,
    get_batch,
    get_item,
)

_CHINESE_FONT_CANDIDATES = [
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "KaiTi",
    "FangSong",
]


def _find_col_index(header: List[str], candidates: List[str], default_idx: int) -> int:
    lower = [h.strip().lower() for h in header]
    for cand in candidates:
        cand = cand.lower()
        for i, h in enumerate(lower):
            if cand in h:
                return i
    return default_idx


def _parse_target_currents(s: str) -> List[float]:
    if not s:
        return []
    parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
    return [float(p) for p in parts]


def _render_title(template: Optional[str], *, file_path: Path) -> str:
    if not template:
        return f"LSV of {file_path.stem}"

    stem = file_path.stem
    context = {
        "batch": get_batch(),
        "item": get_item(),
        "file": file_path.name,
        "stem": stem,
        "sample": stem,
    }
    return template.format(**context)


def _choose_font(user_font: str) -> str:
    if user_font in _CHINESE_FONT_CANDIDATES:
        return user_font
    return _CHINESE_FONT_CANDIDATES[0]


def lsv_plot_curve(
    tool_name: str,
    source_csv: str,
    curve_type: str = "raw",

    # --- figure setting ---
    fig_width: float = 5.0,
    fig_height: float = 4.0,
    dpi: int = 300,

    # --- axis style ---
    xlabel: str = "Potential (V)",
    ylabel: str = "Current Density (mA/cm²)",
    title: Optional[str] = None,
    font: str = "Arial",
    fontsize: float = 12.0,

    # --- curve style ---
    line_color: str = "blue",
    line_width: float = 2.0,

    # --- target markers ---
    target_current: str = "10",     # mA/cm²
    mark_targets: bool = True,
    use_abs_current: bool = True,

    # --- Tafel ---
    tafel_enabled: bool = False,
    tafel_range: str = "1-10",

    # --- misc ---
    plot_grid: bool = True,
    encoding: str = "utf-8",
) -> None:

    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    if curve_type not in ("raw", "ir"):
        raise ValueError("curve_type 必须是 'raw' 或 'ir'")

    # === read csv ===
    with src.open("r", encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        first_row = next(reader)
        header = [c.strip() for c in first_row]

        cur_idx = _find_col_index(header,
            ["a/cm2", "a/cm^2", "current_density", "current"],
            default_idx=1
        )

        if curve_type == "ir":
            pot_idx = _find_col_index(header,
                ["potential_ir_v", "potential_ir"],
                default_idx=-1,
            )
            if pot_idx < 0:
                raise ValueError("IR 曲线缺少 potential_ir 列")
        else:
            pot_idx = _find_col_index(header,
                ["potential_v", "potential"],
                default_idx=0
            )

        potentials = []
        currents_mAcm2 = []

        for row in reader:
            potential_v = float(row[pot_idx])
            current_Acm2 = float(row[cur_idx])
            currents_mAcm2.append(current_Acm2 * 1000.0)  # A/cm² → mA/cm²
            potentials.append(potential_v)

    E_all = np.asarray(potentials, float)
    I_all = np.asarray(currents_mAcm2, float)

    # === fig settings ===
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)

    ax.plot(E_all, I_all,
            color=line_color,
            linewidth=line_width)

    font_to_use = _choose_font(font)
    ax.set_xlabel(xlabel, fontname=font_to_use, fontsize=fontsize)
    ax.set_ylabel(ylabel, fontname=font_to_use, fontsize=fontsize)
    ax.set_title(_render_title(title, file_path=src),
                 fontname=font_to_use, fontsize=fontsize)

    if plot_grid:
        ax.grid(True, alpha=0.3)

    have_legend = False

    # === target markers ===
    if mark_targets and target_current:
        targets = _parse_target_currents(target_current)

        for tc in targets:
            best_idx, best_diff = None, None
            for i, cur in enumerate(I_all):
                value = abs(cur) if use_abs_current else cur
                diff = abs(value - tc)
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best_idx = i

            if best_idx is not None:
                x0 = float(E_all[best_idx])
                y0 = float(I_all[best_idx])

                ax.plot(x0, y0, "ro", markersize=8,
                        label=f"{tc} mA/cm² @ {x0:.3f} V")

                ax.annotate(
                    f"{tc} mA/cm²\n{x0:.3f} V",
                    xy=(x0, y0),
                    xytext=(10, 10),
                    textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.3",
                              facecolor="yellow", alpha=0.7),
                    arrowprops=dict(arrowstyle="->",
                                    connectionstyle="arc3,rad=0"),
                    fontsize=max(8, fontsize - 2),
                )

        have_legend = True

    # === Tafel fit overlay ===
    if tafel_enabled and curve_type == "raw":
        rng = tafel_range.replace("，", ",").replace(" ", "")
        lo, hi = (rng.split("-", 1) if "-" in rng else (rng, rng))
        lo, hi = float(lo), float(hi)
        lo, hi = min(lo, hi), max(lo, hi)

        mask = (
            np.isfinite(I_all) & np.isfinite(E_all)
            & (I_all > 0)
            & (I_all >= lo) & (I_all <= hi)
        )

        if mask.sum() >= 3:
            I_sel = I_all[mask]
            E_sel = E_all[mask]
            x = np.log10(np.clip(I_sel, 1e-12, None))
            y = E_sel

            b, a = np.polyfit(x, y, 1)
            order = np.argsort(I_sel)
            I_fit = I_sel[order]
            E_fit = a + b * np.log10(np.clip(I_fit, 1e-12, None))

            ax.plot(E_fit, I_fit, "r-.", linewidth=1.5,
                    label=f"Tafel fit: {b*1000:.1f} mV/dec")

            ax.scatter(E_sel, I_sel, c="red", s=20, zorder=5,
                       label="Tafel used points")

            have_legend = True

    if have_legend:
        ax.legend()

    fig.tight_layout()

    # === save ===
    out_name = (
        f"{src.stem}_LSV_IR_compensated.png"
        if curve_type == "ir"
        else f"{src.stem}_LSV.png"
    )
    out_path = src.with_name(out_name)

    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    return_file(out_path.name)


regist_tool(lsv_plot_curve)
