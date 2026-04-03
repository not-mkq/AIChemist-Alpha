"""
meta_runtime.py

Meta Tool 运行时支持：
- 注册 Meta Tool 配置
- 执行 Map 和 Sequence 两种模式的 Meta Tool
- 支持递归调用（Meta Tool 调用 Meta Tool）
"""
from __future__ import annotations

import os
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from db import get_connection, list_batches, list_items
from merge_runtime import run_merge_tool
from request_checker import (
    check_merge_tool_request,
    check_tool_request,
    get_run_param_type_map,
)
from errors import RunFailure
from tool_runtime import (
    run_tool,
    _get_project_tool_config,
    expand_single_tool_iterations,
    _collect_text_values,
)
from scope_registry import get_child_scope

# =========================
# 注册表与进度追踪
# =========================

@dataclass
class MetaToolInfo:
    name: str
    config: Dict[str, Any]


META_TOOLS_REGISTRY: Dict[str, MetaToolInfo] = {}

# 全局进度追踪：{run_id: {"total": int, "current": int, "status": str, "percent": int, "message": str}}
PROGRESS_REGISTRY: Dict[str, Dict[str, Any]] = {}
_progress_lock = threading.Lock()


def get_task_progress(run_id: str) -> Optional[Dict[str, Any]]:
    """获取指定任务的进度"""
    return PROGRESS_REGISTRY.get(run_id)


def _set_progress(run_id: Optional[str], current: int, total: int, status: str = "running", message: str = ""):
    """记录任务进度。仅 Map 工具会更新真实的 current/total。"""
    if not run_id:
        return
    with _progress_lock:
        PROGRESS_REGISTRY[run_id] = {
            "total": total,
            "current": current,
            "status": status,
            "message": message,
            "percent": int(current / total * 100) if total > 0 else 0
        }


def _ensure_ok(result: Dict[str, Any], tool_name: str, scope: str, batch: Optional[str], item: Optional[str]) -> None:
    """Raise RunFailure if result is not ok."""
    if result.get("status") != "ok":
        raise RunFailure(
            {
                "tool": tool_name,
                "scope": scope,
                "batch": batch,
                "item": item,
                **result,
            }
        )


def _get_alt_candidates(config: Dict[str, Any]) -> List[str]:
    """统一提取 Alt 模式的候选工具列表。"""
    candidates = (
        config.get("tool_alternatives")
        or config.get("tool_candidates")
        or config.get("tools")
        or []
    )
    return [c for c in candidates if c]


def load_meta_tools() -> None:
    """
    从文件系统加载 Meta Tool 配置并注册到 META_TOOLS_REGISTRY。
    
    注意：此函数在系统启动时调用，用于内存缓存。
    实际的工具配置从 tool-instances/<profile>/*.config.json 文件读取。
    """
    from profile_config import get_tool_instances_dir
    
    instances_dir = get_tool_instances_dir()
    if not instances_dir.exists():
        return
    
    # 递归扫描所有配置文件
    for config_file in instances_dir.rglob("*.config.json"):
        # 跳过模板文件
        if config_file.name.endswith(".template.config.json"):
            continue
        
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if not isinstance(data, dict):
                continue
            
            # 计算相对于 instances_dir 的路径
            rel_path = config_file.relative_to(instances_dir)
            if rel_path.parent != Path("."):
                dir_path = str(rel_path.parent).replace("\\", "/")
            else:
                dir_path = ""
            
            for tool_instance_name, config in data.items():
                if not isinstance(config, dict):
                    continue
                
                # 严格校验：code_name 是 Meta 运行时的唯一身份标识，不再支持 'mode'
                code_name = config.get("code_name")
                if code_name not in {"map", "sequence", "alt"}:
                    # 仅在定义了 tool_type=meta 但 code_name 错误时打印警告，避免干扰 Single 工具扫描
                    if config.get("tool_type") == "meta":
                        print(f"[META-TOOL] Warning: Meta tool '{tool_instance_name}' has invalid or missing code_name '{code_name}'. Skipping.")
                    continue
                
                # 构建完整路径标识
                if dir_path:
                    tool_path = f"{dir_path}/{tool_instance_name}"
                else:
                    tool_path = tool_instance_name
                
                if tool_path in META_TOOLS_REGISTRY:
                    print(f"[META-TOOL] Warning: Meta tool '{tool_path}' already in registry, skipping duplicate")
                    continue
                
                # 必填字段颗粒度校验
                error = None
                if code_name == "map":
                    if "tool" not in config:
                        error = "Map mode requires 'tool' field"
                elif code_name == "sequence":
                    # 同时兼容新旧字段名，但必须有其一
                    if "tool_sequence" not in config and "steps" not in config:
                        error = "Sequence mode requires 'tool_sequence' or 'steps' field"
                elif code_name == "alt":
                    if not _get_alt_candidates(config):
                        error = "Alt mode requires tool candidates"
                
                if error:
                    print(f"[META-TOOL] Warning: Skipping '{tool_path}': {error}")
                    continue
                
                META_TOOLS_REGISTRY[tool_path] = MetaToolInfo(
                    name=tool_path,
                    config=config
                )
                print(f"[META-TOOL] Loaded from file: {tool_path} (code_name={code_name})")
        except Exception as e:
            print(f"[META-TOOL] Error loading {config_file}: {e}")


