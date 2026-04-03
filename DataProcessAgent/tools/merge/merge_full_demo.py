# merge-tools/merge_full_demo.py
"""
示例 Merge 工具，涵盖：
- 多个输入标签聚合成文件列表 (inputs_a / inputs_b)
- 从下一级结果表汇总来的文本向量 (summary_text) - 对应 input_cols
- 必填 / 可选运行参数
- 输出一个汇总报告文件 + 一段结果文本
"""

from pathlib import Path
from statistics import mean

from merge_runtime import regist_merge_tool, merge_return_file, merge_return_value


def merge_full_demo(
    tool_name: str,
    inputs_a: list[str],
    inputs_b: list[str],
    summary_text: list[str],
    weight: float,
    description: str,
    flag: bool = False,
    extra: str | None = None,
    prev_batch_score: str | None = None,
) -> None:
    """
    - inputs_a / inputs_b: 收到的文件路径列表（按 label 收集）
    - summary_text: 来自下一级结果表（input_cols）的一列文本向量
    - 统计文件个数与大小均值，写入报告
    - prev_batch_score: 通过 run_params 引用当前 scope 的结果列
    """
    counts = [len(inputs_a), len(inputs_b)]
    sizes_a = [Path(p).stat().st_size for p in inputs_a if Path(p).exists()]
    sizes_b = [Path(p).stat().st_size for p in inputs_b if Path(p).exists()]
    avg_a = mean(sizes_a) if sizes_a else 0
    avg_b = mean(sizes_b) if sizes_b else 0

    report = Path(f"{tool_name}_merge.txt")
    lines = [
        f"weight={weight}",
        f"description={description}",
        f"flag={flag}",
        f"extra={extra}",
        f"prev_batch_score={prev_batch_score}",
        f"inputs_a_count={counts[0]} avg_size={avg_a}",
        f"inputs_b_count={counts[1]} avg_size={avg_b}",
        f"summary_text_count={len(summary_text)}",
        f"summary_text_sample={summary_text[:3]}",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")

    merge_return_file(report.name)
    merge_return_value(report.read_text(encoding="utf-8"))


regist_merge_tool(merge_full_demo)
