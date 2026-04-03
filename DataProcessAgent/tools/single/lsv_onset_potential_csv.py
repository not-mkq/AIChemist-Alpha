# tools/lsv_onset_potential_csv.py
"""
从归一化后的 LSV CSV 曲线计算 onset 电位:
- 输入: LSV CSV (通常为 lsv_normalize_csv 的输出, 或再经过 IR 补偿)
- 输出: onset_potential_v (V)

支持选项:
- 是否使用 IR 补偿后的电位列 potential_ir_V
"""

from pathlib import Path
import csv

from tool_runtime import (
    regist_tool,
    return_value,
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


def _get_potential_index(header: list[str], use_ir_compensated: bool) -> int:
    """
    根据 use_ir_compensated 决定使用哪一列作为电位列。
    - use_ir_compensated = True 时, 必须找到 potential_ir_V 列, 否则报错。
    - False 时, 优先 potential_V / potential, 找不到退回第 0 列。
    """
    lower = [h.strip().lower() for h in header]

    if use_ir_compensated:
        # 严格要求存在 IR 列
        for i, h in enumerate(lower):
            if "potential_ir_v" == h or "potential_ir" == h:
                return i
        raise ValueError("需要 IR 补偿列 'potential_ir_V', 但在 CSV 表头中未找到该列")
    else:
        return _find_col_index(
            header,
            candidates=["potential_v", "potential"],
            default_idx=0,
        )


def _get_current_index(header: list[str]) -> int:
    """
    查找电流 / 电流密度列索引。找不到时退化为第 1 列。
    """
    return _find_col_index(
        header,
        candidates=[
            "current_density_ma", "current_density",
            "current_a", "current",
        ],
        default_idx=1,
    )


def _compute_onset_potential(
    potentials: list[float],
    currents: list[float],
    onset_current_mAcm2: float,
    use_abs_current: bool,
) -> float:
    """
    在电流曲线上寻找首次达到 onset_current 的位置, 使用线性插值得到 onset 电位。
    - potentials / currents 长度需 >= 2
    - currents 单位: A/cm²
    - onset_current_mAcm2 单位: mA/cm²
    """
    if len(potentials) != len(currents) or len(potentials) < 2:
        raise ValueError("数据点数量不足, 无法计算 onset 电位")

    # 输入是 mA/cm², 数据是 A/cm², 这里做一次单位换算
    target = float(onset_current_mAcm2) / 1000.0  # A/cm²

    prev_p = potentials[0]
    prev_i_raw = currents[0]
    prev_i = abs(prev_i_raw) if use_abs_current else prev_i_raw

    if prev_i >= target:
        return prev_p

    for p, i_raw in zip(potentials[1:], currents[1:]):
        i_val = abs(i_raw) if use_abs_current else i_raw

        if i_val >= target:
            if i_val == prev_i:
                return p
            ratio = (target - prev_i) / (i_val - prev_i)
            onset_potential = prev_p + ratio * (p - prev_p)
            return onset_potential

        prev_p = p
        prev_i = i_val

    raise ValueError("在给定曲线中, 电流未达到设定的 onset_current, 无法计算 onset 电位")


def lsv_onset_potential_csv(
    tool_name: str,
    source_csv: str,
    onset_current_mAcm2: float,
    use_ir_compensated: bool = False,
    use_abs_current: bool = True,
    encoding: str = "utf-8",
) -> None:
    """
    从 LSV CSV 中计算 onset_potential_v。
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    with src.open("r", encoding=encoding, newline="") as f_in:
        reader = csv.reader(f_in)
        first_row = next(reader, None)
        if first_row is None:
            raise ValueError("输入 CSV 为空")

        header = [c.strip() for c in first_row]
        if len(header) < 2:
            raise ValueError("输入 CSV 至少需要两列(电位, 电流/电流密度)")

        pot_idx = _get_potential_index(header, use_ir_compensated=use_ir_compensated)
        cur_idx = _get_current_index(header)

        potentials: list[float] = []
        currents: list[float] = []

        for row in reader:
            if not row:
                continue
            if len(row) <= max(pot_idx, cur_idx):
                raise ValueError("数据行列数不足, 无法获取电位和电流")

            p = float(row[pot_idx])
            i = float(row[cur_idx])
            potentials.append(p)
            currents.append(i)

        onset_p = _compute_onset_potential(
            potentials,
            currents,
            onset_current_mAcm2=onset_current_mAcm2,
            use_abs_current=bool(use_abs_current),
        )

    # 单一返回值: onset_potential_v
    return_value(onset_p)


regist_tool(lsv_onset_potential_csv)
