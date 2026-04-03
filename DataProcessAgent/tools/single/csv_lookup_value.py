# tools/csv_lookup_value.py
"""
通用 CSV 查表工具：

给定一个 CSV 文件、一列作为查找列 (x_col)、另一列作为返回列 (y_col)，
以及一个目标自变量值 x_value，本工具在表中查找 / 插值对应的 y 值。

- 输入：
  - source_csv: 任意 CSV 文件路径
  - x_col: 查找列名（支持模糊匹配，如 "potential", "E", "x" 等）
  - y_col: 返回列名（同上）
  - x_value: 目标自变量值（float）
  - interpolate: 是否启用线性插值（默认 True）

- 输出：
  - {stem}_lookup.csv，包含两列：
      <x_col>, <y_col>
    只有一行，即查表结果
  - result_col：一个 dict，key 形如：
      f"{y_col}_at_{x_col}_{x_value}"
"""

from pathlib import Path
import csv
from typing import List

from tool_runtime import (
    regist_tool,
    return_value,
)


def _find_col_index_by_name(header: list[str], col_name: str) -> int:
    """
    在 header 中根据给定列名做模糊匹配（大小写不敏感、子串匹配）。
    若存在多个匹配，以第一个为准；不存在则抛出 ValueError。
    """
    if not col_name:
        raise ValueError("列名不能为空")

    target = col_name.strip().lower()
    lower = [h.strip().lower() for h in header]

    # 先尝试完全相等
    for i, h in enumerate(lower):
        if h == target:
            return i

    # 再尝试子串包含
    for i, h in enumerate(lower):
        if target in h:
            return i

    raise ValueError(f"在表头中找不到匹配列名: {col_name!r}；表头为: {header!r}")


def _interpolate_y(
    xs: List[float],
    ys: List[float],
    x_target: float,
    interpolate: bool,
) -> float:
    """
    在 (xs, ys) 数据中查找 x_target 对应的 y。
    - 若刚好存在 xs[i] == x_target，直接返回 ys[i]
    - 否则在相邻点间做线性插值（要求 x_target 在数据范围内）
    - 若 interpolate=False，则只接受精确匹配，否则抛出 ValueError
    """

    if len(xs) != len(ys):
        raise ValueError("x 列和 y 列长度不一致")
    if len(xs) < 1:
        raise ValueError("数据点数量为 0")
    if len(xs) == 1:
        # 只有一个点时，只能做精确匹配
        if xs[0] == x_target:
            return ys[0]
        raise ValueError(
            f"仅有一个数据点，且 x={xs[0]} != 目标 x={x_target}，无法求值"
        )

    # 精确匹配优先
    for x, y in zip(xs, ys):
        if x == x_target:
            return y

    if not interpolate:
        raise ValueError(
            f"未在 x 列中找到精确的 x={x_target}，且 interpolate=False，无法求值"
        )

    # 线性插值：在相邻点间寻找 x_target 覆盖区间
    # 不要求 x 单调，只要能找到一个区间 [x0, x1] 包含目标即可
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        y0, y1 = ys[i], ys[i + 1]

        # 若区间两端等值且不等于目标，跳过
        if x0 == x1:
            continue

        # 判断 x_target 是否位于 [min(x0,x1), max(x0,x1)] 之间（包含边界）
        lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
        if not (lo <= x_target <= hi):
            continue

        # 线性插值 t ∈ [0, 1]
        t = (x_target - x0) / (x1 - x0)
        y = y0 + t * (y1 - y0)
        return y

    raise ValueError(
        f"目标 x={x_target} 不在数据范围内，或没有找到可用于插值的相邻点区间"
    )


def csv_lookup_value(
    tool_name: str,
    source_csv: str,
    x_col: str,
    y_col: str,
    x_value: float,
    encoding: str | None = "utf-8",
    interpolate: bool = True,
) -> None:
    """
    通用 CSV 查表主入口。
    """
    src = Path(source_csv)
    if not src.is_file():
        raise FileNotFoundError(f"源 CSV 文件不存在: {src}")

    enc = encoding or "utf-8"

    with src.open("r", encoding=enc, newline="") as f:
        reader = csv.reader(f)
        first_row = next(reader, None)
        if first_row is None:
            raise ValueError("输入 CSV 为空")

        header = [c.strip() for c in first_row]
        x_idx = _find_col_index_by_name(header, x_col)
        y_idx = _find_col_index_by_name(header, y_col)

        xs: List[float] = []
        ys: List[float] = []

        for row in reader:
            if not row:
                continue
            # 行长度不足，跳过或报错都可以；这里选报错，方便发现坏数据
            if len(row) <= max(x_idx, y_idx):
                raise ValueError(
                    f"数据行列数不足，无法读取 x/y，两列索引分别为 "
                    f"{x_idx}, {y_idx}，行内容: {row!r}"
                )
            try:
                xs.append(float(row[x_idx]))
                ys.append(float(row[y_idx]))
            except ValueError as e:
                # 有无法转换为 float 的值，抛错提醒
                raise ValueError(
                    f"无法将某行数据转换为浮点数：x={row[x_idx]!r}, y={row[y_idx]!r}"
                ) from e

    y_val = _interpolate_y(xs, ys, x_value, interpolate=interpolate)

    # 输出 CSV，只写一个点
    out_path = src.with_name(f"{src.stem}_lookup.csv")
    with out_path.open("w", encoding="utf-8", newline="") as f_out:
        writer = csv.writer(f_out)
        writer.writerow([x_col, y_col])
        writer.writerow([f"{x_value:.8g}", f"{y_val:.8g}"])

    # metrics key：简单拼一下，顺便把空格替换成下划线，避免结果列表里太奇怪
    def _sanitize(s: str) -> str:
        return s.replace(" ", "_")

    f"{_sanitize(y_col)}_at_{_sanitize(x_col)}_{x_value}"

    #return_file(out_path.name)
    return_value(f"{y_val:.8g}")


regist_tool(csv_lookup_value)
