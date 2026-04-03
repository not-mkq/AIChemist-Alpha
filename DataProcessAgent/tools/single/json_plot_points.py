import json
import logging
import fnmatch
from pathlib import Path
from typing import Dict, Any, List, Union

import matplotlib
matplotlib.use('Agg') # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from matplotlib.patches import Polygon

from tool_runtime import (
    regist_tool,
    return_file,
)

logger = logging.getLogger(__name__)

def _map_anchor(anchor: str):
    """Map anchor text to Matplotlib alignment and offset."""
    ha, va = "center", "center"
    ox, oy = 0, 0
    
    a = anchor.lower()
    if "north" in a: 
        va = "bottom"
        oy = 10
    elif "south" in a: 
        va = "top"
        oy = -10
        
    if "east" in a: 
        ha = "left"
        ox = 10
    elif "west" in a: 
        ha = "right"
        ox = -10
        
    return (ox, oy), ha, va

def _draw_annotation(ax, x, y, text, style, font_name):
    """Helper to draw a label/annotation."""
    if not text: return

    # Parse Anchor/Offset
    anchor = style.get("anchor", "north west")
    offset_cfg = style.get("offset")
    (def_ox, def_oy), ha, va = _map_anchor(anchor)
    
    if offset_cfg and "," in str(offset_cfg):
        try:
            parts = str(offset_cfg).split(",")
            def_ox, def_oy = float(parts[0]), float(parts[1])
        except: pass
    
    # Bbox
    bbox_cfg = style.get("bbox")
    bbox_props = None
    if bbox_cfg:
        bbox_props = {
            "boxstyle": bbox_cfg.get("style", "round,pad=0.3"),
            "fc": bbox_cfg.get("facecolor", "yellow"),
            "ec": bbox_cfg.get("edgecolor", "none"),
            "lw": float(bbox_cfg.get("linewidth", 1)),
            "alpha": float(bbox_cfg.get("alpha", 0.5))
        }
        
    # Arrow
    arrow_props = None
    arrow_cfg = style.get("arrow")
    if arrow_cfg:
        arrow_props = {
            "arrowstyle": arrow_cfg.get("style", "->"),
            "color": arrow_cfg.get("color", "gray"),
            "linewidth": float(arrow_cfg.get("width", 1.0))
        }

    ax.annotate(
        text,
        xy=(x, y),
        xytext=(def_ox, def_oy),
        textcoords="offset points",
        ha=ha, va=va,
        color=style.get("color", "black"),
        fontsize=float(style.get("fontsize", 10)),
        fontfamily=style.get("fontfamily", font_name),
        bbox=bbox_props,
        arrowprops=arrow_props,
        zorder=20 # Always on top
    )

def _get_group_key(obj, field):
    """Retrieve grouping key from object (metadata or top-level)."""
    if not field: return None
    # Check top level (e.g. injected by aggregator)
    if field in obj: return str(obj[field])
    # Check metadata
    meta = obj.get("metadata", {})
    if field in meta: return str(meta[field])
    return "Default"

