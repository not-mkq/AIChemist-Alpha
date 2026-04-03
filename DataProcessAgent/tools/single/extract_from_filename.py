import re
from pathlib import Path
from tool_runtime import (
    regist_tool,
    return_value,
    return_json,
)

def extract_from_filename(
    tool_name: str,
    source_file: str,
    regex_pattern: str,
    mode: str = "regex",
) -> None:
    """
    根据正则表达式从文件名中提取字段并写入结果列。
    """
    # 获取原始文件名
    filename = Path(source_file).name
    
    pattern_to_use = regex_pattern
    if mode == "wildcard":
        # wildcard 模式：将 * 转换为 (.*) 并转义其他字符
        # re.escape 会把 * 转义为 \*，所以我们替换 \* 为 (.*)
        pattern_to_use = re.escape(regex_pattern).replace(r"\*", r"(.*)")
        print(f"[TOOL] Converted wildcard '{regex_pattern}' to regex '{pattern_to_use}'")

    match = re.search(pattern_to_use, filename)
    
    if not match:
        raise ValueError(f"Pattern '{regex_pattern}' (mode={mode}) not found in filename: {filename}")

    # 1. 优先处理命名分组 (Named Groups)
    group_dict = match.groupdict()
    if group_dict:
        # 如果存在命名分组，将其作为字典返回
        # 结果表会产生 result_col.group_name 形式的列
        return_json(group_dict)
        print(f"[TOOL] Extracted named groups from '{filename}': {group_dict}")
        return

    # 2. 决定结果值
    res_val = None
    groups = match.groups()
    if groups:
        # 如果有多个普通分组但没命名，默认返回第一个
        res_val = groups[0]
        print(f"[TOOL] Extracted group 1 from '{filename}': {res_val}")
    else:
        # 3. 没有任何分组，返回整个匹配内容
        res_val = match.group(0)
        print(f"[TOOL] Extracted full match from '{filename}': {res_val}")

    if res_val is not None:
        return_value(res_val)

regist_tool(extract_from_filename)
