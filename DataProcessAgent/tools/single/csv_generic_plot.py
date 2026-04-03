# tools/single/csv_generic_plot.py
"""
通用 CSV 绘图工具：
- 支持 x, y0 以及可选的 y1, y2, y3, y4。
- 支持每条线的颜色、线宽、线性定制。
- 支持在指定 x 处标出点，并根据模板生成 Label。
- 模板支持 {x}, {y0}, {y1}, {y2}, {y3}, {y4} 占位符。
"""

import csv
import re
import logging
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

from tool_runtime import (
    regist_tool,
    return_file,
)

logger = logging.getLogger(__name__)


def _find_col_index(header: List[str], col_name: str) -> int:
    target = col_name.strip().lower()
    lower = [h.strip().lower() for h in header]
    for i, h in enumerate(lower):
        if h == target:
            return i
    # 模糊匹配
    for i, h in enumerate(lower):
        if target in h:
            return i
    raise ValueError(f"Cannot find column '{col_name}' in header: {header}")


def _parse_list(s: str | None) -> List[float]:
    if not s:
        return []
    parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
    return [float(p) for p in parts]


def _render_text(template: str | None, context: Dict[str, Any]) -> str:
    if not template:
        return ""
    
    def replacer(match):
        full_key = match.group(1)
        # 分离变量名和格式化字符串，如 "x:.2f" -> "x", ".2f"
        # 注意：变量名可能包含特殊字符，但通常不含冒号（除非用于切片，这里暂不支持）
        if ":" in full_key:
            var_name, fmt = full_key.split(":", 1)
        else:
            var_name, fmt = full_key, None
            
        if var_name in context:
            val = context[var_name]
            if fmt:
                try:
                    # 使用 format(value, spec) 进行格式化
                    return format(val, fmt)
                except Exception:
                    return str(val)
            return str(val)
        return match.group(0) # 没找到变量，保留原样

    # 1. 变量替换：使用更宽泛的正则 \{([^}]+)\} 以支持 {Item@10mA} 这种复杂键名
    rendered = re.sub(r"\{([^}]+)\}", replacer, template)
    
    # 2. 转义处理：支持用 `@` 表示字面量 @
    rendered = rendered.replace("`@`", "@")
    
    return rendered.replace("\\n", "\n")


def _match_columns(header: List[str], pattern_str: str) -> List[Dict[str, str]]:
    """
    支持通配符匹配列名。
    返回列表，每项包含:
    - 'name': 完整列名
    - 'match': 通配符匹配到的部分
    """
    if "*" not in pattern_str:
        return []

    # 将 * 转换为正则捕获组 (.*)
    regex_pattern = re.escape(pattern_str).replace(r"\*", "(.*)")
    try:
        regex = re.compile(f"^{regex_pattern}$", re.IGNORECASE)
    except Exception:
        return []

    results = []
    for h in header:
        m = regex.match(h)
        if m:
            # 合并所有捕获组作为 match 内容
            captured = " ".join([g for v in m.groups() if (g := v.strip())])
            results.append({"name": h, "match": captured})
    return results


