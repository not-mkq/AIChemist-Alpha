# tools/lsv_targets_from_csv.py
"""
从普通的 LSV CSV（电位 + 电流/电流密度两列）中，
提取给定目标电流密度下的电位（无 IR 补偿）。

- 输入：通常为 `lsv_normalize_csv` 输出的 `{basename}_lsvnorm.csv`
至少包含两列，例如：
    potential_V, current_density_mAcm2

- 参数：
- target_current: 例如 "10" 或 "5,10"
- use_abs_current: 是否按 |j| 匹配目标电流

- 输出：
- {stem}_targets.csv，包含：
    target_current_mAcm2, potential_V
- result_col：一个 dict，key 形如：
    "potential_at_10mAcm2", ...
"""

from pathlib import Path
import csv
from typing import List, Dict

from tool_runtime import (
    regist_tool,
    return_file,
    return_value,
)


def _find_col_index(header: list[str], candidates: list[str], default_idx: int) -> int:
    lower = [h.strip().lower() for h in header]
    for cand in candidates:
        cand = cand.lower()
        for i, h in enumerate(lower):
            if cand in h:
                return i
    return default_idx


def _parse_target_currents(spec: str) -> List[float]:
    if not spec:
        raise ValueError("target_current 不能为空")
    vals: List[float] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        vals.append(float(part))
    if not vals:
        raise ValueError(f"无法从 target_current={spec!r} 中解析任何数值")
    return vals


def _find_potential_at_current(
    potentials: List[float],
    currents: List[float],
    target: float,
    use_abs_current: bool,
) -> float:
    """
    在 I-E 曲线中寻找目标电流对应的电位（线性插值）。
    """
    if len(potentials) != len(currents):
        raise ValueError("电位、电流列长度不一致")
    if len(currents) < 2:
        raise ValueError("数据点太少，无法插值求解目标电流点")


    # **换算：mA/cm² → A/cm²**
    target_A = target / 1000.0
    def norm_i(i: float) -> float:
        return abs(i) if use_abs_current else i

    j = [norm_i(c) for c in currents]

    for i in range(len(j) - 1):
        j0, j1 = j[i], j[i + 1]
        if j0 == target_A:
            return potentials[i]
        if j1 == target_A:
            return potentials[i + 1]

        diff0 = j0 - target_A
        diff1 = j1 - target_A

        if diff0 * diff1 > 0:
            continue
        if j1 == j0:
            continue

        t = (target_A - j0) / (j1 - j0)
        e = potentials[i] + t * (potentials[i + 1] - potentials[i])
        return e

    raise ValueError(f"曲线未达到目标电流 {target} mA/cm²，无法求解电位")


def lsv_targets_from_csv(
    tool_name: str,
    source_csv: str,
    target_current: str = "10",
    use_abs_current: bool = True,
    encoding: str | None = "utf-8",
) -> None:
    """
    从无 IR 的 LSV CSV 中提取目标电流点的电位。
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    enc = encoding or "utf-8"
    targets = _parse_target_currents(target_current)

    with src.open("r", encoding=enc, newline="") as f:
        reader = csv.reader(f)
        first_row = next(reader, None)
        if first_row is None:
            raise ValueError("输入 CSV 为空")

        header = [c.strip() for c in first_row]
        if len(header) < 2:
            raise ValueError("输入 CSV 至少需要两列（电位、电流/电流密度）")

        pot_idx = _find_col_index(
            header,
            candidates=["potential_v", "potential"],
            default_idx=0,
        )
        cur_idx = _find_col_index(
            header,
            candidates=[
                "current_density_ma", "current_density",
                "current_ma", "current_a", "current"
            ],
            default_idx=1,
        )

        potentials: List[float] = []
        currents: List[float] = []

        for row in reader:
            if not row:
                continue
            if len(row) <= max(pot_idx, cur_idx):
                raise ValueError("数据行列数不足，无法读取电位 / 电流")

            potentials.append(float(row[pot_idx]))
            currents.append(float(row[cur_idx]))

    metrics: Dict[str, float] = {}
    out_path = src.with_name(f"{src.stem}_targets.csv")

    with out_path.open("w", encoding="utf-8", newline="") as f_out:
        writer = csv.writer(f_out)
        writer.writerow(["target_current_mAcm2", "potential_V"])

        for tc in targets:
            e = _find_potential_at_current(
                potentials=potentials,
                currents=currents,
                target=tc,
                use_abs_current=use_abs_current,
            )
            metrics[f"potential_at_{tc}mAcm2"] = e
            writer.writerow([tc, f"{e:.8g}"])

    return_file(out_path.name)
    return_value(metrics)


regist_tool(lsv_targets_from_csv)
