# tools/merge/result_aggregator.py
"""
结果列汇总工具 (Merge Tool)

功能：
1. 接收 10 个来自结果列的数值列表。
2. 第一个列表为必填，其余 9 个为可选。
3. 自动识别列表中的 Item/Batch 名称。
4. 将所有数值合并对齐，输出为一个汇总 CSV 文件。
"""

from __future__ import annotations

import csv
from typing import List, Any, Optional

from merge_runtime import regist_merge_tool, merge_return_file

def result_aggregator(
    tool_name: str,
    # 10 个输入参数 (由 merge_runtime 自动解析为 List)
    col0_data: List[Any],
    col1_data: Optional[List[Any]] = None,
    col2_data: Optional[List[Any]] = None,
    col3_data: Optional[List[Any]] = None,
    col4_data: Optional[List[Any]] = None,
    col5_data: Optional[List[Any]] = None,
    col6_data: Optional[List[Any]] = None,
    col7_data: Optional[List[Any]] = None,
    col8_data: Optional[List[Any]] = None,
    col9_data: Optional[List[Any]] = None,
    
    # 列名映射 (可选，用于 CSV 表头)
    col0_name: str = "Value0",
    col1_name: str = "Value1",
    col2_name: str = "Value2",
    col3_name: str = "Value3",
    col4_name: str = "Value4",
    col5_name: str = "Value5",
    col6_name: str = "Value6",
    col7_name: str = "Value7",
    col8_name: str = "Value8",
    col9_name: str = "Value9",
    
    output_filename: str = "aggregated_results.csv"
) -> None:
    # 1. 准备数据结构
    # 我们假设 col0_data 是必填的，以此为基准长度
    n = len(col0_data)
    if n == 0:
        print("[AGGREGATOR] Warning: col0_data is empty.")
        
    # 组装有效的列
    active_cols = [(col0_name, col0_data)]
    
    optionals = [
        (col1_name, col1_data), (col2_name, col2_data), (col3_name, col3_data),
        (col4_name, col4_data), (col5_name, col5_data), (col6_name, col6_data),
        (col7_name, col7_data), (col8_name, col8_data), (col9_name, col9_data)
    ]
    
    for name, data in optionals:
        if data is not None and len(data) > 0:
            # 补齐长度
            if len(data) < n:
                data = list(data) + [None] * (n - len(data))
            active_cols.append((name, data))

    # 2. 写入 CSV
    with open(output_filename, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        # 写入表头
        writer.writerow([c[0] for c in active_cols])
        # 写入数据行
        for i in range(n):
            row = []
            for name, data in active_cols:
                row.append(data[i])
            writer.writerow(row)

    # 3. 返回文件
    merge_return_file(output_filename)

regist_merge_tool(result_aggregator)