def _draw_object(ax, obj, series_index, font_name):
    """Draw a single object (Series or Point) onto the axes."""
    type_ = obj.get("type")
    style = obj.get("style", {})
    z = float(style.get("zorder") or 3)
    
    # Priority for legend text
    label = style.get("legend_label") or style.get("label")
    
    # A. Render Series
    if type_ == "series":
        d = obj.get("data", {})
        X = np.array(d.get("x", []))
        Y = np.array(d.get("y", []))
        if len(X) == 0: return

        # Common Style Config
        line_cfg = style.get("line", {})
        bar_cfg = style.get("bar", {})
        plot_type = style.get("plot_type", "line")
        
        # Determine Color (Explicit)
        c = line_cfg.get("color") 
        # Note: For bar plots, we might want a specific bar color, 
        # but reusing line.color is consistent with previous logic.

        actual_color = c # Fallback if not auto-assigned

        # --- Branch 1: Bar Plot ---
        if plot_type == "bar":
            bars = ax.bar(X, Y,
                   width=float(bar_cfg.get("width") or 0.8),
                   color=c,
                   alpha=float(line_cfg.get("alpha") or 1.0),
                   label=label,
                   zorder=z)
            # Capture actual color
            if len(bars) > 0:
                actual_color = bars[0].get_facecolor()
            
            # Bar plots typically don't need the 'fill' logic below (which is for area charts).
            # If fill is explicitly active, we could allow it, but usually it conflicts visually.
            # We'll skip A2 for bar plots to avoid clutter.

        # --- Branch 2: Line Plot (Default) ---
        else:
            # Plot Line
            lines = ax.plot(X, Y, 
                    color=c, 
                    linewidth=float(line_cfg.get("width") or 1.5),
                    linestyle=line_cfg.get("style", "-"),
                    alpha=float(line_cfg.get("alpha") or 1.0) if line_cfg.get("alpha") is not None else None,
                    label=label,
                    zorder=z)
            
            # Capture actual color
            if lines:
                actual_color = lines[0].get_color()
            
            # A2. Fill Logic (Only for Line/Area plots)
            fill_cfg = style.get("fill", {})
            f_active = fill_cfg.get("active")
            # f_alpha could be a string or a float
            raw_alpha = fill_cfg.get("alpha")
            try: f_alpha = float(raw_alpha) if raw_alpha is not None else 0.2
            except: f_alpha = 0.2
            
            # Final safeguard: ensure active is a true boolean and alpha is positive
            if f_active is True and f_alpha > 0:
                # Smart Color: Fill -> Line (Config) -> Line (Actual) -> Default
                fill_c = fill_cfg.get("color") or line_cfg.get("color") or actual_color
                
                target_id = fill_cfg.get("target_id")
                base_y = 0 # Default scalar
                
                # Resolve Baseline
                if target_id == "zero": base_y = 0
                elif target_id == "min": base_y = np.min(Y)
                elif target_id == "max": base_y = np.max(Y)
                elif target_id in series_index:
                    target_data = series_index[target_id]
                    tx, ty = target_data["x"], target_data["y"]
                    
                    # CRITICAL FIX: np.interp requires INCREASING xp. 
                    # XPS Binding Energy is usually DECREASING.
                    if len(tx) > 1 and tx[0] > tx[-1]:
                        base_y = np.interp(X, tx[::-1], ty[::-1])
                    else:
                        base_y = np.interp(X, tx, ty)
                
                grad_dir = fill_cfg.get("gradient_dir")
                
                # --- Gradient Rendering ---
                if grad_dir and str(grad_dir).lower() in ["up", "down"]:
                    try:
                        # 1. Create Clip Polygon
                        verts_base = list(zip(X, base_y)) if hasattr(base_y, "__len__") else [(x, base_y) for x in X]
                        verts_top = list(zip(X, Y))
                        verts = verts_base + verts_top[::-1]
                        poly = Polygon(verts, transform=ax.transData)
                        
                        # 2. Bounding Box
                        xmin, xmax = np.min(X), np.max(X)
                        # Handle scalar base_y
                        min_base = np.min(base_y) if hasattr(base_y, "__len__") else base_y
                        max_base = np.max(base_y) if hasattr(base_y, "__len__") else base_y
                        ymin, ymax = min(min_base, np.min(Y)), max(max_base, np.max(Y))
                        
                        # 3. Generate Gradient Matrix
                        N = 256
                        base_rgba = to_rgba(fill_c)
                        
                        alphas = np.linspace(f_alpha, 1.0, N)
                        if str(grad_dir).lower() == "down":
                            alphas = np.flip(alphas)
                            
                        gradient = np.zeros((N, 1, 4))
                        gradient[:, 0, :3] = base_rgba[:3]
                        gradient[:, 0, 3] = alphas
                        
                        im = ax.imshow(gradient, extent=[xmin, xmax, ymin, ymax], 
                                      aspect='auto', origin='lower', zorder=z-0.1)
                        im.set_clip_path(poly)
                        
                    except Exception as e:
                        logger.error(f"Gradient fill failed: {e}")
                
                # --- Standard Solid Fill ---
                else:
                    ax.fill_between(X, base_y, Y,
                                    color=fill_c,
                                    alpha=f_alpha,
                                    zorder=z - 0.1)

        # A4. Annotation (Inline)
        ann = obj.get("annotation")
        if ann and ann.get("active"):
            _draw_annotation(ax, ann.get("data_x"), ann.get("data_y"), 
                             ann.get("text"), ann.get("style", {}), font_name)

    # B. Render Points
    elif type_ == "point":
        # Support both 'points' list and top-level 'x','y'
        points = obj.get("points", [])
        if not points and "x" in obj and "y" in obj:
            points = [{"x": obj["x"], "y": obj["y"]}]
            
        if not points: return
        
        # Track if we've added the label to avoid duplicates in the same group
        label_added = False

        for p in points:
            x, y = p.get("x"), p.get("y")
            if x is None or y is None: continue
            
            # Marker
            # Always draw marker, defaulting if empty
            m_cfg = style.get("marker") or {} 
            
            current_label = None
            if not label_added:
                current_label = label
                label_added = True
                
            ax.plot(x, y, 
                    marker=m_cfg.get("style", "o"),
                    color=m_cfg.get("color", "red"),
                    markersize=float(m_cfg.get("size", 5)),
                    linestyle="None",
                    label=current_label, # Add label for legend
                    zorder=15)
            
            # Label (Annotation)
            l_cfg = style.get("label", {})
            if l_cfg:
                _draw_annotation(ax, x, y, l_cfg.get("text"), l_cfg, font_name)


