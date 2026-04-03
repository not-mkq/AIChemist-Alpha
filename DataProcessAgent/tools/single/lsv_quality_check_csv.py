# tools/lsv_quality_check_csv.py
"""
LSV 数据质量检查工具（基于 CSV 的简化版本）

输入：
- source_csv: 已整理好的 LSV 数据 CSV，一般来自 lsv_normalize_csv 或其他前处理工具。
  默认会尝试自动识别电位列和电流列。

输出：
- 质量诊断 JSON 文件（默认：<basename>_quality.json）
  含：
    - 基本统计信息（点数、电位 / 电流范围）
    - 噪声相关指标（相对噪声）
    - 跳变相关指标（相对最大跳变）
    - 各规则是否触发
    - 最终质量等级（good / fair / poor）
    - 局部问题列表 local_issues:
        * 噪声段：
            {
              "start_index": 120,
              "end_index": 150,
              "reason": "高频噪声",
              "type": "noise"
            }
        * 跳变点：
            {
              "index": 300,
              "reason": "电流跳变",
              "type": "jump"
            }

  这里的 index / start_index / end_index 均以 CSV 数据行计数，
  去掉表头后，第一行数据为 index = 0。

返回值：
- 字符串质量等级： "good" / "fair" / "poor"
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List, Dict, Any

from tool_runtime import regist_tool, return_file, return_value


def _pick_column(
    fieldnames: List[str],
    preferred: List[str],
    fallback_index: int,
) -> str:
    """
    从字段名列表中选择一列：
    1. 先按 preferred 里的关键词模糊匹配（不区分大小写）
    2. 找不到就用 fallback_index 对应的列
    """
    if not fieldnames:
        raise ValueError("CSV 文件没有表头字段")

    lower_map = {name.lower(): name for name in fieldnames}

    for key in preferred:
        key_lower = key.lower()
        # 完整匹配
        if key_lower in lower_map:
            return lower_map[key_lower]
        # 子串匹配
        for ln, raw in lower_map.items():
            if key_lower in ln:
                return raw

    # 兜底：按位置
    if fallback_index >= len(fieldnames):
        fallback_index = len(fieldnames) - 1
    return fieldnames[fallback_index]


def _compute_relative_noise(currents: List[float], window: int = 11) -> float:
    """
    计算一个非常粗糙的“相对噪声”：
    - 先做简单滑动平均，得到平滑曲线
    - 噪声 ~ 原始值 - 平滑值 的标准差
    - 再除以电流整体幅度 (max - min)，得到无量纲噪声比
    """
    n = len(currents)
    if n < 3:
        return 0.0

    if window < 3:
        window = 3
    if window > n:
        window = n if n % 2 == 1 else n - 1
        if window < 3:
            window = 3

    half = window // 2
    smooth: List[float] = []
    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)
        seg = currents[left:right]
        smooth.append(sum(seg) / len(seg))

    # 噪声序列
    noise = [c - s for c, s in zip(currents, smooth)]
    mean_noise = sum(noise) / len(noise)
    var = sum((x - mean_noise) ** 2 for x in noise) / max(1, (len(noise) - 1))
    std_noise = var ** 0.5

    c_min = min(currents)
    c_max = max(currents)
    span = abs(c_max - c_min)

    if span <= 0:
        return 0.0

    return std_noise / span


def _compute_max_jump_ratio(currents: List[float]) -> float:
    """
    最大跳变比：
    - 计算相邻点的 |ΔI|
    - 取最大值 / (整体幅度 max(I) - min(I)) 作为跳变比
    """
    n = len(currents)
    if n < 2:
        return 0.0

    diffs = [abs(currents[i + 1] - currents[i]) for i in range(n - 1)]
    max_jump = max(diffs)

    c_min = min(currents)
    c_max = max(currents)
    span = abs(c_max - c_min)

    if span <= 0:
        return 0.0

    return max_jump / span


def _detect_local_issues(
    currents: List[float],
    current_span: float,
    local_noise_window: int,
    local_noise_factor: float,
    jump_warn: float,
) -> List[Dict[str, Any]]:
    """
    检测局部问题，返回 local_issues 列表。

    - 局部高频噪声：
        用滑动窗口在“电流差分”上计算局部 std，找出显著高于整体平均的窗口，
        合并连续窗口为区间，输出为 noise 段。
    - 电流跳变：
        若 |ΔI_i| > jump_warn * current_span，则认为 i+1 为跳变点。
    """
    issues: List[Dict[str, Any]] = []
    n = len(currents)

    # --- 局部噪声检测 ---
    if n >= 5 and current_span > 0:
        window = local_noise_window
        if window < 3:
            window = 3
        if window > n:
            window = n if n % 2 == 1 else n - 1
        if window >= 3:
            half = window // 2
            noise_scores: List[float] = []
            centers: List[int] = []

            # 以 center 为中心的窗口，统计差分的 std
            for center in range(half, n - half):
                left = center - half
                right = center + half
                seg = currents[left:right + 1]
                if len(seg) < 2:
                    continue
                diffs = [seg[j + 1] - seg[j] for j in range(len(seg) - 1)]
                mean_d = sum(diffs) / len(diffs)
                var_d = sum((d - mean_d) ** 2 for d in diffs) / max(1, (len(diffs) - 1))
                std_d = var_d ** 0.5
                noise_scores.append(std_d)
                centers.append(center)

            if noise_scores:
                mean_score = sum(noise_scores) / len(noise_scores)
                if mean_score > 0 and local_noise_factor > 0:
                    threshold = mean_score * local_noise_factor
                    high_centers = [
                        centers[i]
                        for i, score in enumerate(noise_scores)
                        if score > threshold
                    ]

                    if high_centers:
                        high_centers.sort()
                        grouped: List[tuple[int, int]] = []
                        run_start = high_centers[0]
                        prev = high_centers[0]

                        for c in high_centers[1:]:
                            if c == prev + 1:
                                prev = c
                            else:
                                grouped.append((run_start, prev))
                                run_start = c
                                prev = c
                        grouped.append((run_start, prev))

                        # 生成 noise 区间（限制一下最多几段，避免过多）
                        max_regions = 5
                        for center_start, center_end in grouped[:max_regions]:
                            start_index = max(0, center_start - half)
                            end_index = min(n - 1, center_end + half)
                            issues.append(
                                {
                                    "start_index": int(start_index),
                                    "end_index": int(end_index),
                                    "reason": "高频噪声",
                                    "type": "noise",
                                }
                            )

    # --- 跳变点检测 ---
    if n >= 2 and current_span > 0 and jump_warn > 0:
        diff_threshold = jump_warn * current_span
        for i in range(n - 1):
            if abs(currents[i + 1] - currents[i]) > diff_threshold:
                issues.append(
                    {
                        "index": int(i + 1),
                        "reason": "电流跳变",
                        "type": "jump",
                    }
                )

    return issues


def lsv_quality_check_csv(
    tool_name: str,
    source_csv: str,
    # 列名相关：一般不需要改，让工具自动猜
    potential_col: str | None = None,
    current_col: str | None = None,
    # 采样点数阈值
    min_points_warn: int = 50,
    min_points_bad: int = 20,
    # 相对噪声阈值
    noise_warn: float = 0.02,
    noise_bad: float = 0.05,
    # 跳变阈值
    jump_warn: float = 0.10,
    jump_bad: float = 0.20,
    # 局部诊断相关参数
    local_noise_window: int = 11,
    local_noise_factor: float = 3.0,
    # 输出 JSON 文件名（默认：<basename>_quality.json）
    output_json: str | None = None,
) -> None:
    """
    LSV 质量诊断主函数（工具入口）。

    参数说明（可在 template 里暴露给前端）：
    - potential_col / current_col:
        指定电位 / 电流列名；留空让工具自动识别。
    - min_points_warn / min_points_bad:
        低于 bad 直接判为 poor；介于 bad 和 warn 之间至少降到 fair。
    - noise_warn / noise_bad:
        相对噪声（0~1 之间，一般 <0.05 比较干净）。
    - jump_warn / jump_bad:
        相对最大跳变（0~1 之间，大跳变说明有尖峰或接触不良等）。
    - local_noise_window / local_noise_factor:
        局部噪声检测窗口及阈值因子，用于生成 local_issues 中的噪声段。
    """
    csv_path = Path(source_csv)

    # 读 CSV
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            raise ValueError("CSV 文件没有表头，无法进行质量诊断")

        # 选择电位列
        if potential_col is None:
            potential_col = _pick_column(
                fieldnames,
                preferred=["potential_V", "potential", "E/V", "E(V)", "E"],
                fallback_index=0,
            )
        if current_col is None:
            current_col = _pick_column(
                fieldnames,
                preferred=[
                    "current_density_mAcm2",
                    "current_density_abs_mAcm2",
                    "current_A",
                    "current",
                    "I/A",
                    "Current/A",
                ],
                fallback_index=1 if len(fieldnames) > 1 else 0,
            )

        potentials: List[float] = []
        currents: List[float] = []

        for row in reader:
            # 不做 try/except，数据有问题就让它抛错
            p = float(row[potential_col])
            c = float(row[current_col])
            potentials.append(p)
            currents.append(c)

    n_points = len(potentials)

    if n_points == 0:
        raise ValueError("CSV 中没有有效数据行")

    # 基本统计
    p_min = min(potentials)
    p_max = max(potentials)
    c_min = min(currents)
    c_max = max(currents)
    p_span = p_max - p_min
    c_span = c_max - c_min

    # 噪声与跳变
    noise_ratio = _compute_relative_noise(currents)
    jump_ratio = _compute_max_jump_ratio(currents)

    # 规则判定
    flags = {
        "too_few_points_bad": n_points < min_points_bad,
        "too_few_points_warn": (min_points_bad <= n_points < min_points_warn),
        "noise_bad": noise_ratio > noise_bad,
        "noise_warn": (noise_warn < noise_ratio <= noise_bad),
        "jump_bad": jump_ratio > jump_bad,
        "jump_warn": (jump_warn < jump_ratio <= jump_bad),
    }

    # 质量等级：good / fair / poor
    quality = "good"
    if (
        flags["too_few_points_bad"]
        or flags["noise_bad"]
        or flags["jump_bad"]
    ):
        quality = "poor"
    elif (
        flags["too_few_points_warn"]
        or flags["noise_warn"]
        or flags["jump_warn"]
    ):
        quality = "fair"

    # 局部问题诊断（local_issues）
    local_issues = _detect_local_issues(
        currents=currents,
        current_span=c_span,
        local_noise_window=local_noise_window,
        local_noise_factor=local_noise_factor,
        jump_warn=jump_warn,
    )

    # 输出 JSON
    if output_json is None:
        out_path = csv_path.with_name(csv_path.stem + "_quality.json")
    else:
        out_path = Path(output_json)

    payload: Dict[str, Any] = {
        "source_csv": csv_path.name,
        "potential_col": potential_col,
        "current_col": current_col,
        "n_points": n_points,
        "potential_min": p_min,
        "potential_max": p_max,
        "potential_span": p_span,
        "current_min": c_min,
        "current_max": c_max,
        "current_span": c_span,
        "noise_ratio": noise_ratio,
        "jump_ratio": jump_ratio,
        "thresholds": {
            "min_points_warn": min_points_warn,
            "min_points_bad": min_points_bad,
            "noise_warn": noise_warn,
            "noise_bad": noise_bad,
            "jump_warn": jump_warn,
            "jump_bad": jump_bad,
        },
        "flags": flags,
        "quality": quality,
        "local_issues": local_issues,
        "local_params": {
            "local_noise_window": local_noise_window,
            "local_noise_factor": local_noise_factor,
        },
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 返回文件 & 质量等级
    return_file(out_path.name)
    return_value(quality)


regist_tool(lsv_quality_check_csv)
