from pathlib import Path
import re

from tool_runtime import (
    regist_tool,
    return_file,
)


def _looks_number(s: str) -> bool:
    """判断一个字符串是不是数字（支持科学计数法）"""
    s = s.strip()
    if not s:
        return False
    # 简单正则：123, -0.12, 1e-3, -2.5E+4
    return bool(re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", s))


def _split_line(line: str):
    """用于检测的拆分：返回 (tokens, delim)"""
    if "\t" in line:
        return [p.strip() for p in line.split("\t")], "\t"
    if ";" in line:
        return [p.strip() for p in line.split(";")], ";"
    if "," in line:
        return [p.strip() for p in line.split(",")], ","
    # 没有明显分隔符就按空白拆
    return line.split(), None


def _looks_data_row(line: str) -> bool:
    """判断该行是否像“数据行”：大部分字段是数字"""
    tokens, _ = _split_line(line)
    tokens = [t for t in tokens if t]
    if len(tokens) < 2:
        return False
    num_cnt = sum(1 for t in tokens if _looks_number(t))
    return num_cnt >= max(2, int(len(tokens) * 0.6))


def _looks_header_row(line: str) -> bool:
    """判断该行是否像“表头行”：有分隔符，且包含字母字段"""
    tokens, delim = _split_line(line)
    if delim is None:
        return False
    tokens = [t for t in tokens if t]
    if len(tokens) < 2:
        return False
    # 至少有一个字段包含字母（Potential/V, Current/A 等）
    has_alpha = any(any(ch.isalpha() for ch in t) for t in tokens)
    return has_alpha


def extract_csv(
    tool_name: str,
    source_txt: str,
    start_line: int | None = None,
    encoding: str = "utf-8",
) -> None:
    """
    从原始 LSV 文件中提取数据区，转存为标准 CSV。
    """
    src = Path(source_txt)

    # 读取所有行
    lines = src.read_text(encoding=encoding).splitlines()

    # ---- Step 1: 决定数据起始行（0-based index） ----
    if start_line is not None:
        # 用户手动给的是 1-based，这里转成 0-based 索引
        start_idx = max(0, int(start_line) - 1)
    else:
        # 自动检测：
        # 1）优先找“表头行 + 下一行是数据行”的组合
        start_idx = 0
        found = False

        n = len(lines)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue

            if _looks_header_row(stripped):
                # 找下一行非空非注释，检查是否像数据行
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and _looks_data_row(lines[j]):
                    start_idx = i
                    found = True
                    break

        # 2）如果没找到，就退化：从上往下找第一行“像数据行”的
        if not found:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if _looks_data_row(stripped):
                    start_idx = i
                    found = True
                    break

        # 3）还找不到就保持 0（几乎不可能，但做个兜底）
        # start_idx 已经默认为 0

    data_lines = lines[start_idx:]

    # ---- Step 2: 粗略检测分隔符，并统一转成逗号分隔 ----
    first_data = ""
    for line in data_lines:
        if line.strip():
            first_data = line
            break

    if "\t" in first_data:
        delim = "\t"
    elif ";" in first_data:
        delim = ";"
    elif "," in first_data:
        delim = ","
    else:
        # 退化为按任意空白分隔
        delim = None

    # 框架现在负责重命名，工具只需生成一个临时文件名
    out_name = "extracted_data.csv"
    out_path = Path(out_name)

    out_rows = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        for line in data_lines:
            if not line.strip():
                continue
            if delim is None:
                parts = line.split()
            else:
                parts = line.split(delim)
            parts = [p.strip() for p in parts]
            if not any(parts):
                continue
            f.write(",".join(parts) + "\n")
            out_rows += 1

    return_file(out_name)


regist_tool(extract_csv)