# 工具不再在启动时自动加载，改为按需加载
# load_meta_tools()  # 已移除：工具等到使用时再注册


# =========================
# 工具类型判断
# =========================

def get_tool_type(tool_name: str, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """
    根据工具实例名判断工具类型（从文件系统查询）。
    
    参数：
        tool_name: 工具实例名
        conn: 数据库连接（可选，保留以保持兼容性，但不再使用）
    
    返回：
        "single" | "merge" | "meta" | None
    """
    from tool_registry import get_tool_type_from_file
    return get_tool_type_from_file(tool_name)


def _get_meta_code_name(tool_name: str) -> Optional[str]:
    """
    获取 Meta Tool 的具体模式 (map/sequence/alt)。
    """
    from tool_registry import get_tool_config_from_file
    cfg = get_tool_config_from_file(tool_name)
    return cfg.get("code_name") if cfg else None


# =========================
# 可用性检查
# =========================

def _adjust_scope_for_tool(tool_name: str, scope: str, conn: sqlite3.Connection) -> str:
    """
    为候选工具调整 scope。
    主要用于 Sequence/Alt 模式下的子工具 Scope 计算。
    """
    tool_type = get_tool_type(tool_name, conn)
    
    # Map to scope_registry ToolType
    reg_type = tool_type
    if tool_type == "meta":
        meta_code = _get_meta_code_name(tool_name)
        if meta_code == "map":
            reg_type = "meta_map"
        elif meta_code == "sequence":
            reg_type = "meta_sequence"
        elif meta_code == "alt":
            reg_type = "meta_alt"
            
    # Assume sequence-like parent for adjustment
    child_scope = get_child_scope("sequence", scope, reg_type)
    return child_scope or scope


def check_meta_tool_available(
    meta_tool_name: str,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    conn: Optional[sqlite3.Connection] = None,
    available_labels: Optional[Set[str]] = None,
    available_result_cols: Optional[Set[str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    检查 Meta Tool 在给定参数下是否可用。
    
    参数：
        meta_tool_name: Meta Tool 的名字
        project: 项目名
        batch: 批次名（可选）
        item: 条目名（可选）
        scope: 调用时的 scope（Map: item->batch/batch->project/item->project；Sequence: item/batch/project；Alt: 透传给候选工具）
        conn: 数据库连接（可选）
    
    返回：
        (is_available, error_info)
        - is_available: 是否可用
        - error_info: 如果不可用，返回错误信息字典；如果可用，返回 None
    """
    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True
    
    try:
        from tool_registry import get_tool_config_from_file
        
        config = get_tool_config_from_file(meta_tool_name)
        if config is None:
            return False, {
                "reason": "tool_not_found",
                "detail": f"Meta tool '{meta_tool_name}' not registered"
            }
        
        # 确认实例类型仍为 meta（避免误用）
        tool_type = get_tool_type(meta_tool_name, conn)
        if tool_type != "meta":
            return False, {
                "reason": "invalid_tool_type",
                "detail": f"Tool '{meta_tool_name}' is not a meta tool (type: {tool_type})"
            }
        
        mode = config.get("code_name")
        inherited_labels: Set[str] = set(available_labels or [])
        inherited_result_cols: Set[str] = set(available_result_cols or [])
        if mode == "map":
            # Map mode: scope 是运行时参数，指定迭代范围
            map_scope = scope  # scope 就是 item->batch/batch->project/item->project
            
            # 根据 map_scope 确定迭代范围
            if map_scope == "item->batch":
                if not batch:
                    return False, {
                        "reason": "missing_batch",
                        "detail": "Map scope 'item->batch' requires batch parameter"
                    }
                # 查询该 batch 下的所有 item
                items = [row["name"] for row in list_items(conn, project, batch)]
                if not items:
                    return False, {
                        "reason": "no_items",
                        "detail": f"No items found in batch '{batch}'"
                    }
                # 对每个 item，检查被调用的工具是否可用
                called_tool = config.get("tool")
                tool_scope = _determine_tool_scope(called_tool, map_scope, conn)
                if tool_scope is None:
                    return False, {
                        "reason": "invalid_map_scope",
                        "detail": f"Map scope '{map_scope}' calling '{called_tool}' is not supported"
                    }
                for item_name in items:
                    is_ok, error = _check_called_tool(
                        called_tool,
                        project,
                        batch,
                        item_name,
                        tool_scope,
                        conn,
                        available_labels=inherited_labels,
                        available_result_cols=inherited_result_cols,
                    )
                    if not is_ok:
                        return False, error
            
            elif map_scope == "batch->project":
                # 查询该 project 下的所有 batch
                batches = [row["name"] for row in list_batches(conn, project)]
                if not batches:
                    return False, {
                        "reason": "no_batches",
                        "detail": f"No batches found in project '{project}'"
                    }
                # 对每个 batch，检查被调用的工具是否可用
                called_tool = config.get("tool")
                # 先尝试获取第一个 batch 来测试配置
                if batches:
                    test_batch = batches[0]
                    tool_scope = _determine_tool_scope(called_tool, map_scope, conn)
                    is_ok, error = _check_called_tool(
                        called_tool,
                        project,
                        test_batch,
                        None,
                        tool_scope,
                        conn,
                        available_labels=inherited_labels,
                        available_result_cols=inherited_result_cols,
                    )
                    if not is_ok:
                        return False, error
                # 如果第一个 batch 检查通过，其他 batch 也应该通过（配置相同）
            
            elif map_scope == "item->project":
                # 查询该 project 下的所有 item（需要嵌套查询）
                batches = [row["name"] for row in list_batches(conn, project)]
                if not batches:
                    return False, {
                        "reason": "no_batches",
                        "detail": f"No batches found in project '{project}'"
                    }
                # 对每个 batch 下的每个 item，检查被调用的工具是否可用
                called_tool = config.get("tool")
                tool_scope = _determine_tool_scope(called_tool, map_scope, conn)
                if tool_scope is None:
                    return False, {
                        "reason": "invalid_map_scope",
                        "detail": f"Map scope '{map_scope}' calling '{called_tool}' is not supported"
                    }
                for batch_name in batches:
                    items = [row["name"] for row in list_items(conn, project, batch_name)]
                    for item_name in items:
                        is_ok, error = _check_called_tool(
                            called_tool,
                            project,
                            batch_name,
                            item_name,
                            tool_scope,
                            conn,
                            available_labels=inherited_labels,
                            available_result_cols=inherited_result_cols,
                        )
                        if not is_ok:
                            return False, error
            
            else:
                return False, {
                    "reason": "invalid_map_scope",
                    "detail": f"Invalid map scope: {map_scope}"
                }
            
            return True, None
        
        elif mode == "sequence":
            # Sequence mode: scope 是调用时的 scope (item/batch/project)
            tool_sequence = config.get("tool_sequence", [])
            
            # 维护序列中前面工具生成的 labels 和 result_cols
            available_labels_set: set[str] = set(inherited_labels)
            available_result_cols_set: set[str] = set(inherited_result_cols)
            
            for tool_name in tool_sequence:
                adj_scope = _adjust_scope_for_tool(tool_name, scope, conn)
                is_ok, error = _check_called_tool(
                    tool_name,
                    project,
                    batch,
                    item,
                    adj_scope,
                    conn,
                    available_labels=available_labels_set,
                    available_result_cols=available_result_cols_set,
                )
                if not is_ok:
                    return False, error
                
                tool_output_labels, tool_output_cols = _get_sequence_step_outputs(
                    tool_name,
                    project,
                    batch,
                    item,
                    adj_scope,
                    conn,
                    available_labels_set,
                    available_result_cols_set,
                )
                available_labels_set.update(tool_output_labels)
                available_result_cols_set.update(tool_output_cols)
            
            return True, None
        
        elif mode == "alt":
            candidates = _get_alt_candidates(config)
            if not candidates:
                return False, {
                    "reason": "invalid_config",
                    "detail": "Alt 模式需要至少一个候选工具"
                }

            errors: List[Dict[str, Any]] = []
            for tool_name in candidates:
                adj_scope = _adjust_scope_for_tool(tool_name, scope, conn)
                is_ok, error = _check_called_tool(
                    tool_name,
                    project,
                    batch,
                    item,
                    adj_scope,
                    conn,
                    available_labels=inherited_labels,
                    available_result_cols=inherited_result_cols,
                )
                if is_ok:
                    return True, None
                errors.append({"tool": tool_name, **(error or {})})

            return False, {
                "reason": "all_alternatives_unavailable",
                "detail": "所有候选工具均不可用",
                "errors": errors,
            }
        
        return False, {
            "reason": "invalid_mode",
            "detail": f"Unknown mode: {mode}"
        }
    
    finally:
        if owns_conn:
            conn.close()


def _check_called_tool(
    tool_name: str,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    conn: sqlite3.Connection,
    available_labels: Optional[set[str]] = None,
    available_result_cols: Optional[set[str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    检查被调用的工具是否可用（递归检查）。
    
    如果工具是 meta tool，递归调用 check_meta_tool_available。
    """
    # 使用 get_tool_type 判断工具类型（所有工具都有实例名）
    tool_type = get_tool_type(tool_name, conn)
    
    if tool_type is None:
        return False, {
            "reason": "tool_not_found",
            "tool": tool_name,
            "detail": f"Tool '{tool_name}' not found"
        }
    
    cfg = None
    
    if tool_type == "single":
        # Single tool: 使用 request_checker.check_tool_request
        try:
            cfg = _get_project_tool_config(conn, project, tool_name)
            code_name = cfg.get("code_name", tool_name)
            iterations = expand_single_tool_iterations(cfg)
            param_type_map = get_run_param_type_map(code_name, conn=conn)
        except Exception as e:
            reason = "invalid_iter_config" if isinstance(e, ValueError) else "config_error"
            return False, {
                "reason": reason,
                "tool": tool_name,
                "detail": str(e),
            }

        iter_virtual_labels: set[str] = set(available_labels or [])
        iter_virtual_cols: set[str] = set(available_result_cols or [])

        for idx, iteration in enumerate(iterations):
            missing_labels, missing_cols = check_tool_request(
                conn=conn,
                project_name=project,
                batch_name=batch,
                item_name=item,
                input_label_map=iteration.input_label_map,
                run_params=iteration.run_params,
                scope=scope,
                code_name=code_name,
                param_type_map=param_type_map,
                virtual_labels=iter_virtual_labels,
                virtual_result_cols=iter_virtual_cols,
            )

            # 过滤掉序列中前面工具已生成的 labels 和 result_cols
            if available_labels is not None:
                missing_labels = [label for label in missing_labels if label not in available_labels]
            if available_result_cols is not None:
                missing_cols = [c for c in missing_cols if c not in available_result_cols]

            if missing_labels or missing_cols:
                return False, {
                    "reason": "missing_inputs",
                    "tool": tool_name,
                    "missing_labels": missing_labels,
                    "missing_item_results": missing_cols,
                    "iteration_index": idx,
                }

            iter_virtual_labels.update(_collect_text_values(iteration.output_file_label))
            iter_virtual_cols.update(_collect_text_values(iteration.result_col))
        return True, None
    
    elif tool_type == "merge":
        # Merge tool: 使用 request_checker.check_merge_tool_request
        try:
            cfg = _get_project_tool_config(conn, project, tool_name)
            code_name = cfg.get("code_name", tool_name)
            # 将 scope 转换为 merge_mode
            merge_mode_map = {
                "item->batch": "batch_from_items",
                "item->project": "project_from_items",
                "batch->project": "project_from_batches",
            }
            merge_mode = merge_mode_map.get(scope)
            if not merge_mode:
                return False, {
                    "reason": "invalid_scope",
                    "tool": tool_name,
                    "detail": f"Invalid scope '{scope}' for merge tool"
                }
            
            missing_labels, missing_cols = check_merge_tool_request(
                conn=conn,
                project_name=project,
                batch_name=batch,
                merge_mode=merge_mode,
                input_label_map=cfg.get("input_label_map", {}),
                input_cols=cfg.get("input_cols") or {},
                run_params=cfg.get("run_params", {}),
                code_name=code_name,
            )
            
            # 过滤掉序列中前面工具已生成的 labels 和 result_cols
            if available_labels is not None:
                missing_labels = [label for label in missing_labels if label not in available_labels]
            if available_result_cols is not None:
                missing_cols = [c for c in missing_cols if c not in available_result_cols]
            
            if missing_labels or missing_cols:
                return False, {
                    "reason": "missing_inputs",
                    "tool": tool_name,
                    "missing_labels": missing_labels,
                    "missing_results": missing_cols
                }
            return True, None
        except Exception as e:
            return False, {
                "reason": "config_error",
                "tool": tool_name,
                "detail": str(e)
            }
    
    elif tool_type == "meta":
        # Meta tool: 递归调用 check_meta_tool_available
        return check_meta_tool_available(
            tool_name,
            project,
            batch,
            item,
            scope,
            conn,
            available_labels=available_labels,
            available_result_cols=available_result_cols,
        )
    
    return False, {
        "reason": "tool_not_found",
        "tool": tool_name,
        "detail": f"Tool '{tool_name}' not found in any registry"
    }


def _get_tool_outputs(
    tool_name: str,
    project: str,
    scope: str,
    conn: sqlite3.Connection,
) -> Tuple[set[str], set[str]]:
    """
    获取工具的输出 labels 和 result_cols。
    
    参数：
        tool_name: 工具实例名
        project: 项目名
        scope: 工具的 scope
        conn: 数据库连接
    
    返回：
        (output_labels, output_result_cols) 元组
        - output_labels: 工具输出的文件标签集合
        - output_result_cols: 工具输出的结果列集合
    """
    output_labels: set[str] = set()
    output_result_cols: set[str] = set()
    
    def _append_value(target: set[str], value: Optional[Any]) -> None:
        if value is None:
            return
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                target.add(trimmed)
            return
        if isinstance(value, list):
            for item in value:
                _append_value(target, item)
            return
        text = str(value).strip()
        if text:
            target.add(text)

    try:
        # 获取工具类型
        tool_type = get_tool_type(tool_name, conn)
        if not tool_type:
            return output_labels, output_result_cols
        
        # 获取工具配置
        cfg = _get_project_tool_config(conn, project, tool_name)

        if tool_type == "single":
            try:
                iterations = expand_single_tool_iterations(cfg)
            except ValueError:
                iterations = []
            for iteration in iterations:
                _append_value(output_labels, iteration.output_file_label)
                _append_value(output_result_cols, iteration.result_col)
        elif tool_type == "merge":
            _append_value(output_labels, cfg.get("output_file_label"))
            _append_value(output_result_cols, cfg.get("result_col"))
        elif tool_type == "meta":
            mode = cfg.get("code_name")
            if mode == "sequence":
                seq_scope = scope
                for child in cfg.get("tool_sequence", []):
                    child_scope = _adjust_scope_for_tool(child, seq_scope, conn)
                    child_labels, child_cols = _get_tool_outputs(child, project, child_scope, conn)
                    output_labels.update(child_labels)
                    output_result_cols.update(child_cols)
            elif mode == "alt":
                for child in _get_alt_candidates(cfg):
                    child_scope = _adjust_scope_for_tool(child, scope, conn)
                    child_labels, child_cols = _get_tool_outputs(child, project, child_scope, conn)
                    output_labels.update(child_labels)
                    output_result_cols.update(child_cols)
            elif mode == "map":
                called_tool = cfg.get("tool")
                if called_tool:
                    child_scope = _determine_tool_scope(called_tool, scope, conn) or scope
                    child_labels, child_cols = _get_tool_outputs(called_tool, project, child_scope, conn)
                    output_labels.update(child_labels)
                    output_result_cols.update(child_cols)
        else:
            _append_value(output_labels, cfg.get("output_file_label"))
            _append_value(output_result_cols, cfg.get("result_col"))
        
    except Exception:
        # 如果获取配置失败，返回空集合
        pass
    
    return output_labels, output_result_cols


def _get_sequence_step_outputs(
    tool_name: str,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    conn: sqlite3.Connection,
    available_labels: Optional[Set[str]] = None,
    available_result_cols: Optional[Set[str]] = None,
) -> Tuple[set[str], set[str]]:
    """
    针对 Sequence 检查场景，根据当前可用的标签/结果列，推导该步骤实际会产生的输出。

    Alt 模式只返回实际会被选中的候选工具的输出。
    其他模式沿用 _get_tool_outputs 的结果。
    """
    tool_type = get_tool_type(tool_name, conn)
    if tool_type == "meta":
        cfg = _get_project_tool_config(conn, project, tool_name)
        mode = cfg.get("code_name")
        if mode == "alt":
            inherited_labels = set(available_labels or [])
            inherited_cols = set(available_result_cols or [])
            for child in _get_alt_candidates(cfg):
                child_scope = _adjust_scope_for_tool(child, scope, conn)
                is_ok, _ = _check_called_tool(
                    child,
                    project,
                    batch,
                    item,
                    child_scope,
                    conn,
                    available_labels=inherited_labels,
                    available_result_cols=inherited_cols,
                )
                if is_ok:
                    return _get_sequence_step_outputs(
                        child,
                        project,
                        batch,
                        item,
                        child_scope,
                        conn,
                        inherited_labels,
                        inherited_cols,
                    )
            return set(), set()
    return _get_tool_outputs(tool_name, project, scope, conn)


def _determine_tool_scope(called_tool: str, map_scope: str, conn: sqlite3.Connection) -> Optional[str]:
    """
    根据被调用工具的类型和 Map scope 确定工具的实际 scope。
    """
    tool_type = get_tool_type(called_tool, conn)
    reg_type = tool_type
    if tool_type == "meta":
        meta_code = _get_meta_code_name(called_tool)
        if meta_code == "map":
            reg_type = "meta_map"
        elif meta_code == "sequence":
            reg_type = "meta_sequence"
        elif meta_code == "alt":
            reg_type = "meta_alt"
            
    return get_child_scope("map", map_scope, reg_type)


# =========================
# Meta Tool 执行
# =========================

def run_meta_tool(
    project_name: str,
    tool_instance_name: str,
    batch_name: Optional[str] = None,
    item_name: Optional[str] = None,
    scope: str = "",
    conn: Optional[sqlite3.Connection] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    执行 Meta Tool。
    
    参数：
        project_name: 项目名
        tool_instance_name: Meta Tool 的名字
        batch_name: 批次名（可选）
        item_name: 条目名（可选）
        scope: 调用时的 scope
            - Map mode: item->batch/batch->project/item->project
            - Sequence mode: item/batch/project
        conn: 数据库连接（可选）
    
    返回：
        执行结果字典
    """
    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True
    
    try:
        # 从 tool_instances 表获取 Meta Tool 配置
        from tool_registry import get_tool_config_from_file
        
        config = get_tool_config_from_file(tool_instance_name)
        if config is None:
            return {
                "status": "error",
                "reason": "tool_not_found",
                "detail": f"Meta tool '{tool_instance_name}' not found in config files"
            }
        
        # 验证工具类型
        tool_type = get_tool_type(tool_instance_name, conn)
        if tool_type != "meta":
            return {
                "status": "error",
                "reason": "invalid_tool_type",
                "detail": f"Tool '{tool_instance_name}' is not a meta tool (type: {tool_type})"
            }
        
        mode = config.get("code_name")
        
        # 先检查可用性
        is_available, error_info = check_meta_tool_available(
            tool_instance_name, project_name, batch_name, item_name, scope, conn
        )
        if not is_available:
            return {
                "status": "error",
                "reason": "tool_unavailable",
                **error_info
            }
        
        try:
            if mode == "map":
                return _run_map_mode(
                    conn, project_name, batch_name, item_name, scope, config, run_id
                )
            elif mode == "sequence":
                return _run_sequence_mode(
                    conn, project_name, batch_name, item_name, scope, config, run_id
                )
            elif mode == "alt":
                return _run_alt_mode(
                    conn, project_name, batch_name, item_name, scope, config, run_id
                )
            else:
                return {
                    "status": "error",
                    "reason": "invalid_mode",
                    "detail": f"Unknown mode: {mode}"
                }
        except RunFailure:
            raise
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            return {
                "status": "error",
                "reason": "meta_tool_exception",
                "detail": f"{str(e)}\n{tb_str}",
                "exception_type": e.__class__.__name__
            }
    
    finally:
        if owns_conn:
            conn.close()


def _load_global_config() -> Dict[str, Any]:
    try:
        with open("config/project_config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _parallel_worker_task(ctx: Dict[str, Any], args: Tuple, run_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Top-level worker function for ProcessPoolExecutor"""
    from db import get_connection
    conn = get_connection()
    try:
        # args: (tool_name, project, batch, item, scope)
        res = _call_tool(*args, conn=conn, run_id=run_id)
        return ctx, res
    except Exception as e:
        import traceback
        return ctx, {"status": "error", "reason": "process_exception", "detail": f"{e}\n{traceback.format_exc()}"}
    finally:
        conn.close()

def _run_map_mode(
    conn: sqlite3.Connection,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    config: Dict[str, Any],
    run_id: str,
) -> Dict[str, Any]:
    """
    执行 Map 模式的 Meta Tool (支持并行)。
    """
    map_scope = scope  # scope 就是 item->batch/batch->project/item->project
    called_tool = config.get("tool")
    
    global_cfg = _load_global_config()
    parallel = config.get("parallel", global_cfg.get("parallel_map", False))
    if parallel:
        # Parallel Map implementation
        # 优先级：工具配置 > 全局配置 > 平台默认 (Windows 61, Linux 100)
        platform_max = 61 if os.name == 'nt' else 100
        default_workers = global_cfg.get("max_workers", platform_max)
        
        max_workers = config.get("max_workers", default_workers)
        # 强制安全性限制
        max_workers = min(max_workers, platform_max)
        
        results = []
        import concurrent.futures

    
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    
    # 任务列表：List[Tuple[ContextDict, ToolArgsTuple]]
    # ToolArgs: (tool_name, project, batch, item, scope)
    tasks = []
    
    if map_scope == "item->batch":
        if not batch:
            return {
                "status": "error",
                "reason": "missing_batch",
                "detail": "Map scope 'item->batch' requires batch parameter"
            }
        # 查询该 batch 下的所有 item
        items = [row["name"] for row in list_items(conn, project, batch)]
        for item_name in items:
            tasks.append(({"item": item_name}, (called_tool, project, batch, item_name, "item")))
            
    elif map_scope == "batch->project":
        # 查询该 project 下的所有 batch
        batches = [row["name"] for row in list_batches(conn, project)]
        tool_scope = _determine_tool_scope(called_tool, map_scope, conn)
        if tool_scope is None:
            return {
                "status": "error",
                "reason": "invalid_map_scope",
                "detail": f"Map scope '{map_scope}' calling '{called_tool}' is not supported"
            }
        for batch_name in batches:
            tasks.append(({"batch": batch_name}, (called_tool, project, batch_name, None, tool_scope)))
    
    elif map_scope == "item->project":
        # 查询该 project 下的所有 item（嵌套查询）
        batches = [row["name"] for row in list_batches(conn, project)]
        tool_scope = _determine_tool_scope(called_tool, map_scope, conn)
        if tool_scope is None:
            return {
                "status": "error",
                "reason": "invalid_map_scope",
                "detail": f"Map scope '{map_scope}' calling '{called_tool}' is not supported"
            }
        for bn in batches:
            for itm in list_items(conn, project, bn):
                tasks.append(({"batch": bn, "item": itm["name"]}, (called_tool, project, bn, itm["name"], tool_scope)))
    
    else:
        return {
            "status": "error",
            "reason": "invalid_map_scope",
            "detail": f"Invalid map scope: {map_scope}"
        }
    
    total = len(tasks)
    _set_progress(run_id, 0, total, message="准备执行..." if parallel else "正在迭代...")
    
    if parallel and total > 0:
        # 并行模式：使用 ProcessPoolExecutor 避免 os.chdir 冲突
        from concurrent.futures.process import BrokenProcessPool
        
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                # 记录 future 与 context 的映射，以便报错时知道是哪个 item 挂了
                futures = {executor.submit(_parallel_worker_task, ctx, args, run_id): ctx for ctx, args in tasks}
                
                try:
                    for f in concurrent.futures.as_completed(futures):
                        ctx = futures[f]
                        try:
                            _, result = f.result()
                            if result.get("status") == "ok":
                                results.append(result)
                            else:
                                errors.append({**ctx, **result})
                        except BrokenProcessPool:
                            error_msg = "检测到并行子进程意外崩溃（可能是内存溢出 OOM 或被系统杀掉）。正在强制终止所有后续任务..."
                            print(f"[CRITICAL-META] {error_msg}")
                            
                            # 立即尝试取消所有还在排队或运行的任务
                            for fut in futures:
                                if not fut.done():
                                    fut.cancel()
                            
                            # 更新全局进度状态为失败
                            _set_progress(run_id, len(results) + len(errors), total, status="failed", message="检测到进程崩溃，任务已中止")
                            
                            return {
                                "status": "error",
                                "reason": "process_crashed",
                                "detail": "A parallel worker process was terminated abruptly (BrokenProcessPool). This usually indicates resource exhaustion (OOM) or hitting process limits.",
                                "total": total,
                                "success": len(results),
                                "failed": len(errors) + 1,
                                "results": results,
                                "errors": errors + [{"reason": "process_crashed", "detail": "Task pool broke during execution"}]
                            }
                        except Exception as e:
                            import traceback
                            errors.append({
                                "status": "error", 
                                "reason": "future_exception", 
                                "detail": f"{e}\n{traceback.format_exc()}",
                                **ctx
                            })
                        
                        # 更新进度（基于已完成的任务数）
                        finished_count = len(results) + len(errors)
                        _set_progress(run_id, finished_count, total, message=f"并行处理 {finished_count}/{total}")
                except Exception as e:
                    return {
                        "status": "error",
                        "reason": "executor_failed",
                        "detail": f"Parallel execution engine encountered a fatal error: {e}"
                    }
        except Exception as e:
            return {
                "status": "error",
                "reason": "pool_init_failed",
                "detail": f"Failed to initialize process pool: {e}"
            }
    else:
        # 串行模式：复用当前 conn
        for idx, (ctx, args) in enumerate(tasks):
            result = _call_tool(*args, conn=conn, run_id=run_id)
            if result.get("status") == "ok":
                results.append(result)
            else:
                errors.append({**ctx, **result})
            _set_progress(run_id, idx + 1, total, message=f"已处理 {idx+1}/{total}")
    
    return {
        "status": "ok" if not errors else "error",
        "mode": "map",
        "scope": map_scope,
        "total": len(results) + len(errors),
        "success": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def _run_sequence_mode(
    conn: sqlite3.Connection,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    config: Dict[str, Any],
    run_id: str,
) -> Dict[str, Any]:
    """
    执行 Sequence 模式的 Meta Tool。
    """
    tool_sequence = config.get("tool_sequence", [])
    
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    
    for tool_name in tool_sequence:
        # 使用 scope_registry 计算子工具 scope
        tool_type = get_tool_type(tool_name, conn)
        reg_type = tool_type
        if tool_type == "meta":
            meta_code = _get_meta_code_name(tool_name)
            if meta_code == "map":
                reg_type = "meta_map"
            elif meta_code == "sequence":
                reg_type = "meta_sequence"
            elif meta_code == "alt":
                reg_type = "meta_alt"
        
        tool_scope = get_child_scope("sequence", scope, reg_type)
        
        if tool_scope is None:
             # Should be caught by check_meta_tool_available, but fail safe here
             errors.append({
                 "tool": tool_name,
                 "status": "error", 
                 "reason": "invalid_scope_transition",
                 "detail": f"Cannot call {reg_type} '{tool_name}' from sequence scope '{scope}'"
             })
             break
        
        result = _call_tool(
            tool_name, project, batch, item, tool_scope, conn, run_id
        )
        
        if result.get("status") == "ok":
            results.append({"tool": tool_name, **result})
        else:
            errors.append({"tool": tool_name, **result})
            # Sequence 模式：遇到错误就停止
            break
    
    return {
        "status": "ok" if not errors else "error",
        "mode": "sequence",
        "scope": scope,
        "total": len(tool_sequence),
        "completed": len(results),
        "results": results,
        "errors": errors,
    }


def _run_alt_mode(
    conn: sqlite3.Connection,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    config: Dict[str, Any],
    run_id: Optional[str],
) -> Dict[str, Any]:
    """
    执行 Alt 模式：按顺序尝试候选工具，找到第一个可执行的工具并运行。
    """
    candidates = _get_alt_candidates(config)
    if not candidates:
        return {
            "status": "error",
            "reason": "invalid_config",
            "detail": "Alt 模式需要至少一个候选工具"
        }

    attempts: List[Dict[str, Any]] = []

    for tool_name in candidates:
        adj_scope = _adjust_scope_for_tool(tool_name, scope, conn)
        is_ok, err = _check_called_tool(
            tool_name, project, batch, item, adj_scope, conn
        )
        attempts.append({"tool": tool_name, "available": is_ok, **(err or {})})
        if not is_ok:
            continue

        result = _call_tool(
            tool_name, project, batch, item, adj_scope, conn, run_id
        )
        status = result.get("status")
        payload = {
            "status": status,
            "mode": "alt",
            "selected_tool": tool_name,
            "result": result,
            "attempts": attempts,
        }
        if status != "ok":
            payload["reason"] = "selected_tool_failed"
        return payload

    return {
        "status": "error",
        "reason": "all_alternatives_unavailable",
        "mode": "alt",
        "attempts": attempts,
    }


def _call_tool(
    tool_name: str,
    project: str,
    batch: Optional[str],
    item: Optional[str],
    scope: str,
    conn: sqlite3.Connection,
    run_id: Optional[str],
) -> Dict[str, Any]:
    """
    调用工具（single/merge/meta）。
    
    所有工具都有实例名：
    - Single Tool: 实例名在 prj_config 中
    - Merge Tool: 实例名在 prj_config 中
    - Meta Tool: 实例名在 tool_instances 中
    """
    tool_type = get_tool_type(tool_name, conn)
    
    if tool_type is None:
        return {
            "status": "error",
            "reason": "tool_not_found",
            "detail": f"Tool '{tool_name}' not found"
        }
    
    if tool_type == "single":
        result = run_tool(
            project_name=project,
            tool_instance_name=tool_name,
            batch_name=batch if scope != "project" else None,
            item_name=item if scope == "item" else None,
            conn=conn,
            run_id=run_id,
        )
        _ensure_ok(result, tool_name, scope, batch, item)
        return result
    
    elif tool_type == "merge":
        # 将 scope 转换为 merge_mode
        merge_mode_map = {
            "item->batch": "batch_from_items",
            "item->project": "project_from_items",
            "batch->project": "project_from_batches",
        }
        merge_mode = merge_mode_map.get(scope)
        if not merge_mode:
            raise RunFailure(
                {
                    "status": "error",
                    "reason": "invalid_scope",
                    "detail": f"Invalid scope '{scope}' for merge tool",
                }
            )
        
        result = run_merge_tool(
            project_name=project,
            tool_instance_name=tool_name,
            batch_name=batch if scope == "item->batch" else None,
            merge_mode=merge_mode,
            conn=conn,
        )
        _ensure_ok(result, tool_name, scope, batch, item)
        return result
    
    elif tool_type == "meta":
        result = run_meta_tool(
            project_name=project,
            tool_instance_name=tool_name,
            batch_name=batch,
            item_name=item,
            scope=scope,
            conn=conn,
            run_id=run_id,
        )
        _ensure_ok(result, tool_name, scope, batch, item)
        return result
    
    raise RunFailure(
        {
            "status": "error",
            "reason": "tool_not_found",
            "detail": f"Tool '{tool_name}' not found in any registry",
        }
    )