def csv_generic_plot(
    tool_name: str,
    source_csv: str,
    x_col: str,
    y0_col: str,
    y1_col: str | None = None,
    y2_col: str | None = None,
    y3_col: str | None = None,
    y4_col: str | None = None,
    y5_col: str | None = None,
    y6_col: str | None = None,
    y7_col: str | None = None,
    y8_col: str | None = None,
    y9_col: str | None = None,
    y10_col: str | None = None,
    y11_col: str | None = None,
    y12_col: str | None = None,
    y13_col: str | None = None,
    y14_col: str | None = None,

    # --- Split Data Logic ---
    split_by_col: str | None = None,
    split_by_legend_template: str | None = None,

    # --- Global Style ---
    fig_width: float | None = None,
    fig_height: float | None = None,
    dpi: int | None = None,
    xlabel: str | None = None,
    ylabel: str | None = None,
    title_template: str | None = None,
    font_name: str | None = None,
    fontsize: float | None = None,
    plot_grid: bool | None = None,
    
    # --- Axis Scaling ---
    x_log: bool | None = None,
    y_log: bool | None = None,
    y_axis_from_zero: bool | None = None,
    equal_aspect: bool | None = None,

    # --- Curve Styles (Color, Width, Style) ---
    y0_style: str | None = None,
    y1_style: str | None = None,
    y2_style: str | None = None,
    y3_style: str | None = None,
    y4_style: str | None = None,
    y5_style: str | None = None,
    y6_style: str | None = None,
    y7_style: str | None = None,
    y8_style: str | None = None,
    y9_style: str | None = None,
    y10_style: str | None = None,
    y11_style: str | None = None,
    y12_style: str | None = None,
    y13_style: str | None = None,
    y14_style: str | None = None,

    # --- Markers & Labels ---

    marker_x_values: str | None = None,
    marker_y_values: str | None = None,
    marker_style: str | None = None,  # New: shape,color,size@Legend
    label_template: str | None = None,
    label_anchor: str | None = None, # New: north, south, east, west, etc.
    show_marker_line: bool | None = None,
    
    # --- Legend Customization ---
    legend_extra_text: str | None = None,
    legend_loc: str | None = None,

    encoding: str | None = None,
) -> None:
    # --- Apply Defaults ---
    fig_width = fig_width if fig_width is not None else 6.0
    fig_height = fig_height if fig_height is not None else 4.5
    dpi = dpi if dpi is not None else 300
    # xlabel, ylabel, title_template defaults removed to allow None (hidden)
    font_name = font_name if font_name is not None else "Arial"
    fontsize = fontsize if fontsize is not None else 12.0
    plot_grid = plot_grid if plot_grid is not None else True
    legend_loc = legend_loc if legend_loc is not None else "best"
    split_by_legend_template = split_by_legend_template if split_by_legend_template is not None else "{val}"

    x_log = bool(x_log)
    y_log = bool(y_log)
    y_axis_from_zero = bool(y_axis_from_zero)
    equal_aspect = bool(equal_aspect)
    
    # Styles defaults for y0-y14
    y_styles_default = [
        "blue,2.0,-", "red,1.5,--", "green,1.5,-.", "orange,1.5,:", "purple,1.5,-",
        "brown,1.5,--", "pink,1.5,-.", "gray,1.5,:", "olive,1.5,-", "cyan,1.5,--",
        "teal,1.5,-", "navy,1.5,--", "gold,1.5,-.", "magenta,1.5,:", "lime,1.5,-"
    ]
    
    styles_provided = [
        y0_style, y1_style, y2_style, y3_style, y4_style, 
        y5_style, y6_style, y7_style, y8_style, y9_style,
        y10_style, y11_style, y12_style, y13_style, y14_style
    ]
    y_styles_final = []
    for i in range(15):
        y_styles_final.append(styles_provided[i] if styles_provided[i] is not None else y_styles_default[i])
    
    # Marker defaults
    marker_style = marker_style if marker_style is not None else "o,red,5"
    label_template = label_template if label_template is not None else "({x:.2f}, {y:.2f})"
    show_marker_line = show_marker_line if show_marker_line is not None else True
    encoding = encoding if encoding is not None else "utf-8"

    src = Path(source_csv)
    ctx = {"stem": src.stem}

    # 1. 预读取 Header 和所有行
    with src.open("r", encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        header = [c.strip() for c in next(reader)]
        all_rows = [row for row in reader if row]

    if not all_rows:
        raise ValueError("Input CSV is empty")

    x_idx = _find_col_index(header, x_col)
    y_configs = []

    # --- 处理 Split By 逻辑 ---
    if split_by_col:
        try:
            s_idx = _find_col_index(header, split_by_col)
            # 获取唯一值并排序
            def _sort_key(v):
                try: return float(v)
                except: return str(v)
            unique_vals = sorted(list(set(row[s_idx] for row in all_rows)), key=_sort_key)
            
            base_y_col = y0_col
            base_style = y_styles_final[0]
            
            for i, val in enumerate(unique_vals):
                style_part = base_style
                current_label = _render_text(split_by_legend_template, {"val": val, "stem": src.stem})
                if "@" in base_style:
                    style_part, _ = base_style.split("@", 1)
                
                parts = [p.strip() for p in style_part.split(",")]
                color_spec = parts[0]
                if not color_spec.startswith("col(") and len(unique_vals) > 1:
                    color_spec = f"C{i % 10}"
                
                width = float(parts[1]) if len(parts) > 1 else 2.0
                lstyle = parts[2] if len(parts) > 2 else "-"
                marker = parts[3] if len(parts) > 3 else None
                stride = int(parts[4]) if len(parts) > 4 else 0

                # --- 解析基线列 ---
                fill_baseline_idx = -1
                if marker and marker.lower().startswith("fill"):
                    base_match = re.search(r"\(\s*([^)]+)\s*\)", marker)
                    if base_match:
                        b_col = base_match.group(1).strip()
                        try:
                            fill_baseline_idx = _find_col_index(header, b_col)
                        except ValueError:
                            logger.warning(f"Baseline column '{b_col}' not found.")

                color_col_idx = -1
                fixed_color = color_spec
                if color_spec.startswith("col(") and color_spec.endswith(")"):
                    c_col_name = color_spec[4:-1].strip()
                    color_col_idx = _find_col_index(header, c_col_name)
                    fixed_color = None

                y_configs.append({
                    "idx": _find_col_index(header, base_y_col),
                    "name": base_y_col,
                    "label": current_label,
                    "color": fixed_color,
                    "color_col_idx": color_col_idx,
                    "width": width,
                    "linestyle": lstyle,
                    "marker": marker,
                    "stride": stride,
                    "filter": {"col_name": split_by_col, "op": "==", "val": str(val), "idx": s_idx},
                    "data": [],
                    "colors_data": [],
                    "baseline_idx": fill_baseline_idx,
                    "baseline_data": []
                })
        except ValueError:
            logger.warning(f"Split column '{split_by_col}' not found. Falling back to normal mode.")
            split_by_col = None # Proceed to 'else' block below
    
    if not split_by_col:
        # 传统 y0-y14 模式，增加通配符支持
        y_specs = [
            y0_col, y1_col, y2_col, y3_col, y4_col, 
            y5_col, y6_col, y7_col, y8_col, y9_col,
            y10_col, y11_col, y12_col, y13_col, y14_col
        ]
        y_styles = y_styles_final


        for i, y_spec in enumerate(y_specs):
            if not y_spec or not y_spec.strip(): continue
            
            # 解析过滤器
            y_col_part = y_spec
            filter_cfg = None
            if "@" in y_spec:
                y_col_part, filter_expr = y_spec.rsplit("@", 1)
                match = re.match(r"(.+?)\s*(==|!=|>=|<=|>|<|=)\s*(.+)", filter_expr)
                if match:
                    f_col, f_op, f_val = match.groups()
                    if f_op == "=": f_op = "=="
                    try:
                        f_idx = _find_col_index(header, f_col.strip())
                        filter_cfg = {"col_name": f_col.strip(), "op": f_op, "val": f_val.strip(), "idx": f_idx}
                    except ValueError:
                        logger.warning(f"Filter column '{f_col}' not found, filter will be ignored.")
                        filter_cfg = None

            # 扩展通配符
            matches = _match_columns(header, y_col_part)
            if not matches:
                # 没通配符或没匹配到，按原样处理
                matches = [{"name": y_col_part, "match": ""}]

            raw_style_str = y_styles[i]
            style_part = raw_style_str
            style_legend_tmpl = None
            if "@" in raw_style_str:
                style_part, style_legend_tmpl = raw_style_str.split("@", 1)

            # 样式解析 (固定部分)
            parts = [p.strip() for p in style_part.split(",")]
            color_spec = parts[0]
            width = float(parts[1]) if len(parts) > 1 else 1.5
            lstyle = parts[2] if len(parts) > 2 else "-"
            marker = parts[3] if len(parts) > 3 else None
            stride = int(parts[4]) if len(parts) > 4 else 0

            # --- 解析基线列 ---
            fill_baseline_idx = -1
            if marker and marker.lower().startswith("fill"):
                base_match = re.search(r"\(\s*([^)]+)\s*\)", marker)
                if base_match:
                    b_col = base_match.group(1).strip()
                    try:
                        fill_baseline_idx = _find_col_index(header, b_col)
                    except ValueError:
                        logger.warning(f"Baseline column '{b_col}' not found.")

            for m_idx, m_info in enumerate(matches):
                y_real_name = m_info["name"]
                try:
                    idx = _find_col_index(header, y_real_name)
                except ValueError:
                    # 找不到的数据列就跳过，不中断运行
                    logger.warning(f"Column '{y_real_name}' not found in CSV header, skipping curve.")
                    continue

                # 动态生成标签
                curve_ctx = ctx.copy()
                curve_ctx.update({
                    "col": y_real_name,
                    "match": m_info["match"],
                    "index": m_idx
                })
                
                if style_legend_tmpl is not None:
                    current_label = _render_text(style_legend_tmpl, curve_ctx)
                else:
                    current_label = y_real_name if len(matches) > 1 else "_nolegend_"
                
                # print(f"DEBUG: col={y_real_name}, label={current_label}")

                color_col_idx = -1
                fixed_color = color_spec
                if color_spec.startswith("col(") and color_spec.endswith(")"):
                    color_col_idx = _find_col_index(header, color_spec[4:-1].strip())
                    fixed_color = None

                y_configs.append({
                    "idx": idx, "name": y_real_name, "label": current_label,
                    "color": fixed_color, "color_col_idx": color_col_idx,
                    "width": width, "linestyle": lstyle, "marker": marker, "stride": stride,
                    "filter": filter_cfg, "data": [], "colors_data": [],
                    "baseline_idx": fill_baseline_idx, "baseline_data": []
                })

    # 2. 分发数据
    x_data = []
    for row in all_rows:
        try:
            xv = float(row[x_idx])
            
            row_y_data = []
            row_baseline_data = []
            for cfg in y_configs:
                val = float(row[cfg["idx"]])
                
                # 基线采集
                b_val = 0.0
                if cfg["baseline_idx"] != -1:
                    try: b_val = float(row[cfg["baseline_idx"]])
                    except: b_val = 0.0
                
                f = cfg.get("filter")
                if f:
                    actual_f_raw = row[f["idx"]]
                    try:
                        a_val, t_val = float(actual_f_raw), float(f["val"])
                    except ValueError:
                        a_val, t_val = str(actual_f_raw), str(f["val"])
                    
                    op = f["op"]
                    passed = False
                    if op == "==": passed = (a_val == t_val)
                    elif op == "!=": passed = (a_val != t_val)
                    elif op == ">": passed = (a_val > t_val)
                    elif op == "<": passed = (a_val < t_val)
                    elif op == ">=": passed = (a_val >= t_val)
                    elif op == "<=": passed = (a_val <= t_val)
                    if not passed: val = np.nan
                row_y_data.append(val)
                row_baseline_data.append(b_val)
            
            # 只有当所有列都处理完（且没有触发 Exception）才记录这一行
            x_data.append(xv)
            for j, cfg in enumerate(y_configs):
                cfg["data"].append(row_y_data[j])
                cfg["baseline_data"].append(row_baseline_data[j])
                if cfg["color_col_idx"] != -1:
                    cfg["colors_data"].append(row[cfg["color_col_idx"]])
        except Exception as e:
            continue

    X = np.array(x_data)
    if len(X) == 0:
        logger.warning("No valid numeric data found to plot.")
    
    # 2. 绘图准备
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)
    
    # 应用对数坐标
    if x_log and len(X) > 0 and np.all(X > 0):
        ax.set_xscale("log")
    if y_log:
        ax.set_yscale("log")
    
    if equal_aspect:
        ax.set_aspect("equal")

    # --- Pre-calculate Bar Width ---
    # 计算 X 轴的最小间隔，决定柱子默认宽度
    if len(X) > 1:
        unique_x = np.unique(X)
        if len(unique_x) > 1:
            min_x_diff = float(np.min(np.diff(unique_x)))
        else:
            min_x_diff = 1.0
    else:
        min_x_diff = 1.0 
    bar_width = min_x_diff * 0.8 # 默认占用 80% 宽度

    # 绘制曲线 (从 y14 倒序绘制到 y0，确保 y0 在最上方)
    plot_handles_map = {} # 用于按索引收集句柄，保持图例顺序
    
    num_y = len(y_configs)
    for i in range(num_y - 1, -1, -1):
        cfg = y_configs[i]
        m = cfg["marker"]
        stride = cfg.get("stride", 0)
        is_hollow = False
        is_bar = False
        is_fill = False
        fill_alpha = 0.1
        
        # 计算该曲线的基础 zorder (i 越小，zorder 越高)
        # 基础范围 2.0 ~ 3.5
        curr_z = 2.0 + (num_y - i) * 0.1

        # Check for bar/fill markers
        if m and m.lower().startswith("bar"):
            is_bar = True
            if m.endswith("!"):
                is_hollow = True
        elif m and m.lower().startswith("fill"):
            is_fill = True
            bang_count = m.count("!")
            fill_alpha = min(1.0, 0.1 + bang_count * 0.1)
        elif m and m.endswith("!"):
            m = m[:-1]
            is_hollow = True
            
        plot_slice = slice(None, None, stride + 1)
        sliced_x = X[plot_slice]
        y_raw = np.array(cfg["data"])
        if len(y_raw) == 0:
            continue
        sliced_y = y_raw[plot_slice]
        sliced_baseline = np.array(cfg["baseline_data"])[plot_slice]
        
        if len(sliced_x) == 0:
            continue

        if is_bar:
            # === Bar Chart Rendering ===
            effective_width = bar_width * (stride + 1)
            face_c = cfg["color"]
            edge_c = "none"
            if is_hollow:
                face_c = "none"
                edge_c = cfg["color"]
            if cfg["linestyle"]:
                 edge_c = cfg["color"]
            
            bar_colors = face_c
            edge_colors = edge_c
            if cfg["color_col_idx"] != -1 and len(cfg["colors_data"]) > 0:
                 raw_colors = np.array(cfg["colors_data"])[plot_slice]
                 if is_hollow:
                     edge_colors = raw_colors
                     face_c = "none"
                 else:
                     bar_colors = raw_colors
            
            ax.bar(
                sliced_x, sliced_y, 
                width=effective_width, 
                color=bar_colors,
                edgecolor=edge_colors,
                linewidth=cfg["width"], 
                linestyle=cfg["linestyle"],
                label=cfg["label"],
                zorder=curr_z
            )
            
            if cfg["label"] and cfg["label"] != "_nolegend_":
                leg_face = bar_colors[0] if isinstance(bar_colors, (list, np.ndarray)) else bar_colors
                leg_edge = edge_colors[0] if isinstance(edge_colors, (list, np.ndarray)) else edge_colors
                proxy = matplotlib.patches.Rectangle((0,0), 1, 1, 
                    facecolor=leg_face, edgecolor=leg_edge,
                    linewidth=cfg["width"], linestyle=cfg["linestyle"],
                    label=cfg["label"]
                )
                plot_handles_map[i] = proxy

        elif is_fill:
            # === Area/Fill Rendering ===
            fill_c = cfg["color"] if cfg["color"] else "blue"
            ax.fill_between(
                sliced_x, sliced_y, sliced_baseline,
                color=fill_c, 
                alpha=fill_alpha, 
                zorder=curr_z,
                label="_nolegend_"
            )
            
            if cfg["linestyle"]:
                lines = ax.plot(
                    sliced_x, sliced_y,
                    color=cfg["color"],
                    linewidth=cfg["width"],
                    linestyle=cfg["linestyle"],
                    zorder=curr_z + 0.05,
                    label="_nolegend_"
                )
            
            if cfg["label"] and cfg["label"] != "_nolegend_":
                proxy = matplotlib.patches.Patch(
                    facecolor=fill_c, 
                    alpha=fill_alpha,
                    edgecolor=cfg["color"] if cfg["linestyle"] else "none",
                    linewidth=cfg["width"] if cfg["linestyle"] else 0,
                    label=cfg["label"]
                )
                plot_handles_map[i] = proxy

        else:
            # === Line/Scatter Rendering (Existing Logic) ===
            line_handle = None
            if cfg["color_col_idx"] != -1 and len(cfg["colors_data"]) > 0:
                sliced_colors = np.array(cfg["colors_data"])[plot_slice]
                points = np.array([sliced_x, sliced_y]).T.reshape(-1, 1, 2)
                segments = np.concatenate([points[:-1], points[1:]], axis=1)
                seg_colors = sliced_colors[:-1]
                
                lc = LineCollection(segments, colors=seg_colors, 
                                    linewidths=cfg["width"], linestyles=cfg["linestyle"],
                                    zorder=curr_z)
                ax.add_collection(lc)
                
                # 为了图例 (Legend)
                line_handle = ax.plot([sliced_x[0]], [sliced_y[0]], color=sliced_colors[0], 
                                    linewidth=cfg["width"], linestyle=cfg["linestyle"],
                                    label=cfg["label"],
                                    zorder=curr_z,
                                    visible=False if cfg["linestyle"] == "" else True)[0]
                
                if m:
                    ax.scatter(sliced_x, sliced_y, s=(cfg["width"] * 3)**2, 
                            c=sliced_colors, marker=m, 
                            edgecolors="none" if not is_hollow else sliced_colors,
                            facecolors=sliced_colors if not is_hollow else "none",
                            zorder=curr_z + 0.05)
            else:
                # 普通单色模式
                plots = ax.plot(sliced_x, sliced_y, 
                        color=cfg["color"], 
                        linewidth=cfg["width"], 
                        linestyle=cfg["linestyle"],
                        marker=m,
                        label=cfg["label"],
                        markersize=cfg["width"] * 3 if m else None,
                        markerfacecolor="none" if is_hollow else cfg["color"],
                        markeredgecolor=cfg["color"] if is_hollow else None,
                        markeredgewidth=1.5 if is_hollow else None,
                        zorder=curr_z)
                if plots:
                    line_handle = plots[0]
            
            # 收集有效图例句柄
            if line_handle and cfg["label"] and cfg["label"] != "_nolegend_":
                plot_handles_map[i] = line_handle

    # 整理图例顺序 (y0 -> y14)
    plot_handles = [plot_handles_map[idx] for idx in sorted(plot_handles_map.keys())]

    # 强制从 0 开始 (放在绘图后，以便获取准确的自动缩放范围)
    if not y_log:
        if y_axis_from_zero:
            ylim = ax.get_ylim()
            if ylim and len(ylim) == 2:
                ymin, ymax = ylim
                if ymin > 0:
                    ax.set_ylim(bottom=0)
                elif ymax < 0:
                    ax.set_ylim(top=0)
        else:
            # 自动模式：如果数据离 0 很远，Matplotlib 依然包含 0，则我们手动缩放到数据区间
            all_y = []
            for cfg in y_configs:
                valid_y = [v for v in cfg["data"] if not np.isnan(v)]
                if valid_y:
                    all_y.extend(valid_y)
            
            if all_y:
                data_min = min(all_y)
                data_max = max(all_y)
                data_range = data_max - data_min
                if data_range == 0: data_range = 1.0
                
                # 只有当数据全部在 0 的一侧时，才考虑“远离 0”
                if data_min > 0:
                    # 检查当前 ymin 是否被强制设为 0 了
                    ylim_curr = ax.get_ylim()
                    if ylim_curr and len(ylim_curr) == 2:
                        curr_ymin, curr_ymax = ylim_curr
                        if curr_ymin <= 0:
                            ax.set_ylim(bottom=data_min - 0.05 * data_range)
                elif data_max < 0:
                    ylim_curr = ax.get_ylim()
                    if ylim_curr and len(ylim_curr) == 2:
                        curr_ymin, curr_ymax = ylim_curr
                        if curr_ymax >= 0:
                            ax.set_ylim(top=data_max + 0.05 * data_range)

    # 全局修饰
    font_props = {"family": font_name, "size": fontsize}
    
    if title_template:
        ax.set_title(_render_text(title_template, ctx), fontdict=font_props)
    if xlabel:
        ax.set_xlabel(_render_text(xlabel, ctx), fontdict=font_props)
    if ylabel:
        ax.set_ylabel(_render_text(ylabel, ctx), fontdict=font_props)
    
    for label in (ax.get_xticklabels() + ax.get_yticklabels()):
        label.set_fontname(font_name)
        label.set_fontsize(fontsize * 0.8)

    if plot_grid:
        ax.grid(True, linestyle="--", alpha=0.6)

    # 3. 标注点 (Markers)
    # 解析 marker_style: "shape,color,size@Legend"
    m_shape = "o"
    m_color = "red"
    m_size = 5.0
    m_legend = None
    
    if marker_style:
        if "@" in marker_style:
            marker_style_part, m_legend_tmpl = marker_style.split("@", 1)
            m_legend = _render_text(m_legend_tmpl, ctx)
        else:
            marker_style_part = marker_style
        
        m_parts = [p.strip() for p in marker_style_part.split(",")]
        if len(m_parts) > 0: m_shape = m_parts[0]
        if len(m_parts) > 1: m_color = m_parts[1]
        if len(m_parts) > 2: m_size = float(m_parts[2])

    m_x_list = _parse_list(marker_x_values)
    m_y_list = _parse_list(marker_y_values)
    
    # 解析锚点位置 (TikZ 风格映射到 Matplotlib)
    anchor_map = {
        "north": ((0, 10), "center", "bottom"),
        "south": ((0, -10), "center", "top"),
        "east": ((10, 0), "left", "center"),
        "west": ((-10, 0), "right", "center"),
        "north east": ((10, 10), "left", "bottom"),
        "north west": ((-10, 10), "right", "bottom"),
        "south east": ((10, -10), "left", "top"),
        "south west": ((-10, -10), "right", "top"),
    }
    
    # 预定义备选锚点以便 auto 模式使用
    current_anchor = (label_anchor or "north west").lower()

    points_to_mark = [] # List of (x, y, is_on_y0)
    
    if m_x_list and m_y_list:
        for px, py in zip(m_x_list, m_y_list):
            points_to_mark.append((px, py, False))
    elif len(y_configs) > 0:
        y0_cfg = y_configs[0]
        y0_data = np.array(y0_cfg["data"])
        if m_x_list:
            for mx in m_x_list:
                idx = (np.abs(X - mx)).argmin()
                points_to_mark.append((X[idx], y0_data[idx], True))
        elif m_y_list:
            for my in m_y_list:
                idx = (np.abs(y0_data - my)).argmin()
                points_to_mark.append((X[idx], y0_data[idx], True))

    # 绘制标注
    has_marker_drawn = False
    for px, py, is_on_y0 in points_to_mark:
        has_marker_drawn = True
        
        # 确定当前点的锚点
        this_offset, this_ha, this_va = anchor_map.get(current_anchor, anchor_map["north west"])
        
        if current_anchor == "auto" and is_on_y0:
            # 自动避障逻辑：根据局部斜率决定位置
            idx = (np.abs(X - px)).argmin()
            if 0 < idx < len(X) - 1:
                # 计算简单梯度
                slope = (y_configs[0]["data"][idx+1] - y_configs[0]["data"][idx-1]) / (X[idx+1] - X[idx-1] + 1e-9)
                if slope > 0: # 曲线向上走
                    this_offset, this_ha, this_va = anchor_map["north west"]
                else: # 曲线向下走
                    this_offset, this_ha, this_va = anchor_map["north east"]
            else:
                this_offset, this_ha, this_va = anchor_map["north west"]

        # 绘制点
        is_hollow = False
        shape = m_shape
        if shape.endswith("!"):
            shape = shape[:-1]
            is_hollow = True

        ax.plot(px, py, shape, 
                color=m_color, 
                markersize=m_size,
                markerfacecolor="none" if is_hollow else m_color,
                markeredgecolor=m_color,
                zorder=5)

        # 准备 Label 上下文
        idx = (np.abs(X - px)).argmin()
        label_ctx = {"x": px, "y": py, "y0": y_configs[0]["data"][idx] if len(y_configs) > 0 else py}
        for k in range(1, len(y_configs)):
            label_ctx[f"y{k}"] = y_configs[k]["data"][idx]

        txt = _render_text(label_template, label_ctx)
        if txt:
            ax.annotate(
                txt,
                xy=(px, py),
                xytext=this_offset, 
                textcoords="offset points",
                ha=this_ha,       
                va=this_va,      
                fontname=font_name,
                fontsize=fontsize * 0.8,
                bbox=dict(boxstyle="round,pad=0.2", fc="yellow", alpha=0.3),
                zorder=6
            )

    # --- 构建最终图例 ---
    final_handles = plot_handles[:]
    
    # 添加 Marker 图例 (仅当确实画了点，且定义了 Legend)
    if has_marker_drawn and m_legend:
        # 创建 Handle
        shape = m_shape
        is_hollow = False
        if shape.endswith("!"):
            shape = shape[:-1]
            is_hollow = True
            
        m_handle = matplotlib.lines.Line2D(
            [], [], 
            color=m_color, 
            marker=shape, 
            linestyle="None", 
            markersize=m_size,
            label=m_legend,
            markerfacecolor="none" if is_hollow else m_color,
            markeredgecolor=m_color
        )
        final_handles.append(m_handle)
    
    # 添加 Extra Text
    if legend_extra_text:
        rendered_extra = _render_text(legend_extra_text, ctx)
        extra_handle = matplotlib.lines.Line2D([], [], color="none", label=rendered_extra)
        final_handles.append(extra_handle)

    if final_handles:
        # 去重：如果多个 handle 具有相同的 label，只保留第一个
        unique_handles = []
        seen_labels = set()
        for h in final_handles:
            lbl = h.get_label()
            if lbl not in seen_labels:
                unique_handles.append(h)
                seen_labels.add(lbl)

        ax.legend(handles=unique_handles, 
                  loc=legend_loc,
                  prop={"family": font_name, "size": fontsize * 0.9})

    fig.tight_layout()
    out_name = "plot_output.png"
    fig.savefig(out_name, dpi=dpi)
    plt.close(fig)
    return_file(out_name)


regist_tool(csv_generic_plot)