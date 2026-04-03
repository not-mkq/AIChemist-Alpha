import json
import logging
import re
import csv
import math
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np

from tool_runtime import regist_tool, return_file, RunContext

logger = logging.getLogger(__name__)

# === Helper Functions (Shared Logic) ===

def _eval_param(param: Any, context: Dict[str, Any]) -> Any:
    """Evaluate Python expression if param starts with '=', otherwise try format."""
    if isinstance(param, str):
        if param.strip().startswith("="):
            expr = param.strip()[1:]
            # Safe eval context
            allowed_locals = context.copy()
            allowed_locals.update({
                "math": math, "np": np, "abs": abs, "min": min, "max": max, 
                "len": len, "str": str, "float": float, "int": int
            })
            # Let it fail if expr is wrong!
            return eval(expr, {"__builtins__": {}}, allowed_locals)
            
        elif "{" in param and "}" in param:
            # Try string formatting
            try:
                return param.format(**context)
            except Exception:
                # Formatting failed usually means it wasn't a template or key missing
                # It's safer to return original string here (e.g. LaTeX labels)
                return param
    return param

def _match_columns(header: List[str], patterns_str: str) -> List[Dict[str, str]]:
    """Support comma-separated patterns and '!' exclusion."""
    patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]
    matched_names = set()
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
        
        regex_pat = re.escape(p).replace(r"\*", "(.*)")
        try: regex = re.compile(f"^{regex_pat}$", re.IGNORECASE)
        except: continue
        
        for h in header:
            m = regex.match(h)
            if m:
                if is_exclude: matched_names.discard(h)
                else:
                    matched_names.add(h)
                    captured = " ".join([g for v in m.groups() if (g := v.strip())])
                    name_to_match[h] = captured

    results = []
    for h in header:
        if h in matched_names:
            results.append({"name": h, "match": name_to_match.get(h, "")})
    return results

def _find_col_index(header: List[str], col_name: str) -> int:
    target = col_name.strip().lower()
    lower = [h.strip().lower() for h in header]
    if target in lower: return lower.index(target)
    for i, h in enumerate(lower):
        if target in h: return i
    raise ValueError(f"Column '{col_name}' not found.")

# === Main Tool ===

