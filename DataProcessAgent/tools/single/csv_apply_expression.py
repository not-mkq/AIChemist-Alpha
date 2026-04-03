# tools/single/csv_apply_expression.py
from pathlib import Path
import math
import csv

from tool_runtime import (
    regist_tool,
    return_file,
)

def _find_col_index(header: list[str], col_name: str) -> int:
    target = col_name.strip().lower()
    lower = [h.strip().lower() for h in header]
    for i, h in enumerate(lower):
        if h == target: return i
    for i, h in enumerate(lower):
        if target in h: return i
    raise ValueError(f"Cannot find column '{col_name}' in header: {header!r}")

def _parse_bind(spec: str | None) -> tuple[str, str] | None:
    if not spec or "@" not in spec: return None
    col, var = spec.split("@", 1)
    return col.strip(), var.strip()

def csv_apply_expression(
    tool_name: str,
    source_csv: str,
    expression: str,
    column: str | None = None,
    new_col_name: str | None = None,
    col_bind_1: str | None = None,
    col_bind_2: str | None = None,
    col_bind_3: str | None = None,
    col_bind_4: str | None = None,
    col_bind_5: str | None = None,
    encoding: str = "utf-8",
) -> None:
    src = Path(source_csv)
    # 框架现在负责重命名，工具只需生成一个临时文件名
    out_name = "processed_data.csv"
    out_path = Path(out_name)

    # 其余逻辑保持不变...
    bind_specs = [_parse_bind(x) for x in (col_bind_1, col_bind_2, col_bind_3, col_bind_4, col_bind_5)]
    bind_specs = [x for x in bind_specs if x is not None]
    col_name = (column or "").strip()
    op_col_enabled = bool(col_name)
    new_name = (new_col_name or "").strip()

    with src.open("r", encoding=encoding, newline="") as fin, \
         out_path.open("w", encoding="utf-8", newline="") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        header = [h.strip() for h in next(reader)]

        bind_col_indices = [(_find_col_index(header, c), v) for c, v in bind_specs]
        if op_col_enabled:
            op_idx = _find_col_index(header, col_name)
            if new_name: header[op_idx] = new_name
        else:
            if not new_name: raise ValueError("new_col_name is required when column is empty.")
            op_idx = len(header)
            header.append(new_name)

        writer.writerow(header)

        env = {"__builtins__": {}}
        safe_funcs = {"abs": abs, "min": min, "max": max, "round": round, 
                      "lg": math.log10, "log10": math.log10,
                      "ln": math.log, "log": math.log,
                      "exp": math.exp, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "pi": math.pi, "e": math.e,
                      "null": None, "true": True, "false": False}
        # 移除了 a, b, c, d, e 的显式赋值，它们现在会通过框架替换进 expression 字符串中
        base_vars = {**safe_funcs}

        for row in reader:
            if not row: continue
            if len(row) < len(header): row = row + [""] * (len(header) - len(row))
            vars_ = dict(base_vars)
            for idx, var in bind_col_indices: vars_[var] = float(row[idx])
            vars_["i"] = float(row[op_idx]) if op_col_enabled else None
            y = eval(expression, env, vars_)
            row[op_idx] = f"{float(y):.8g}"
            writer.writerow(row)

    # 按照 single_full_demo 规范，只需返回文件名字符串
    return_file(out_name)

regist_tool(csv_apply_expression)