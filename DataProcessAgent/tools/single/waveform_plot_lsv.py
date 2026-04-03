"""
waveform_plot_lsv

根据 LSV 质量报告 + CSV 波形数据，绘制带局部问题高亮的波形诊断图。

输入：
- source_csv: LSV 数据 CSV，至少包含电位列和电流列
- quality_report: 第一步工具生成的质量报告 JSON，假设包含：
  - potential_col: 电位列名
  - current_col: 电流列名
  - n_points, noise_ratio, jump_ratio, flags, quality 等全局信息
  - local_issues: 列表，用于描述局部问题区段

local_issues 的兼容格式（索引基于数据行，0 起）：
- 整数：表示单点问题，例如 120
- 字典形式：
  {
    "index": 300,            # 单点
    "reason": "电流跳变",    # 可选：问题说明
    "type": "jump"           # 可选：问题类型
  }
  或
  {
    "start_index": 120,
    "end_index": 150,
    "reason": "高频噪声",
    "type": "noise"
  }
  也兼容键名 "start"/"end"。

输出：
- 在与 source_csv 同目录下生成 {stem}_waveform.png
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib

# 使用无交互后端，防止在服务器环境出问题
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from tool_runtime import regist_tool, return_file


def _load_quality_report(path: Path, encoding: str = "utf-8") -> Dict[str, Any]:
    with path.open("r", encoding=encoding) as f:
        data = json.load(f)
    # 如果将来支持 list 包一层，这里顺手展开一下
    if isinstance(data, list) and data:
        # 取第一个元素作为报告
        if isinstance(data[0], dict):
            return data[0]
    if not isinstance(data, dict):
        raise ValueError(f"质量报告 JSON 结构异常：期望 dict，实际为 {type(data)}")
    return data


def _extract_local_issue_ranges(
    issues: Any,
    n_points: int,
) -> List[Tuple[int, int, str]]:
    """
    将 quality_report['local_issues'] 规范化成 (start, end, label) 三元组列表。

    - start, end: 闭区间索引，都会被 clamp 到 [0, n_points-1]
    - label: 文本标签（reason/type/自动编号）
    """
    ranges: List[Tuple[int, int, str]] = []

    if not issues:
        return ranges
    if not isinstance(issues, list):
        # 容错：如果是单个对象也包一层
        issues = [issues]

    for idx, item in enumerate(issues):
        start_idx: int | None = None
        end_idx: int | None = None
        label = ""

        if isinstance(item, int):
            start_idx = end_idx = int(item)
        elif isinstance(item, dict):
            # 先各种 key 猜一遍
            if "index" in item:
                start_idx = end_idx = int(item["index"])
            else:
                start_idx = item.get("start_index")
                end_idx = item.get("end_index")

                if start_idx is None and "start" in item:
                    start_idx = item["start"]
                if end_idx is None and "end" in item:
                    end_idx = item["end"]

            # label 尝试 reason / type / label / 自动编号
            label = (
                item.get("reason")
                or item.get("type")
                or item.get("label")
                or f"issue-{idx + 1}"
            )
        else:
            # 其他类型先忽略
            continue

        if start_idx is None:
            continue
        if end_idx is None:
            end_idx = start_idx

        start_idx = max(0, int(start_idx))
        end_idx = max(0, int(end_idx))
        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx

        if start_idx >= n_points:
            continue
        end_idx = min(n_points - 1, end_idx)

        ranges.append((start_idx, end_idx, label))

    return ranges


def _load_lsv_csv(
    csv_path: Path,
    potential_col: str,
    current_col: str,
    encoding: str = "utf-8",
) -> Tuple[List[float], List[float]]:
    potentials: List[float] = []
    currents: List[float] = []

    with csv_path.open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        if potential_col not in reader.fieldnames or current_col not in reader.fieldnames:
            raise KeyError(
                f"CSV 中缺少指定列：potential_col='{potential_col}', current_col='{current_col}', "
                f"现有列为：{reader.fieldnames}"
            )

        for row in reader:
            # 空行 / 缺失值跳过
            if row.get(potential_col) in (None, "") or row.get(current_col) in (None, ""):
                continue
            potentials.append(float(row[potential_col]))
            currents.append(float(row[current_col]))

    if not potentials:
        raise ValueError("CSV 中没有有效的数据点（检查列名和数据行）。")

    return potentials, currents


def waveform_plot_lsv(
    tool_name: str,
    source_csv: str,
    quality_report: str,
    use_quality_cols: bool = True,
    potential_col: str | None = None,
    current_col: str | None = None,
    fig_width: float | None = None,
    fig_height: float | None = None,
    dpi: int | None = None,
    highlight_alpha: float | None = None,
    encoding: str = "utf-8",
) -> None:
    """
    入口函数：由运行时框架调用。

    参数说明见 template；这里不做严格校验，缺失参数交给上层框架处理。
    """
    csv_path = Path(source_csv)
    report_path = Path(quality_report)

    report = _load_quality_report(report_path, encoding=encoding)

    # 全局信息（有就用，没有就给默认）
    n_points = int(report.get("n_points", 0))
    noise_ratio = float(report.get("noise_ratio", 0.0))
    jump_ratio = float(report.get("jump_ratio", 0.0))
    quality = str(report.get("quality", "unknown"))
    flags = report.get("flags") or {}
    local_issues_raw = report.get("local_issues", [])

    # 解析列名优先级：
    # 1) use_quality_cols=True 时，优先使用报告中的 potential_col/current_col
    # 2) 其次使用函数参数 potential_col/current_col
    # 3) 再不行就回退到常见列名
    report_p_col = report.get("potential_col")
    report_i_col = report.get("current_col")

    if use_quality_cols:
        p_col = report_p_col or potential_col
        i_col = report_i_col or current_col
    else:
        p_col = potential_col or report_p_col
        i_col = current_col or report_i_col

    if not p_col:
        p_col = "Potential/V"
    if not i_col:
        # 尝试电流 / 电流密度两种典型命名
        i_col = "Current/A"

    potentials, currents = _load_lsv_csv(csv_path, p_col, i_col, encoding=encoding)

    # 如果质量报告里的 n_points 没填，尝试用实际长度补上
    if n_points <= 0:
        n_points = len(potentials)

    issue_ranges = _extract_local_issue_ranges(local_issues_raw, n_points)

    # 图像参数
    fw = fig_width or 8.0
    fh = fig_height or 4.5
    dpi_val = dpi or 150
    alpha_val = 0.15 if highlight_alpha is None else float(highlight_alpha)

    fig, ax = plt.subplots(figsize=(fw, fh), dpi=dpi_val)

    # 先画整体波形
    ax.plot(potentials, currents, linewidth=1.2, label="waveform")

    # 高亮局部问题区段
    for idx, (start, end, label) in enumerate(issue_ranges):
        if start >= len(potentials):
            continue
        end = min(end, len(potentials) - 1)
        seg_x = potentials[start : end + 1]
        seg_y = currents[start : end + 1]

        # 覆盖一条粗线
        ax.plot(seg_x, seg_y, linewidth=2.0, color="#d62728", label=None if idx > 0 else "local issue")

        # 可选的背景高亮
        if alpha_val > 0:
            x_min = min(seg_x)
            x_max = max(seg_x)
            ax.axvspan(x_min, x_max, color="#d62728", alpha=alpha_val)

    # 质量摘要文本
    summary_lines = [
        f"quality: {quality}",
        f"n_points: {n_points}",
        f"noise_ratio: {noise_ratio:.3g}",
        f"jump_ratio: {jump_ratio:.3g}",
    ]

    if isinstance(flags, dict):
        active_flags = [k for k, v in flags.items() if v]
        if active_flags:
            summary_lines.append("flags: " + ", ".join(active_flags))

    ax.text(
        0.02,
        0.98,
        "\n".join(summary_lines),
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=9,
        bbox=dict(boxstyle="round", fc="white", ec="none", alpha=0.8),
    )

    ax.set_xlabel(p_col)
    ax.set_ylabel(i_col)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)

    title = f"{csv_path.name} waveform ({quality})"
    ax.set_title(title)

    # 把图例放在合适位置（如果有 local issue）
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best", fontsize=9)

    fig.tight_layout()

    out_path = csv_path.with_name(f"{csv_path.stem}_waveform.png")
    fig.savefig(out_path, dpi=dpi_val)
    plt.close(fig)

    # 返回输出文件给框架
    return_file(out_path.name)


# 注册工具
regist_tool(waveform_plot_lsv, "waveform_plot_lsv")
