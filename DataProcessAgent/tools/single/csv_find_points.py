import json
import logging
import re
import csv
import math
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np

from tool_runtime import regist_tool, return_file

logger = logging.getLogger(__name__)

# === Helper Functions ===

def _find_col_index(header: List[str], col_name: str) -> int:
    target = col_name.strip().lower()
    lower = [h.strip().lower() for h in header]
    for i, h in enumerate(lower):
        if h == target: return i
    for i, h in enumerate(lower):
        if target in h: return i
    raise ValueError(f"Column '{col_name}' not found.")

def _match_columns(header: List[str], patterns_str: str) -> List[Dict[str, str]]:
    """
    支持逗号分隔的多个模式，且支持以 ! 开头的排除模式。
    按表头顺序返回匹配结果。
    """
    patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]
    
    matched_names = set()
    # 存储通配符匹配到的 match 映射，以便后续提取
    name_to_match = {}

    for pat in patterns:
        is_exclude = pat.startswith("!")
        p = pat[1:] if is_exclude else pat
        
        if "*" not in p:
            if p in header:
                if is_exclude: matched_names.discard(p)
                else: 
                    matched_names.add(p)
                    name_to_match[p] = ""
            continue
        
        # 处理通配符
        regex_pat = re.escape(p).replace(r"\*", "(.*)")
        try:
            regex = re.compile(f"^{regex_pat}$", re.IGNORECASE)
        except: continue
        
        for h in header:
            m = regex.match(h)
            if m:
                if is_exclude:
                    matched_names.discard(h)
                else:
                    matched_names.add(h)
                    # 如果该列没存过 match 或者新的匹配更精确（非空），则更新
                    captured = " ".join([g for v in m.groups() if (g := v.strip())])
                    name_to_match[h] = captured

    # 按 header 原始顺序组织结果
    results = []
    for h in header:
        if h in matched_names:
            results.append({"name": h, "match": name_to_match.get(h, "")})
    return results

def _eval_param(param_value: str | None, context: Dict[str, Any]) -> Any:
    """
    Evaluates a parameter.
    - If None, returns None.
    - If starts with '=', treats as Python expression.
    - Otherwise, returns as string (performing basic template substitution).
    """
    if param_value is None:
        return None
    
    val_str = str(param_value).strip()
    
    # 1. Python Expression Mode
    if val_str.startswith("="):
        expr = val_str[1:]
        try:
            # Safe eval with limited scope
            # We expose 'math' and all context variables
            safe_locals = context.copy()
            safe_locals["math"] = math
            safe_locals["np"] = np
            return eval(expr, {"__builtins__": None}, safe_locals)
        except Exception as e:
            logger.error(f"Failed to eval expression '{expr}': {e}")
            return None # Or raise? Return None for graceful degradation.

    # 2. Template String Mode
    # Use re.sub to handle {var}
    def replacer(match):
        key = match.group(1)
        fmt = None
        if ":" in key:
            key, fmt = key.split(":", 1)
        
        if key in context:
            v = context[key]
            if fmt:
                try: return format(v, fmt)
                except: return str(v)
            return str(v)
        return match.group(0)
    
    return re.sub(r"\{([^}]+)\}", replacer, val_str)

# === Core Logic ===

