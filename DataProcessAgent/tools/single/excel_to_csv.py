# tools/single/excel_to_csv.py
"""
Excel 转 CSV 工具：
- 支持 .xls 和 .xlsx 格式。
- 用户可以指定要转换的工作表 (Sheet) 名称。
- 自动删除全空行。
- 输出为标准 CSV 文件。
"""

import os
import logging
from pathlib import Path

import pandas as pd
from tool_runtime import regist_tool, return_file

logger = logging.getLogger(__name__)

def excel_to_csv(
    tool_name: str,
    source_excel: str,
    sheet_name: Optional[str] = None,
    sheet_keyword: Optional[str] = None,
    encoding: str = "utf-8",
) -> None:
    """
    将 Excel 的特定工作表转换为 CSV。
    支持按名称匹配或按内容关键词搜索。
    """
    src_path = Path(source_excel).absolute()
    if not src_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {src_path}")

    try:
        # 1. 嗅探格式
        with open(src_path, 'rb') as f:
            header = f.read(8)
        
        if header.startswith(b'PK\x03\x04'):
            engine = 'openpyxl'
        elif header.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            engine = 'xlrd'
        else:
            engine = None
            
        # 2. 确定要使用的 Sheet
        xl = pd.ExcelFile(src_path, engine=engine)
        all_sheets = xl.sheet_names
        target_sheet = None

        # 优先通过名字匹配
        if sheet_name and sheet_name in all_sheets:
            target_sheet = sheet_name
            print(f"[EXCEL-CONV] Using sheet by name: {target_sheet}")
        
        # 如果名字没匹配上，且提供了关键词，则搜索内容
        if not target_sheet and sheet_keyword:
            print(f"[EXCEL-CONV] Searching for keyword '{sheet_keyword}' in {len(all_sheets)} sheets...")
            for name in all_sheets:
                # 读取该 Sheet 进行搜索 (仅读前几行或全读，为了准确性建议全读，因为 Excel 通常不大)
                temp_df = pd.read_excel(xl, sheet_name=name)
                # 将整个 DataFrame 转为字符串并搜索 (不区分大小写以提高易用性)
                if temp_df.astype(str).apply(lambda x: x.str.contains(sheet_keyword, case=False, na=False)).any().any():
                    target_sheet = name
                    print(f"[EXCEL-CONV] Found keyword '{sheet_keyword}' in sheet: {target_sheet}")
                    break
        
        if not target_sheet:
            # 如果都没找到，尝试回退到第一个 Sheet
            target_sheet = all_sheets[0]
            print(f"[EXCEL-CONV] No match found. Falling back to first sheet: {target_sheet}")

        # 3. 读取并清理数据
        df = pd.read_excel(xl, sheet_name=target_sheet)
        
        if df is None:
             raise RuntimeError(f"无法从 Sheet '{target_sheet}' 读取数据。")
        
        # 删除全空行
        original_count = len(df)
        df = df.dropna(how='all')
        df = df.reset_index(drop=True)
        
        print(f"[EXCEL-CONV] Cleaned rows: {original_count} -> {len(df)}")

        # 4. 构造输出文件名 (去除特殊字符)
        safe_sheet_name = "".join([c for c in target_sheet if c.isalnum() or c in ('_', '-')])
        out_name = f"{src_path.stem}_{safe_sheet_name}.csv"
        
        df.to_csv(out_name, index=False, encoding=encoding)
        
        if not os.path.exists(out_name) or os.path.getsize(out_name) == 0:
            raise RuntimeError(f"CSV 生成失败或文件为空: {out_name}")

        return_file(out_name)
        print(f"[EXCEL-CONV] Produced: {out_name}")

    except Exception as e:
        logger.error(f"Excel 转换失败: {e}", exc_info=True)
        # 检查是否是由于缺少引擎导致的
        err_msg = str(e)
        if "openpyxl" in err_msg or "xlrd" in err_msg:
            raise RuntimeError(f"系统缺少 Excel 处理引擎，请联系管理员安装 openpyxl 或 xlrd。错误详情: {e}")
        raise

# 注册工具
regist_tool(excel_to_csv)