def json_plot_points(
    tool_name: str,
    source_json: Union[str, List[str]],
    
    # Global Figure Settings
    fig_width: float | None = None,
    fig_height: float | None = None,
    dpi: int | None = None,
    title: str | None = None,
    xlabel: str | None = None,
    ylabel: str | None = None,
    font_name: str | None = None,
    
    # Plot Config
    plot_grid: bool | None = None,
    show_xticks: bool | None = True,
    show_yticks: bool | None = True,
    x_scale: str = "linear", # linear, log
    y_scale: str = "linear",
    y_axis_from_zero: bool | None = None,
    
    # Faceting / Matrix Plot
    column_by: str | None = None,
    row_by: str | None = None,
    share_x: bool | None = True,
    share_y: bool | None = True,
    
    # Facet Styling
    facet_wspace: float | None = 0.0,
    facet_hspace: float | None = 0.0,
    facet_title_template: str | None = None, # If None, hide title
    facet_title_loc: str = "top", # top, inside_top_left, ...
    
    # Legend Styling
    show_legend: bool = True,
    legend_loc: str = "best",
    legend_labels: str | None = None,
    legend_sort: str | None = None,
    legend_ncol: int | None = 1,
) -> None:
    
    # ... (Load Data) ...
    json_paths = [source_json] if isinstance(source_json, str) else source_json
    all_objects = []
    
    for p in json_paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_objects.extend(data)
                else:
                    all_objects.append(data)
        except Exception as e:
            logger.error(f"Failed to load JSON {p}: {e}")

    if not all_objects:
        logger.warning("No data found to plot.")
        return

    # --- 2. Build Series Index (Global) ---
    series_index = {} # ID -> {x: np.array, y: np.array}
    for obj in all_objects:
        if obj.get("type") == "series" and "id" in obj:
            d = obj.get("data", {})
            series_index[obj["id"]] = {
                "x": np.array(d.get("x", [])),
                "y": np.array(d.get("y", []))
            }

    # --- 3. Faceting Logic ---
    rows = set()
    cols = set()
    grid_map = {} # (r_key, c_key) -> [obj_list]
    
    for obj in all_objects:
        r = _get_group_key(obj, row_by)
        c = _get_group_key(obj, column_by)
        rows.add(r)
        cols.add(c)
        
        key = (r, c)
        if key not in grid_map: grid_map[key] = []
        grid_map[key].append(obj)
        
    sorted_rows = sorted([x for x in rows if x is not None])
    sorted_cols = sorted([x for x in cols if x is not None])
    
    # Handle case where no grouping keys found (default to single plot)
    if not sorted_rows: sorted_rows = [None]
    if not sorted_cols: sorted_cols = [None]
    
    nrows = len(sorted_rows)
    ncols = len(sorted_cols)

    # --- 4. Setup Figure ---
    # User provides Total Width/Height. Defaults: 8x6
    total_w = float(fig_width or 8.0)
    total_h = float(fig_height or 6.0)
    dpi = dpi or 300
    font_name = font_name or "Arial"
    
    # squeeze=False ensures axes is always 2D array [row, col]
    fig, axes = plt.subplots(nrows, ncols, 
                             figsize=(total_w, total_h), 
                             dpi=dpi,
                             sharex=share_x, 
                             sharey=share_y,
                             squeeze=False)
    
    global_handles = {} # label -> handle (deduplicated)

    # --- 5. Render Loop ---
    for i, r_key in enumerate(sorted_rows):
        for j, c_key in enumerate(sorted_cols):
            ax = axes[i, j]
            objs = grid_map.get((r_key, c_key), [])
            
            # --- Subplot Title ---
            # ONLY if facet_title_template is provided
            t_str = ""
            if facet_title_template and str(facet_title_template).strip():
                title_ctx = {"row": r_key, "col": c_key, "val": ""}
                if r_key and c_key: title_ctx["val"] = f"{r_key} | {c_key}"
                elif r_key: title_ctx["val"] = str(r_key)
                elif c_key: title_ctx["val"] = str(c_key)
                
                try: t_str = facet_title_template.format(**title_ctx)
                except: t_str = title_ctx["val"]
            
            if t_str and t_str.strip():
                if facet_title_loc == "top":
                    ax.set_title(t_str, fontsize=10, family=font_name)
                elif facet_title_loc != "hidden":
                    # Handle "inside top left" etc.
                    loc_map = {
                        "inside top left": (0.02, 0.95, "left", "top"),
                        "inside top right": (0.98, 0.95, "right", "top"),
                        "inside bottom left": (0.02, 0.05, "left", "bottom"),
                        "inside bottom right": (0.98, 0.05, "right", "bottom")
                    }
                    pos = loc_map.get(facet_title_loc.lower().replace("_", " "), (0.5, 0.95, "center", "top"))
                    ax.text(pos[0], pos[1], t_str, transform=ax.transAxes, 
                            ha=pos[2], va=pos[3], fontsize=10, family=font_name,
                            bbox=dict(facecolor='white', alpha=0.5, edgecolor='none'))

            # Draw
            for obj in objs:
                _draw_object(ax, obj, series_index, font_name)
            
            # Collect Handles for Global Legend
            if show_legend and legend_loc != "hidden":
                h_list, l_list = ax.get_legend_handles_labels()
                for _h, _l in zip(h_list, l_list):
                    if _l and _l not in global_handles:
                        global_handles[_l] = _h

            # Axis Config
            ax.set_xscale(x_scale)
            ax.set_yscale(y_scale)
            
            if plot_grid: ax.grid(True, linestyle="--", alpha=0.6)
            
            # Ticks Visibility
            if not show_xticks:
                ax.set_xticks([])
            if not show_yticks:
                ax.set_yticks([])

            # Labels (Outer Only logic)
            is_bottom = (i == nrows - 1)
            is_left = (j == 0)
            
            if xlabel and (not share_x or is_bottom):
                ax.set_xlabel(xlabel, family=font_name)
            if ylabel and (not share_y or is_left):
                ax.set_ylabel(ylabel, family=font_name)

            # --- Y Axis From Zero Logic ---
            if y_scale == "linear" and not share_y:
                # Per-subplot logic (only if axes are not shared)
                if y_axis_from_zero:
                    ylim = ax.get_ylim()
                    if ylim and len(ylim) == 2:
                        ymin, ymax = ylim
                        if ymin > 0: ax.set_ylim(bottom=0)
                        elif ymax < 0: ax.set_ylim(top=0)
                elif y_axis_from_zero is not None:
                    # Auto shrink per subplot
                    all_y = []
                    for obj in objs:
                        if obj.get("type") == "series": all_y.extend(obj.get("data", {}).get("y", []))
                        elif obj.get("type") == "point":
                            if "y" in obj: all_y.append(obj["y"])
                            for p in obj.get("points", []):
                                if "y" in p: all_y.append(p["y"])
                    valid_y = [float(y) for y in all_y if y is not None]
                    if valid_y:
                        d_min, d_max = min(valid_y), max(valid_y)
                        d_range = max(1.0, d_max - d_min)
                        if d_min > 0:
                            curr_ymin, _ = ax.get_ylim()
                            if curr_ymin <= 0: ax.set_ylim(bottom=d_min - 0.05 * d_range)
                        elif d_max < 0:
                            _, curr_ymax = ax.get_ylim()
                            if curr_ymax >= 0: ax.set_ylim(top=d_max + 0.05 * d_range)

    # --- Post-process Shared Y Axis (if applicable) ---
    if y_scale == "linear" and share_y and y_axis_from_zero is not None:
        # Use first axis to apply shared limits
        target_ax = axes[0, 0]
        if y_axis_from_zero:
            # Force include 0 for the whole shared set
            ylim = target_ax.get_ylim()
            if ylim and len(ylim) == 2:
                ymin, ymax = ylim
                if ymin > 0: target_ax.set_ylim(bottom=0)
                elif ymax < 0: target_ax.set_ylim(top=0)
        else:
            # Auto shrink for the whole shared set
            all_global_y = []
            for obj in all_objects:
                if obj.get("type") == "series": all_global_y.extend(obj.get("data", {}).get("y", []))
                elif obj.get("type") == "point":
                    if "y" in obj: all_global_y.append(obj["y"])
                    for p in obj.get("points", []):
                        if "y" in p: all_global_y.append(p["y"])
            valid_y = [float(y) for y in all_global_y if y is not None]
            if valid_y:
                d_min, d_max = min(valid_y), max(valid_y)
                d_range = max(1.0, d_max - d_min)
                if d_min > 0:
                    curr_ymin, _ = target_ax.get_ylim()
                    if curr_ymin <= 0: target_ax.set_ylim(bottom=d_min - 0.05 * d_range)
                elif d_max < 0:
                    _, curr_ymax = target_ax.get_ylim()
                    if curr_ymax >= 0: target_ax.set_ylim(top=d_max + 0.05 * d_range)

    # --- 6. Global Legend ---
    if show_legend and legend_loc != "hidden" and global_handles:
        # Initial list (order from dict keys is insertion order in Py3.7+)
        raw_labels = list(global_handles.keys())
        raw_handles = list(global_handles.values())
        
        final_labels, final_handles = raw_labels, raw_handles

        # 1. Sort Logic
        if legend_sort and str(legend_sort).strip():
            patterns = [p.strip() for p in str(legend_sort).split(",") if p.strip()]
            if patterns:
                items = list(zip(raw_labels, raw_handles))
                sorted_items = []
                seen = set()
                
                for pat in patterns:
                    # Find matches for this pattern
                    # Sort matches naturally (alphabetical) within the pattern group
                    matches = []
                    for l, h in items:
                        if l in seen: continue
                        if fnmatch.fnmatch(str(l), pat):
                            matches.append((l, h))
                    
                    matches.sort(key=lambda x: str(x[0]))
                    
                    for l, h in matches:
                        sorted_items.append((l, h))
                        seen.add(l)
                
                # Remaining items (not matched by any pattern)
                remaining = []
                for l, h in items:
                    if l not in seen:
                        remaining.append((l, h))
                remaining.sort(key=lambda x: str(x[0]))
                
                sorted_items.extend(remaining)
                
                if sorted_items:
                    final_labels = [x[0] for x in sorted_items]
                    final_handles = [x[1] for x in sorted_items]

        # 2. Rename Logic (Override)
        if legend_labels and str(legend_labels).strip():
            custom_lbls = [s.strip() for s in str(legend_labels).split(",") if s.strip()]
            # Only use custom labels up to the number of handles
            limit = min(len(custom_lbls), len(final_handles))
            final_labels[:limit] = custom_lbls[:limit]
            
        # Draw Legend
        try:
            if "outside" in legend_loc:
                # Basic outside mapping
                anchor_map = {
                    "outside right": (1.05, 0.5),
                    "outside top": (0.5, 1.05),
                    "outside upper right": (1.05, 1.0)
                }
                # Fallback loc
                base_loc = "center left" if "right" in legend_loc else "lower center"
                bbox = anchor_map.get(legend_loc.lower().replace("_", " "), (1.05, 0.5))
                fig.legend(final_handles, final_labels, loc=base_loc, bbox_to_anchor=bbox, ncol=legend_ncol or 1)
            else:
                # Inside figure (best, upper right, etc)
                # fig.legend does NOT support loc="best".
                real_loc = legend_loc
                if real_loc == "best":
                    # Fallback for figure legend
                    real_loc = "upper right" 
                
                fig.legend(final_handles, final_labels, loc=real_loc, ncol=legend_ncol or 1)
        except Exception as e:
            logger.error(f"Legend draw failed: {e}")

    # --- 7. Final Polish ---
    if title: 
        fig.suptitle(title, family=font_name, fontsize=14)
        
    out_name = "rendered_points.png"
    
    # 1. tight_layout first to fit labels
    # If using outside legend, tight_layout might need adjustment
    rect = [0, 0, 1, 1]
    if title: rect[3] = 0.95 # Leave room for suptitle
    if "outside right" in legend_loc: rect[2] = 0.85 # Shrink width
    
    plt.tight_layout(rect=rect)
    
    # 2. Apply custom spacing (wspace/hspace)
    # If user wants 0 gap, this overrides tight_layout's spacing
    if facet_wspace is not None and facet_hspace is not None:
        plt.subplots_adjust(wspace=facet_wspace, hspace=facet_hspace)
    
    # bbox_inches='tight' ensures outside legends are not clipped
    fig.savefig(out_name, dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    
    return_file(out_name)

regist_tool(json_plot_points)