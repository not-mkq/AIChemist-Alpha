# tools/lsv_normalize_csv.py
"""
LSV 专用归一化工具：
- 从 CSV 文件读取原始电位/电流数据（第一列 = 电位，第二列 = 电流）
- 对电位应用偏移（offset）
- 将电流换算为电流密度（mA/cm²），可选是否对电流取绝对值
- 输出标准格式 CSV：{basename}_lsvnorm.csv，包含两列：
  potential_V, current_density_mAcm2
"""

from pathlib import Path
import csv

from tool_runtime import (
    regist_tool,
    return_file,
)


def lsv_normalize_csv(
    tool_name: str,
    source_csv: str,
    potential_offset: float = 0.0,
    area_cm2: float = 1.0,
    use_abs_current: bool = True,
    current_in_mA: bool = False,
    encoding: str = "utf-8",
) -> None:
    """
    对 LSV CSV 数据进行电位偏移和电流密度归一化。

    参数
    ----
    tool_name : str
        运行时框架传入的工具实例名（不参与逻辑，只用于上下文）。
    source_csv : str
        上一步 extract_csv 生成的 CSV 文件路径。
        约定：第一列为电位 (V)，第二列为电流（默认单位 A）。
    potential_offset : float
        电位偏移量，单位 V。输出电位 = 原始电位 + potential_offset。
    area_cm2 : float
        电极几何面积，单位 cm²。电流密度 = 电流(mA) / area_cm2。
    use_abs_current : bool
        是否对电流取绝对值后再归一化。
    current_in_mA : bool
        如果为 True，则第二列电流单位视为 mA；否则视为 A 并在内部乘 1000 转为 mA。
    encoding : str
        文件编码，默认 utf-8。
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"Source CSV not found: {source_csv}")

    # 目标输出文件：{basename}_lsvnorm.csv
    out_path = src.with_name(f"{src.stem}_norm.csv")

    n_rows_in = 0
    n_rows_out = 0

    with src.open("r", encoding=encoding, newline="") as fin, \
            out_path.open("w", encoding="utf-8", newline="") as fout:

        reader = csv.reader(fin)
        writer = csv.writer(fout)

        # 统一写一个标准表头
        writer.writerow(["potential_V", "current_density_mAcm2"])

        for row in reader:
            # 跳过空行
            if not row or all((not col.strip() for col in row)):
                continue

            n_rows_in += 1

            # 要求至少有两列：电位、电流
            if len(row) < 2:
                # 太少就跳过这一行
                continue

            try:
                potential = float(row[0])
                current_raw = float(row[1])
            except ValueError:
                # 第一行如果是 header 或者有非数字内容，直接跳过
                continue

            # 电位偏移
            potential_shifted = potential + potential_offset

            # 处理电流单位：内部统一用 mA
            if current_in_mA:
                current_mA = current_raw
            else:
                current_mA = current_raw * 1000.0  # A -> mA

            # 取绝对值（可选）
            if use_abs_current:
                current_mA = abs(current_mA)

            # 电流密度 mA/cm²
            if area_cm2 <= 0:
                raise ValueError(f"area_cm2 must be positive, got {area_cm2}")
            current_density = current_mA / area_cm2

            writer.writerow([f"{potential_shifted:.8g}", f"{current_density:.8g}"])
            n_rows_out += 1

    # 返回生成的归一化 CSV 文件，并附带简单统计信息
    return_file(out_path.name)


regist_tool(lsv_normalize_csv)