def csv_extract_series(
    tool_name: str,
    source_csv: str,
    
    # Data Selection
    x_col: str,
    y_col: str, # "Main*, !Res"
    
    # Plot Type
    plot_type: str = "line", # line, bar
    
    # Basic Style (Supports Eval)
    color: str | None = None,
    linewidth: str | None = None,
    linestyle: str | None = None, # -, --, :, -.
    alpha: str | None = None,
    label_text: str | None = None, # Legend label
    zorder: str | None = None,
    
    # Bar Specific
    bar_width: str | None = None,
    
    # ID Customization
    series_id_template: str | None = None, # Default: "{file}::{col}"

    # Fill Logic
    fill_baseline: str | None = None, # min, zero, max, !!(ColName), or direct ID
    fill_color: str | None = None,
    fill_alpha: str | None = None,
    fill_gradient_dir: str | None = None, # "up", "down"
    
    # Annotation (Label on Curve)
    mark_x_ratio: str | None = None, # 0.0 - 1.0
    mark_text: str | None = None,
    mark_offset: str | None = None, # "0,10"
    mark_color: str | None = None,
    font_size: str | None = None,
    
    # Annotation Extras (Box & Arrow)
    bbox_style: str | None = None,
    arrow_style: str | None = None, # ->, -|>, etc
) -> None:
    
    src_path = Path(source_csv)
    with src_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        try: header = [c.strip() for c in next(reader)]
        except: return
        rows = [r for r in reader if r]

    # 1. Resolve X Column
    try: x_idx = _find_col_index(header, x_col)
    except: 
        logger.error(f"X column {x_col} not found")
        return

    # 2. Resolve Y Columns (Wildcard & Filter)
    # Handle @Filter syntax: "Col* @ Cycle == 1"
    y_pattern_raw = y_col
    filter_cfg = None
    if "@" in y_col:
        y_pattern_raw, filter_expr = y_col.rsplit("@", 1)
        fm = re.match(r"(.+?)\s*(==|!=|>=|<=|>|<|=)\s*(.+)", filter_expr)
        if fm:
            f_col, f_op, f_val = fm.groups()
            try:
                f_idx = _find_col_index(header, f_col)
                filter_cfg = {"idx": f_idx, "op": f_op if f_op!="=" else "==", "val": f_val.strip()}
            except: pass

    matched_cols = _match_columns(header, y_pattern_raw)
    
    # 3. Extract Data
    series_list = []
    
    # Pre-pass to gather data
    raw_series = {} # {col_name: {x:[], y:[], match:""}}
    
    for m in matched_cols:
        raw_series[m["name"]] = {"x": [], "y": [], "match": m["match"]}
        
    for row in rows:
        try:
            xv = float(row[x_idx])
            
            # Apply Row Filter
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

            for y_name, s in raw_series.items():
                y_idx = header.index(y_name)
                try:
                    yv = float(row[y_idx])
                    s["x"].append(xv)
                    s["y"].append(yv)
                except: pass
        except: continue

    # 4. Process Each Series
    for i, (y_name, s) in enumerate(raw_series.items()):
        X = np.array(s["x"])
        Y = np.array(s["y"])
        if len(X) == 0: continue
        
        # Enforce Ascending X Order (Critical for interpolation/integration)
        sort_idx = np.argsort(X)
        X = X[sort_idx]
        Y = Y[sort_idx]
        
        # Calculate Metadata
        # Area using Trapezoidal rule. Use abs() because X might be descending (XPS).
        area = abs(float(np.trapz(Y, X)))
        
        # Context for Eval/Format
        ctx = {
            "col": y_name,
            "match": s["match"],
            "index": i,
            "file": src_path.name,
            "stem": src_path.stem,
            "max_y": float(np.max(Y)),
            "min_y": float(np.min(Y)),
            "mean_y": float(np.mean(Y)),
            "area": area,
            "len": len(X)
        }
        
        # Generate ID
        id_tmpl = series_id_template or "{file}::{col}"
        series_id = id_tmpl.format(**ctx)
        
        # --- Style Evaluation ---
        # Label: Only set if user provided a template. No more default "{col}".
        lbl_val = None
        if label_text and str(label_text).strip():
            lbl_val = _eval_param(label_text, ctx)

        # Basic Styles
        c_val = _eval_param(color, ctx)
        lw_val = _eval_param(linewidth, ctx)
        ls_val = _eval_param(linestyle, ctx)
        a_val = _eval_param(alpha, ctx)
        z_val = _eval_param(zorder, ctx)

        resolved_style = {
            "plot_type": plot_type,
            "zorder": z_val,
            "label": lbl_val,
            "line": {
                "color": c_val,
                "width": lw_val,
                "style": ls_val,
                "alpha": a_val,
            }
        }
        
        if plot_type == "bar":
            resolved_style["bar"] = {
                "width": _eval_param(bar_width, ctx),
                "align": "center"
            }
            
        # Fill Logic
        f_active = False
        f_target = None
        f_base = _eval_param(fill_baseline, ctx)
        
        if f_base and str(f_base).strip():
            f_active = True
            f_target = str(f_base).strip()
            
            # Smart ID Resolution for !!(ColName)
            if f_target.startswith("!!") and "(" in f_target:
                target_col = f_target.replace("!!(", "").replace(")", "").strip()
                target_ctx = ctx.copy()
                target_ctx["col"] = target_col
                f_target = id_tmpl.format(**target_ctx)
            elif f_target not in ["min", "max", "zero"]:
                 # Assume it's a direct ID
                 pass
            
            # Check Alpha - Policy Change:
            # None/Empty -> Active=False
            # 0 -> Active=True, Alpha=0
            f_alpha = _eval_param(fill_alpha, ctx)
            
            if f_alpha is None or str(f_alpha).strip() == "":
                f_active = False
            
            # Convert to float for safety, but keep active if it was 0
            try:
                final_alpha = float(f_alpha) if f_active else 0.2
            except: 
                final_alpha = 0.2

            resolved_style["fill"] = {
                "active": f_active,
                "target_id": f_target,
                "color": _eval_param(fill_color, ctx) or c_val,
                "alpha": final_alpha,
                "gradient_dir": _eval_param(fill_gradient_dir, ctx)
            }

        # --- Annotation Logic ---
        ann_def = None
        if mark_text and mark_x_ratio:
            try:
                ratio = float(_eval_param(mark_x_ratio, ctx) or 0.5)
                ratio = max(0.0, min(1.0, ratio))
                
                # Interpolate Position
                x_min, x_max = np.min(X), np.max(X)
                target_x = x_min + ratio * (x_max - x_min)
                
                # Find closest index
                idx = (np.abs(X - target_x)).argmin()
                data_x = float(X[idx])
                data_y = float(Y[idx])
                
                # Update context with point specific data
                ctx.update({"x": data_x, "y": data_y, "val": data_y})
                
                ann_def = {
                    "active": True,
                    "x_ratio": ratio,
                    "data_x": data_x,
                    "data_y": data_y,
                    "text": _eval_param(mark_text, ctx),
                    "style": {
                        "color": _eval_param(mark_color, ctx),
                        "fontsize": _eval_param(font_size, ctx),
                        "offset": _eval_param(mark_offset, ctx),
                        "bbox": {"style": _eval_param(bbox_style, ctx)},
                        "arrow": {"style": _eval_param(arrow_style, ctx)}
                    }
                }
                # Cleanup None style
                for k in list(ann_def["style"]): 
                    if ann_def["style"][k] is None: del ann_def["style"][k]
                    
            except Exception as e:
                logger.error(f"Annotation failed: {e}")

        # Construct Object
        series_obj = {
            "type": "series",
            "id": series_id,
            "source_file": src_path.name,
            "col_name": y_name,
            "metadata": {
                "length": len(X),
                "match": s["match"],
                "integral_area": float(area),
                "y_max": float(np.max(Y)),
                "x_range": [float(np.min(X)), float(np.max(X))]
            },
            "data": {
                "x": X.tolist(),
                "y": Y.tolist()
            },
            "style": resolved_style
        }
        
        if ann_def:
            series_obj["annotation"] = ann_def
            
        series_list.append(series_obj)

    # Output
    out_name = "extracted_series.json"
    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(series_list, f, indent=2, ensure_ascii=False)
        
    return_file(out_name)

regist_tool(csv_extract_series)
