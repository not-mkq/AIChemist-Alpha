import pandas as pd
import re
import numpy as np
from pathlib import Path
from collections import Counter
from typing import Optional, List, Any, Dict
from tool_runtime import (
    regist_tool,
    return_file,
)

def _wildcard_to_regex(wildcard_pattern: str):
    """将通配符 * 转为正则表达式捕获组"""
    escaped = re.escape(wildcard_pattern).replace(r'\*', '(.*)')
    return f"^{escaped}$"

def _render_col_name(template: str, match_obj: re.Match, mode: str) -> str:
    """根据匹配结果渲染输出列名"""
    if not template:
        return ""
    
    context = {}
    if mode == "wildcard":
        groups = match_obj.groups()
        context["matched"] = groups[0] if groups else ""
    else:
        context["group0"] = match_obj.group(0)
        for i, val in enumerate(match_obj.groups(), 1):
            context[f"group{i}"] = val
            
    res = template
    for k, v in context.items():
        res = res.replace(f"{{{k}}}", str(v))
    return res

def _is_float(val: Any) -> bool:
    try:
        f = float(val)
        return not np.isnan(f)
    except (ValueError, TypeError):
        return False

def csv_column_header_cleanup(
    tool_name: str,
    source_csv: str,
    match_mode: str = "wildcard",
    float_threshold: int = 10,
    
    col0_match: str = "", col0_out: str = "",
    col1_match: str = "", col1_out: str = "",
    col2_match: str = "", col2_out: str = "",
    col3_match: str = "", col3_out: str = "",
    col4_match: str = "", col4_out: str = "",
    col5_match: str = "", col5_out: str = "",
    col6_match: str = "", col6_out: str = "",
    col7_match: str = "", col7_out: str = "",
    col8_match: str = "", col8_out: str = "",
    col9_match: str = "", col9_out: str = "",
    
    encoding: str = "utf-8",
) -> None:
    # 1. 准备规则
    rules = []
    pairs = [
        (col0_match, col0_out), (col1_match, col1_out), (col2_match, col2_out),
        (col3_match, col3_out), (col4_match, col4_out), (col5_match, col5_out),
        (col6_match, col6_out), (col7_match, col7_out), (col8_match, col8_out),
        (col9_match, col9_out)
    ]
    for m_pat, out_tmpl in pairs:
        if m_pat.strip():
            regex_str = _wildcard_to_regex(m_pat) if match_mode == "wildcard" else m_pat
            rules.append({
                "pattern": re.compile(regex_str),
                "out_tmpl": out_tmpl or m_pat
            })

    # 2. 读取原始 CSV
    try:
        df_raw = pd.read_csv(source_csv, header=None, sep=None, engine='python', encoding=encoding)
    except Exception as e:
        raise ValueError(f"Failed to read CSV: {e}")

    # 候选列信息列表
    candidates = []
    
    # 3. 逐列扫描，收集匹配信息和有效数据范围
    for col_idx in df_raw.columns:
        series = df_raw[col_idx]
        
        # A. 识别数据列：统计浮点数个数
        float_count = sum(1 for val in series if _is_float(val))
        if float_count < float_threshold:
            continue
            
        # B. 寻找表头：逆序匹配规则
        found_rule = None
        found_match_obj = None
        header_row_idx = -1
        
        for row_idx in range(len(series) - 1, -1, -1):
            cell_val = str(series[row_idx]).strip()
            if not cell_val or cell_val.lower() == "nan":
                continue
            
            for rule in rules:
                m = rule["pattern"].search(cell_val)
                if m:
                    found_rule = rule
                    found_match_obj = m
                    header_row_idx = row_idx
                    break
            if found_rule:
                break
        
        if found_rule:
            final_name = _render_col_name(found_rule["out_tmpl"], found_match_obj, match_mode)
            
            # 扫描该列的有效数据起始行和结束行 (在表头之后寻找)
            first_data_row = -1
            last_data_row = -1
            
            # 向下找第一个 float
            for r in range(header_row_idx + 1, len(series)):
                if _is_float(series[r]):
                    first_data_row = r
                    break
            
            # 向上找最后一个 float
            for r in range(len(series) - 1, header_row_idx, -1):
                if _is_float(series[r]):
                    last_data_row = r
                    break
            
            if first_data_row != -1 and last_data_row != -1:
                candidates.append({
                    "col_idx": col_idx,
                    "name": final_name,
                    "header_row": header_row_idx,
                    "start_row": first_data_row,
                    "end_row": last_data_row
                })

    if not candidates:
        raise ValueError(f"No columns identified as data (threshold={float_threshold}) matched any rules.")

    # 4. 确定统一的数据块范围 (包容机制)
    # 为了最大程度保留数据（防止因部分列首行缺失导致整行被切除），取最小的起始行和最大的结束行
    # 前提是所有列的 header_row 应该大致在同一水平线上，这里假设规则匹配正确
    start_rows = [c["start_row"] for c in candidates]
    end_rows = [c["end_row"] for c in candidates]
    
    common_start_row = min(start_rows)
    common_end_row = max(end_rows)
    
    # 5. 统一提取并构建结果
    result_data = {}
    
    # 用来处理重名
    name_counts = Counter()
    
    for cand in candidates:
        original_name = cand["name"]
        
        # 处理重名：如果名字已经存在，加后缀
        name_counts[original_name] += 1
        if name_counts[original_name] > 1:
            unique_name = f"{original_name}_{name_counts[original_name]-1}"
        else:
            unique_name = original_name
            
        # 提取数据：使用统一的行范围 [common_start_row, common_end_row] (闭区间)
        # 注意 iloc 是左闭右开，所以 end 要 +1
        col_data = df_raw.iloc[common_start_row : common_end_row + 1, cand["col_idx"]]
        
        # 清洗非数值：转为 float，无法转换的变为 NaN
        # 使用 apply 逐个处理以确保安全转换
        clean_col = col_data.apply(lambda x: float(x) if _is_float(x) else np.nan)
        
        # 重置索引，以便放入新的 DataFrame (所有列共享 0..N index)
        result_data[unique_name] = clean_col.values

    # 构建 DataFrame
    res_df = pd.DataFrame(result_data)
    
    out_name = "cleaned_data.csv"
    res_df.to_csv(out_name, index=False, encoding="utf-8-sig")
    
    return_file(out_name)

regist_tool(csv_column_header_cleanup)