def csv_find_points(
    tool_name: str,
    source_csv: str,
    
    # Column Selection
    x_col: str,
    y_col: str,
    
    # Feature Definition
    find_type: str, # max, min, peak, valley, val_x, val_y
    find_param: str | None = None, # e.g. "0.5" for val_y
    
    # Labels
    custom_labels: str | None = None,
    legend_label: str | None = None,
    
    # Styles (All support '=' expression)
    # -- Text --
    label_text: str | None = None,
    label_color: str | None = None,
    font_family: str | None = None,
    font_size: str | None = None,
    label_anchor: str | None = None, # north, south, etc.
    label_offset: str | None = None, # "x,y"
    
    # -- Bbox --
    bbox_style: str | None = None, # round, square
    bbox_facecolor: str | None = None,
    bbox_edgecolor: str | None = None,
    bbox_linewidth: str | None = None,
    bbox_alpha: str | None = None,
    
    # -- Marker --
    marker_style: str | None = None,
    marker_color: str | None = None,
    marker_size: str | None = None,
    
    # -- Arrow --
    arrow_style: str | None = None,
    arrow_color: str | None = None,
) -> None:
    
    src = Path(source_csv)
    with src.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        try: header = [c.strip() for c in next(reader)]
        except: return
        rows = [r for r in reader if r]
        
    # Parse Custom Labels
    c_labels = [l.strip() for l in (custom_labels or "").split(",") if l.strip()]
    
    # Resolve Columns (X is usually one, Y can be multiple via wildcard)
    # x_col doesn't support wildcard in this simplified version, assuming unique X
    try:
        x_idx = _find_col_index(header, x_col)
    except ValueError:
        # Try wildcard for X? For now, exact match or simple search
        logger.error(f"X column {x_col} not found")
        return

    # Parse Y columns (support wildcard and @filter)
    y_col_pattern = y_col
    filter_cfg = None
    if "@" in y_col:
        y_col_pattern, filter_expr = y_col.rsplit("@", 1)
        # Parse filter: Col op Val
        fm = re.match(r"(.+?)\s*(==|!=|>=|<=|>|<|=)\s*(.+)", filter_expr)
        if fm:
            f_col, f_op, f_val = fm.groups()
            try:
                f_idx = _find_col_index(header, f_col)
                filter_cfg = {"idx": f_idx, "op": f_op if f_op!="=" else "==", "val": f_val.strip()}
            except: pass

    matched_y_cols = _match_columns(header, y_col_pattern)
    
    # Collect Data
    # structure: { y_col_name: { "x": [], "y": [], "match": ... } }
    series_data = {}
    
    for m in matched_y_cols:
        y_name = m["name"]
        try: y_idx = _find_col_index(header, y_name)
        except: continue
        series_data[y_name] = {"x": [], "y": [], "match": m["match"], "col": y_name}

    for row in rows:
        try:
            xv = float(row[x_idx])
            
            # Check filter
            if filter_cfg:
                av_raw = row[filter_cfg["idx"]]
                tv_raw = filter_cfg["val"]
                op = filter_cfg["op"]
                try: av, tv = float(av_raw), float(tv_raw)
                except: av, tv = str(av_raw), str(tv_raw)
                
                if op == "==" and not (av == tv): continue
                if op == "!=" and not (av != tv): continue
                if op == ">" and not (av > tv): continue
                if op == "<" and not (av < tv): continue
                if op == ">=" and not (av >= tv): continue
                if op == "<=" and not (av <= tv): continue

            for y_name, s in series_data.items():
                y_idx = _find_col_index(header, y_name) # optimize: cache this
                try:
                    yv = float(row[y_idx])
                    s["x"].append(xv)
                    s["y"].append(yv)
                except: pass
        except: continue

    # Analyze Features
    found_points = []
    
    for y_name, s in series_data.items():
        X = np.array(s["x"])
        Y = np.array(s["y"])
        if len(X) == 0: continue
        
        indices = []
        ft = find_type.lower()
        
        # 1. Find Indices based on feature type
        if ft == "max":
            indices = [np.argmax(Y)]
        elif ft == "min":
            indices = [np.argmin(Y)]
        elif ft == "val_x":
            # Find closest points
            target = float(find_param or 0)
            # Find index where X is closest to target
            idx = (np.abs(X - target)).argmin()
            indices = [idx]
        elif ft == "val_y":
            target = float(find_param or 0)
            # Simple approach: closest point
            # Advanced: interpolation (not implemented here for simplicity of JSON output)
            idx = (np.abs(Y - target)).argmin()
            indices = [idx]
        elif ft == "peak":
            # Simple local maxima
            # find_param can be prominence or width (todo)
            # here we implement simple neighbors comparison
            window = int(float(find_param or 1))
            for i in range(window, len(Y) - window):
                if np.all(Y[i] > Y[i-window:i]) and np.all(Y[i] > Y[i+1:i+1+window]):
                    indices.append(i)
        elif ft == "valley":
            window = int(float(find_param or 1))
            for i in range(window, len(Y) - window):
                if np.all(Y[i] < Y[i-window:i]) and np.all(Y[i] < Y[i+1:i+1+window]):
                    indices.append(i)

        # 2. Process Found Points
        for i, idx in enumerate(indices):
            # Context for Eval/Template
            ctx = {
                "x": float(X[idx]),
                "y": float(Y[idx]),
                "val": float(Y[idx]),
                "index": i,
                "col": y_name,
                "match": s["match"],
                "custom": c_labels[i % len(c_labels)] if c_labels else f"P{i+1}"
            }
            
            # Resolve Styles
            style = {
                "legend_label": _eval_param(legend_label, ctx),
                "label": {
                    "text": _eval_param(label_text or "{custom}: {y:.2f}", ctx),
                    "color": _eval_param(label_color, ctx),
                    "fontfamily": _eval_param(font_family, ctx),
                    "fontsize": _eval_param(font_size, ctx),
                    "anchor": _eval_param(label_anchor, ctx),
                    "offset": _eval_param(label_offset, ctx),
                },
                "bbox": {
                    "style": _eval_param(bbox_style, ctx),
                    "facecolor": _eval_param(bbox_facecolor, ctx),
                    "edgecolor": _eval_param(bbox_edgecolor, ctx),
                    "linewidth": _eval_param(bbox_linewidth, ctx),
                    "alpha": _eval_param(bbox_alpha, ctx),
                },
                "marker": {
                    "style": _eval_param(marker_style, ctx),
                    "color": _eval_param(marker_color, ctx),
                    "size": _eval_param(marker_size, ctx),
                },
                "arrow": {
                    "style": _eval_param(arrow_style, ctx),
                    "color": _eval_param(arrow_color, ctx),
                }
            }
            
            # Clean up None values
            for k in list(style):
                if isinstance(style[k], dict):
                    style[k] = {sk: sv for sk, sv in style[k].items() if sv is not None}
                    if not style[k]: del style[k]
                elif style[k] is None:
                    del style[k]

            point_def = {
                "type": "point",
                "source_file": src.name,
                "x": float(X[idx]),
                "y": float(Y[idx]),
                "col_name": y_name,
                "feature_type": ft,
                "style": style
            }
            found_points.append(point_def)

    out_path = "extracted_points.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(found_points, f, indent=2, ensure_ascii=False)
    
    return_file(out_path)

regist_tool(csv_find_points)
