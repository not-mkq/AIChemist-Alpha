# tools/lsv_ir_compensate_csv.py
"""
对归一化后的 LSV CSV 曲线应用 IR 补偿：
- 输入：`lsv_normalize_csv` 输出的 `{basename}_lsvnorm.csv`
  约定至少包含两列，典型为：
    potential_V, current_density_mAcm2
- 参数：r_solution_ohm (Ω)
- 输出：{basename}_ir.csv，追加一列：
    potential_ir_V
  其中：
    potential_ir_V = potential_V - current * r_solution_ohm
"""

from pathlib import Path
import csv

from tool_runtime import (
    regist_tool,
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


def lsv_ir_compensate_csv(
    tool_name: str,
    source_csv: str,
    r_solution_ohm: float,
    encoding: str = "utf-8",
) -> None:
    """
    对 LSV CSV 曲线进行 IR 补偿，生成附加电位列 potential_ir_V。
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    # 输出文件名：{basename}_ir.csv
    out_path = src.with_name(f"{src.stem}_ir.csv")

    with src.open("r", encoding=encoding, newline="") as f_in, \
            out_path.open("w", encoding="utf-8", newline="") as f_out:

        reader = csv.reader(f_in)
        writer = csv.writer(f_out)

        # 读取表头
        first_row = next(reader, None)
        if first_row is None:
            raise ValueError("输入 CSV 为空")

        header = [c.strip() for c in first_row]
        if len(header) < 2:
            raise ValueError("输入 CSV 至少需要两列（电位、电流/电流密度）")

        # 决定电位列 / 电流列索引：
        # - 优先按列名匹配
        # - 找不到就退化为第 0 / 1 列
        pot_idx = _find_col_index(
            header,
            candidates=["potential_v", "potential"],
            default_idx=0,
        )
        cur_idx = _find_col_index(
            header,
            candidates=[
                "current_density_ma", "current_density",
                "current_a", "current"
            ],
            default_idx=1,
        )

        # 新表头：在原有列后追加 potential_ir_V
        ir_col_name = "potential_ir_V"
        if ir_col_name in header:
            # 防止重复列名，简单加个后缀
            ir_col_name = "potential_ir_V2"
        writer.writerow(header + [ir_col_name])

        # 逐行应用 IR 补偿
        for row in reader:
            if not row:
                continue
            # padding 一下，保证索引存在
            if len(row) <= max(pot_idx, cur_idx):
                raise ValueError("数据行列数不足，无法获取电位和电流")

            potential = float(row[pot_idx])
            current = float(row[cur_idx])

            # 简单 IR 补偿：E_ir = E - I * R
            potential_ir = potential - current * r_solution_ohm

            out_row = list(row) + [f"{potential_ir:.8g}"]
            writer.writerow(out_row)

    # 返回生成的 IR 补偿 CSV 文件
    return_file(out_path.name)


regist_tool(lsv_ir_compensate_csv)
