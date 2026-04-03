# tools/single/csv_filter_rows.py
import pandas as pd
from tool_runtime import (
    regist_tool,
    return_file,
)

def csv_filter_rows(
    tool_name: str,
    input_file: str,
    column: str | None = None,
    min_val: float | None = None,
    max_val: float | None = None,
    expression: str = "",
) -> None:
    """
    CSV 数据筛选工具：
    - 支持简单的数值区间筛选 (min_val <= col <= max_val)。
    - 支持复杂的逻辑表达式筛选 (如 "i > 0 and v < 1.2")。
    - 表达式优先级高于区间筛选。
    """
    df = pd.read_csv(input_file)

    if expression:
        try:
            df_filtered = df.query(expression)
        except Exception as e:
            raise ValueError(f"Filter expression error: {e}")
    elif column:
        df_filtered = df.copy()
        if min_val is not None:
            df_filtered = df_filtered[df_filtered[column] >= min_val]
        if max_val is not None:
            df_filtered = df_filtered[df_filtered[column] <= max_val]
    else:
        raise ValueError("Either 'expression' or 'column' must be provided.")

    # 框架现在负责重命名和保存，工具只需生成一个临时文件名
    temp_output = "filtered_data.csv"
    df_filtered.to_csv(temp_output, index=False)
    return_file(temp_output)
    
    print(f"[TOOL] Filtered rows: {len(df)} -> {len(df_filtered)}")

# 注册工具
regist_tool(csv_filter_rows, tool_name="csv_filter_rows")
