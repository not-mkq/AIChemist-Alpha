# tools/lsv_halfwave_from_curve.py
"""
从 LSV 曲线中计算半波电位（half-wave potential）。

约定：
- 输入 CSV 至少包含两列：
    potential_V, current_density_mAcm2
  如果存在列名为 potential_ir_V（不区分大小写），且 use_ir_potential=True，
  则优先使用该列作为电位列。
- 半波电位定义：
    先在指定电位窗口内（如未指定则使用全程）寻找极限电流 i_lim（可用绝对值），
    然后在同一窗口内寻找 |i| = 0.5 * |i_lim| 对应的电位（线性插值）。
"""

from pathlib import Path
import csv
import json

from tool_runtime import (
    regist_tool,
    return_value,
    return_file,
)


def _find_col_index(header: list[str], candidates: list[str], default_idx: int) -> int:
    """
    在 header 中根据候选关键字（大小写不敏感）寻找列索引。
    找不到时返回 default_idx。
    """
    lower = [h.strip().lower() for h in header]
    for cand in candidates:
        cand = cand.lower()
        for i, h in enumerate(lower):
            if cand in h:
                return i
    return default_idx


def lsv_halfwave_from_curve(
    tool_name: str,
    source_csv: str,
    use_abs_current: bool = True,
    use_ir_potential: bool = True,
    window_min_potential: float | None = None,
    window_max_potential: float | None = None,
    encoding: str = "utf-8",
) -> None:
    """
    从 LSV 曲线中计算半波电位 half_wave_potential_v。
    - use_abs_current: 是否使用 |i| 来定义极限电流（默认 True）
    - use_ir_potential: 若 CSV 中存在 potential_ir_V，则优先使用该列作为电位
    - window_min_potential / window_max_potential: 可选电位窗口，限制 i_lim 计算范围
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    with src.open("r", encoding=encoding, newline="") as f_in:
        reader = csv.reader(f_in)

        # 读取表头
        first_row = next(reader, None)
        if first_row is None:
            raise ValueError("输入 CSV 为空")

        header = [c.strip() for c in first_row]
        if len(header) < 2:
            raise ValueError("输入 CSV 至少需要两列（电位、电流/电流密度）")

        lower = [h.lower() for h in header]

        # 选择电位列：
        # 1) 如果有 potential_ir_v 且 use_ir_potential=True，则优先使用
        # 2) 否则按 potential_v / potential 匹配
        if use_ir_potential and "potential_ir_v" in lower:
            pot_idx = lower.index("potential_ir_v")
        else:
            pot_idx = _find_col_index(
                header,
                candidates=["potential_v", "potential"],
                default_idx=0,
            )

        # 选择电流列：current_density_ma / current_density / current_a / current
        cur_idx = _find_col_index(
            header,
            candidates=[
                "current_density_ma", "current_density",
                "current_a", "current"
            ],
            default_idx=1,
        )

        potentials: list[float] = []
        currents: list[float] = []

        for row in reader:
            if not row:
                continue
            if len(row) <= max(pot_idx, cur_idx):
                raise ValueError("数据行列数不足，无法获取电位和电流")

            p = float(row[pot_idx])
            i = float(row[cur_idx])

            potentials.append(p)
            currents.append(i)

    if len(potentials) < 2:
        raise ValueError("有效数据点不足，无法计算半波电位")

    # 电位窗口：若未指定，则使用全程
    if window_min_potential is None:
        window_min_potential = min(potentials)
    if window_max_potential is None:
        window_max_potential = max(potentials)
    if window_min_potential >= window_max_potential:
        raise ValueError("电位窗口非法：window_min_potential >= window_max_potential")

    # 在窗口内筛选数据点
    region_p: list[float] = []
    region_i: list[float] = []
    for p, i in zip(potentials, currents):
        if window_min_potential <= p <= window_max_potential:
            region_p.append(p)
            region_i.append(i)

    if len(region_p) < 2:
        raise ValueError("电位窗口内有效数据点不足，无法计算半波电位")

    # 极限电流 i_lim：默认使用 |i|
    if use_abs_current:
        amps = [abs(i) for i in region_i]
    else:
        amps = list(region_i)

    i_lim = max(amps)
    if i_lim <= 0.0:
        raise ValueError("极限电流 i_lim <= 0，无法计算半波电位")

    target_i = 0.5 * i_lim

    # 在窗口内寻找 |i| = 0.5 * |i_lim| 的交点，线性插值
    half_potential: float | None = None

    for idx in range(len(region_p) - 1):
        y1 = amps[idx]
        y2 = amps[idx + 1]
        x1 = region_p[idx]
        x2 = region_p[idx + 1]

        # 精确命中
        if y1 == target_i:
            half_potential = x1
            break

        # 跨越 target
        if (y1 - target_i) * (y2 - target_i) < 0.0:
            # 线性插值
            half_potential = x1 + (x2 - x1) * (target_i - y1) / (y2 - y1)
            break

    if half_potential is None:
        raise ValueError("未在电位窗口内找到半波电位交点（|i| = 0.5 * |i_lim|）")

    # 1. 主结果：半波电位，直接作为 result 的值返回
    return_value(half_potential)

    # 2. 详细报告：写入 JSON 文件，包含参数与辅助结果
    report = {
        "half_wave_potential_v": half_potential,
        "limiting_current_abs": i_lim,
        "target_current_abs": target_i,
        "use_abs_current": use_abs_current,
        "use_ir_potential": use_ir_potential,
        "window_min_potential": window_min_potential,
        "window_max_potential": window_max_potential,
        "data_point_count_total": len(potentials),
        "data_point_count_window": len(region_p),
        "source_csv": src.name,
        "potential_column": header[pot_idx],
        "current_column": header[cur_idx],
    }

    report_path = src.with_name(f"{src.stem}-lsv-halfwave.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return_file(report_path.name)


regist_tool(lsv_halfwave_from_curve)
