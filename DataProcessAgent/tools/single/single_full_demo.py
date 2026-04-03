# tools/single_full_demo.py
"""
示例 Single 工具，涵盖：
- 多个输入标签（file_label）
- 必填/可选运行参数（int/float/bool/str）
- 输出文件 + 结果列
- 运行时上下文获取（project/batch/item/scope）
"""

from pathlib import Path

from tool_runtime import (
    regist_tool,
    return_file,
    return_value,
    get_project,
    get_batch,
    get_item,
)


def single_full_demo(
    tool_name: str,
    source_primary: str,
    source_secondary: str,
    alpha: int,
    temperature: float,
    note: str,
    dry_run: bool = False,
    extra_comment: str | None = None,
    ir_method: str = "mean_high_freq",
    retry_times: int | None = None,
    ratio: float = 1.0,
    prev_report_col: str | None = None,
    db_val: float | None = None,  # 新增：演示从数据库读取
) -> None:
    """
    - 读取输入文件信息
    - 结合参数和从数据库读取的 db_val
    - 输出一个固定命名的文件，测试框架重命名
    """
    report_name = "internal_report.txt"
    report = Path(report_name)
    
    lines = [
        f"Tool: {tool_name}",
        f"Alpha: {alpha}",
        f"DB Value: {db_val}",
        f"Note: {note}",
        f"Context: {get_project()}/{get_batch()}/{get_item()}"
    ]
    
    report.write_text("\n".join(lines), encoding="utf-8")

    # 工具只返回内部固定文件名
    # 真正的文件名由框架配置的 output_pattern 决定
    return_file(report_name)
    return_value(f"Processed with db_val={db_val}")


regist_tool(single_full_demo)
