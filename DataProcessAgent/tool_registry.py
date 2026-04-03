"""
tool_registry.py

工具实例注册管理：
- 将所有工具实例注册到 tool_instances 数据库表
- 提供注册和查询接口
- 从 template.config.json 文件加载工具代码元数据到 tool_codes 表
"""

from __future__ import annotations

import json
import sqlite3
import threading
import copy
from pathlib import Path
from typing import Dict, Any, Optional, List, Iterable

import importlib.util
from db import get_connection, init_db
from param_value_utils import extract_wrapped_value
from tool_runtime import TOOLS_REGISTRY
from merge_runtime import MERGE_TOOLS_REGISTRY
from meta_runtime import META_TOOLS_REGISTRY, load_meta_tools
from labeler import CONFIG_PATH as LABEL_CONFIG_PATH
from profile_config import get_tool_instances_dir, get_tool_codes_dir, ROOT_DIR

# Cache for tool configurations to avoid repeated file I/O
_TOOL_CONFIG_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

def clear_config_cache() -> None:
    """清理工具配置缓存。"""
    with _CACHE_LOCK:
        _TOOL_CONFIG_CACHE.clear()

def _load_all_tool_modules() -> None:
    """
    加载所有工具模块（仅在需要时调用，如 /reload-all 接口）。
    不再在启动时自动调用。
    """
    # 清理注册表，避免重复注册导致报错
    TOOLS_REGISTRY.clear()
    MERGE_TOOLS_REGISTRY.clear()
    META_TOOLS_REGISTRY.clear()
    
    # 清理配置缓存
    clear_config_cache()

    # 加载 single tools 代码
    single_dir = get_tool_codes_dir("single")
    if single_dir.exists():
        for py_file in single_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"tools.{py_file.stem}", py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error loading single tool {py_file}: {e}")

    # 加载 merge tools 代码
    merge_dir = get_tool_codes_dir("merge")
    if merge_dir.exists():
        for py_file in merge_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"merge_tools.{py_file.stem}", py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error loading merge tool {py_file}: {e}")
    
    # 加载 meta tools 代码（map_tool.py, sequence_tool.py, alt_tool.py）
    meta_dir = get_tool_codes_dir("meta")
    if meta_dir.exists():
        for py_file in meta_dir.glob("*_tool.py"):
            try:
                spec = importlib.util.spec_from_file_location(f"meta_tools.{py_file.stem}", py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error loading meta tool {py_file}: {e}")
    
    # 加载 meta tools 配置
    load_meta_tools()


def _ensure_tool_loaded(tool_instance_name: str) -> None:
    """
    按需加载工具：当需要使用某个工具时，确保其代码已注册。
    
    参数：
        tool_instance_name: 工具实例名（不包含路径）
    """
    # 获取工具类型和配置
    tool_type = get_tool_type_from_file(tool_instance_name)
    if not tool_type:
        return
    
    config = get_tool_config_from_file(tool_instance_name)
    if not config:
        return
    
    code_name = config.get("code_name", tool_instance_name)
    if not code_name:
        return
    
    # 检查工具代码是否已注册
    if tool_type == "single":
        if code_name in TOOLS_REGISTRY:
            return
        
        tool_file = get_tool_codes_dir("single") / f"{code_name}.py"
        if tool_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(f"tools.{code_name}", tool_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error on-demand loading {tool_file}: {e}")
    
    elif tool_type == "merge":
        if code_name in MERGE_TOOLS_REGISTRY:
            return
        
        merge_file = get_tool_codes_dir("merge") / f"{code_name}.py"
        if merge_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(f"merge_tools.{code_name}", merge_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error on-demand loading {merge_file}: {e}")
    
    elif tool_type == "meta":
        # Meta tools 逻辑在模块导入时已加载，确保配置加载即可
        load_meta_tools()


def load_tool_code_metadata(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    从 template.config.json 文件扫描工具代码元数据（不再写入数据库）。
    
    流程：
    1. 扫描 tools/, merge-tools/, meta-tools/ 目录下的 *.template.config.json 文件
    2. 统计每个模板文件的 code_name, tool_type 等信息
    
    返回：
        加载统计信息
    """
    stats = {
        "single": 0,
        "merge": 0,
        "meta": 0,
        "total": 0
    }
    
    # 扫描所有 template.config.json 文件
    template_dirs = [
        get_tool_codes_dir("single"),
        get_tool_codes_dir("merge"),
        get_tool_codes_dir("meta")
    ]
    
    for template_dir in template_dirs:
        if not template_dir.exists():
            continue
        
        for template_file in template_dir.glob("*.template.config.json"):
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    template_data = json.load(f)

                if not isinstance(template_data, dict) or not hasattr(template_data, "get"):
                    print(f"[TOOL-REGISTRY] Skip {template_file}: template is not an object")
                    continue
                
                code_name = template_data.get("code_name")
                tool_type = template_data.get("tool_type")
                
                if not code_name or not tool_type:
                    print(f"[TOOL-REGISTRY] Warning: {template_file} missing code_name or tool_type")
                    continue
                
                if tool_type == "single":
                    stats["single"] += 1
                elif tool_type == "merge":
                    stats["merge"] += 1
                elif tool_type == "meta":
                    stats["meta"] += 1
                stats["total"] += 1
                
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error loading {template_file}: {e}")
    
    print(f"[TOOL-REGISTRY] Loaded {stats['total']} tool codes: "
          f"{stats['single']} single, {stats['merge']} merge")
    
    return stats


def get_tool_code_template(code_name: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """
    从文件系统读取工具代码的模板信息（不再使用数据库）。
    
    参数：
        code_name: 工具代码名
        conn: 数据库连接（保留参数以保持兼容性，但不再使用）
    
    返回：
        模板数据字典，包含 code_name, tool_type, comment, params 等信息
    """
    # 扫描所有工具类型目录，查找对应的模板文件
    for tool_type in ["single", "merge", "meta"]:
        template_dir = get_tool_codes_dir(tool_type)
        if not template_dir.exists():
            continue
        
        template_file = template_dir / f"{code_name}.template.config.json"
        if template_file.exists():
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error reading template file {template_file}: {e}")
                return None
    
    return None


def _collect_output_labels_from_config(cfg: Dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    raw = cfg.get("output_file_label")
    val, _, _, has_value = extract_wrapped_value(raw)
    if not has_value:
        return labels
    if isinstance(val, str) and val.strip():
        labels.add(val.strip())
    elif isinstance(val, list):
        labels.update([str(v).strip() for v in val if str(v).strip()])
    elif isinstance(val, dict):
        labels.update([str(v).strip() for v in val.values() if str(v).strip()])
    return labels


def _iter_instance_configs_for_labels() -> Iterable[Dict[str, Any]]:
    """
    遍历所有可用的实例配置（包含 tool-instances 以及兼容的 tools/ 目录配置）。
    """
    visited_files: set[Path] = set()

    def scan_dir(base: Path) -> Iterable[Dict[str, Any]]:
        if not base.exists():
            return []
        results: List[Dict[str, Any]] = []
        for config_file in base.rglob("*.config.json"):
            if config_file.name.endswith(".template.config.json"):
                continue
            if config_file in visited_files:
                continue
            visited_files.add(config_file)
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for cfg in data.values():
                        if isinstance(cfg, dict):
                            results.append(cfg)
            except Exception as e:
                print(f"[TOOL-REGISTRY] Error reading {config_file}: {e}")
        return results

    # 当前 profile 下的 tool-instances
    instances_dir = get_tool_instances_dir()
    for cfg in scan_dir(instances_dir):
        yield cfg

    # 兼容：直接放在 tools/ 等目录下的配置（主要用于测试/临时脚本）
    for alt_dir in [Path("tools"), Path("merge-tools"), Path("meta-tools")]:
        for cfg in scan_dir(alt_dir):
            yield cfg


def _ensure_output_labels_exist(
    single_configs: Dict[str, Dict[str, Any]], merge_configs: Dict[str, Dict[str, Any]]
) -> None:
    """
    确保工具配置中的 output_file_label 都在 label-config.json 中。
    如果缺失，则添加一条无匹配的正则规则 "(?!)"。
    """
    wanted: set[str] = set()
    for cfg in single_configs.values():
        wanted.update(_collect_output_labels_from_config(cfg))
    for cfg in merge_configs.values():
        wanted.update(_collect_output_labels_from_config(cfg))

    if not wanted:
        return

    config_path = LABEL_CONFIG_PATH
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"regex": {}, "wildcard": {}}
    else:
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"regex": {}, "wildcard": {}}

    regex_block = data.get("regex") or {}
    wildcard_block = data.get("wildcard") or {}

    updated = False
    for label in wanted:
        if label in regex_block or label in wildcard_block:
            continue
        regex_block[label] = "(?!)"
        updated = True

    if updated:
        data["regex"] = regex_block
        data["wildcard"] = wildcard_block
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[TOOL-REGISTRY] Added missing labels to {config_path}: {sorted(wanted)}")


def sync_all_output_labels_to_label_config() -> Dict[str, Any]:
    """
    收集所有工具实例的 output_file_label，并更新 label-config.json。
    
    返回：
        {
            "added": [...],  # 新添加的 label 列表
            "existing": [...],  # 已存在的 label 列表
            "total": 0  # 总共收集到的 label 数量
        }
    """
    wanted: set[str] = set()
    
    # 收集所有工具实例的 output_file_label（支持 tool-instances 以及兼容路径）
    for cfg in _iter_instance_configs_for_labels():
        wanted.update(_collect_output_labels_from_config(cfg))
    
    if not wanted:
        return {"added": [], "existing": [], "total": 0}
    
    # 读取现有的 label-config.json
    config_path = LABEL_CONFIG_PATH
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"regex": {}, "wildcard": {}}
    else:
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"regex": {}, "wildcard": {}}
    
    regex_block = data.get("regex") or {}
    wildcard_block = data.get("wildcard") or {}
    
    added: list[str] = []
    existing: list[str] = []
    
    for label in sorted(wanted):
        if label in regex_block or label in wildcard_block:
            existing.append(label)
        else:
            regex_block[label] = "(?!)"
            added.append(label)
    
    if added:
        data["regex"] = regex_block
        data["wildcard"] = wildcard_block
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[TOOL-REGISTRY] Added {len(added)} new labels to {config_path}: {added}")
    
    return {
        "added": added,
        "existing": existing,
        "total": len(wanted)
    }

def register_all_tools(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    注册所有工具实例到 tool_instances 表。

    流程：
    1. 清空 tool_instances 表
    2. 加载所有工具代码模块（包括 meta-tools 中的 map/sequence）
    3. 注册 Single Tools（从配置文件）
    4. 注册 Merge Tools（从配置文件）
    5. 注册 Meta Tools（从 meta-tools/*.config.json）
    
    返回：
        注册统计信息
    """
    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True
    
    try:
        # 确保注册表清空并重新加载所有模块
        _load_all_tool_modules()

        # 确保表存在
        init_db(conn)
        
        cur = conn.cursor()
        
        # 1. 清空表
        cur.execute("DELETE FROM tool_instances;")
        
        stats = {
            "single": 0,
            "merge": 0,
            "meta": 0,
            "total": 0
        }
        
        # 2. 注册所有工具实例（从当前 profile 的配置文件）
        single_configs = {}  # {instance_path: config}
        merge_configs = {}
        meta_configs = {}  # {instance_path: config}
        
        # 获取当前 profile 的工具实例目录
        instances_dir = get_tool_instances_dir()
        
        if instances_dir.exists():
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
                    # 移除文件名，只保留目录路径
                    if rel_path.parent != Path("."):
                        dir_path = str(rel_path.parent).replace("\\", "/")
                    else:
                        dir_path = ""
                    
                    for tool_instance_name, config in data.items():
                        code_name = config.get("code_name", tool_instance_name)
                        
                        # 构建完整路径标识
                        if dir_path:
                            instance_path = f"{dir_path}/{tool_instance_name}"
                        else:
                            instance_path = tool_instance_name
                        
                        # 排除 map 和 sequence（它们是 meta tool 的代码）
                        if code_name in ["map", "sequence"]:
                            continue
                        
                        # 根据 code_name 判断类型
                        if code_name in {"map", "sequence", "alt"}:
                            meta_configs[instance_path] = config
                        elif code_name in MERGE_TOOLS_REGISTRY:
                            merge_configs[instance_path] = config
                        elif code_name in TOOLS_REGISTRY:
                            single_configs[instance_path] = config
                except Exception as e:
                    print(f"[TOOL-REGISTRY] Error loading {config_file}: {e}")
        
        # 注意：tool_codes 表应该只由 load_tool_code_metadata() 管理
        # register_all_tools() 只负责注册 tool_instances，不操作 tool_codes
        # 如果 tool_codes 表为空或 template_json 为 None，用户需要先调用 POST /load-metadata 加载模板数据
        
        # 在注册实例前，确保 output_file_label 出现在 label-config.json 中（若缺失则补一条无匹配规则）
        _ensure_output_labels_exist(single_configs, merge_configs)

        # 注册 Single Tools 实例
        for tool_instance_path, config in single_configs.items():
            # tool_instance_path 可能是 "xxx" 或 "收藏夹/xxx"
            instance_name = tool_instance_path.split("/")[-1]
            code_name = config.get("code_name", instance_name)
            instance_comment = config.get("comment")  # 从配置文件读取实例级别的注释
            stats["single"] += 1

            # 校验模板存在
            cur.execute(
                "SELECT 1 FROM tool_codes WHERE code_name = ?;",
                (code_name,)
            )
            if not cur.fetchone():
                raise RuntimeError(f"模板缺失: single 工具代码 '{code_name}' 未在 tool_codes 中注册（请先加载模板）")

            # 使用路径标识作为 instance_name
            cur.execute(
                """
                INSERT INTO tool_instances (instance_name, tool_type, code_name, config_json, comment)
                VALUES (?, ?, ?, ?, ?);
                """,
                (tool_instance_path, "single", code_name, json.dumps(config, ensure_ascii=False), instance_comment)
            )
        
        # 注册 Merge Tools 实例
        for tool_instance_path, config in merge_configs.items():
            instance_name = tool_instance_path.split("/")[-1]
            code_name = config.get("code_name", instance_name)
            instance_comment = config.get("comment")  # 从配置文件读取实例级别的注释
            stats["merge"] += 1

            # 校验模板存在
            cur.execute(
                "SELECT 1 FROM tool_codes WHERE code_name = ?;",
                (code_name,)
            )
            if not cur.fetchone():
                raise RuntimeError(f"模板缺失: merge 工具代码 '{code_name}' 未在 tool_codes 中注册（请先加载模板）")

            # 使用路径标识作为 instance_name
            cur.execute(
                """
                INSERT INTO tool_instances (instance_name, tool_type, code_name, config_json, comment)
                VALUES (?, ?, ?, ?, ?);
                """,
                (tool_instance_path, "merge", code_name, json.dumps(config, ensure_ascii=False), instance_comment)
            )
        
        # 注册 Meta Tools 实例
        for tool_instance_path, config in meta_configs.items():
            instance_name = tool_instance_path.split("/")[-1]
            tool_type = "meta"
            code_name = config.get("code_name")
            if code_name not in {"map", "sequence", "alt"}:
                raise RuntimeError(
                    f"无效的 meta 代码: '{code_name}'，meta 工具 '{tool_instance_path}' 仅支持 code_name=map/sequence/alt"
                )
            instance_comment = config.get("comment")  # 从配置文件读取实例级别的注释
            stats["meta"] += 1

            # 校验模板存在（map/sequence/alt 也需要模板）
            cur.execute(
                "SELECT 1 FROM tool_codes WHERE code_name = ?;",
                (code_name,),
            )
            if not cur.fetchone():
                raise RuntimeError(
                    f"模板缺失: meta 工具代码 '{code_name}' 未在 tool_codes 中注册（请先加载模板）"
                )
            
            # 使用路径标识作为 instance_name
            cur.execute(
                """
                INSERT INTO tool_instances (instance_name, tool_type, code_name, config_json, comment)
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    tool_instance_path,
                    tool_type,
                    code_name,
                    json.dumps(config, ensure_ascii=False),
                    instance_comment,
                )
            )
        
        conn.commit()
        stats["total"] = stats["single"] + stats["merge"] + stats["meta"]
        
        print(f"[TOOL-REGISTRY] Registered {stats['total']} tools: "
              f"{stats['single']} single, {stats['merge']} merge, {stats['meta']} meta")
        
        return stats
    
    finally:
        if owns_conn:
            conn.close()


def get_tool_type_from_db(tool_instance_name: str, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """
    【已废弃】从 tool_instances 表查询工具类型。
    
    工具配置现在完全从文件系统读取，此函数已废弃。
    请使用 get_tool_type_from_file() 代替。
    """
    # 回退到文件系统读取
    return get_tool_type_from_file(tool_instance_name)


def get_tool_config_from_db(tool_instance_name: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """
    【已废弃】从 tool_instances 表查询工具配置。
    
    工具配置现在完全从文件系统读取，此函数已废弃。
    请使用 get_tool_config_from_file() 代替。
    """
    # 回退到文件系统读取
    return get_tool_config_from_file(tool_instance_name)


def _load_instance_from_file(config_file: Path, tool_instance_name: str) -> Optional[Dict[str, Any]]:
    """从指定文件中加载实例配置。"""
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[DEBUG] _load_instance_from_file: file={config_file}, keys={list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
        if isinstance(data, dict) and tool_instance_name in data:
            return data[tool_instance_name]
    except Exception as e:
        print(f"[TOOL-REGISTRY] Error reading {config_file}: {e}")
    return None


def _infer_tool_type_from_path(config_file: Path) -> Optional[str]:
    for parent in config_file.parents:
        name = parent.name
        if name == "tools":
            return "single"
        if name == "merge-tools":
            return "merge"
        if name == "meta-tools":
            return "meta"
    return None


def _search_additional_config_dirs(tool_instance_name: str) -> Optional[Dict[str, Any]]:
    # 兼容：tools/、merge-tools/、meta-tools/ 目录
    for base in [ROOT_DIR / "tools", ROOT_DIR / "merge-tools", ROOT_DIR / "meta-tools"]:
        if not base.exists():
            continue
        pattern = f"{tool_instance_name}.config.json"
        for config_file in base.rglob(pattern):
            if config_file.name.endswith(".template.config.json"):
                continue
            cfg = _load_instance_from_file(config_file, tool_instance_name)
            if cfg:
                inferred_type = cfg.get("tool_type") or _infer_tool_type_from_path(config_file)
                if inferred_type:
                    cfg.setdefault("tool_type", inferred_type)
                return cfg
    return None


def get_tool_config_from_file(tool_instance_name: str) -> Optional[Dict[str, Any]]:
    """
    从配置文件读取工具实例配置（在当前profile的所有目录中搜索）。
    
    参数：
        tool_instance_name: 工具实例名（不包含路径）
    
    返回：
        配置字典，如果不存在返回 None
    """
    # 检查缓存
    with _CACHE_LOCK:
        if tool_instance_name in _TOOL_CONFIG_CACHE:
            return copy.deepcopy(_TOOL_CONFIG_CACHE[tool_instance_name])

    # 获取当前 profile 的工具实例目录
    def _search_profile_dir(instances_dir: Path) -> Optional[Dict[str, Any]]:
        if not instances_dir.exists():
            return None
        
        pattern = f"{tool_instance_name}.config.json"
        for config_file in instances_dir.rglob(pattern):
            if config_file.name.endswith(".template.config.json"):
                continue
            cfg = _load_instance_from_file(config_file, tool_instance_name)
            if cfg:
                return cfg
        return None

    instances_dir = get_tool_instances_dir()
    print(f"[DEBUG] CWD: {Path.cwd()}")
    print(f"[DEBUG] get_tool_config_from_file: searching for {tool_instance_name} in {instances_dir.absolute()} (exists={instances_dir.exists()})")
    cfg = _search_profile_dir(instances_dir)
    
    if not cfg:
        # 兼容：尝试其他 profile 目录（例如 default-profile）
        profiles_root = ROOT_DIR / "tool-instances"
        if profiles_root.exists():
            for profile_dir in profiles_root.iterdir():
                if not profile_dir.is_dir():
                    continue
                if profile_dir == instances_dir:
                    continue
                cfg = _search_profile_dir(profile_dir)
                if cfg:
                    break
    
    if not cfg:
        # 兼容：tools/、merge-tools/、meta-tools/ 目录
        cfg = _search_additional_config_dirs(tool_instance_name)
    
    # 写入缓存（即使是 None 也缓存，避免重复查找不存在的文件）
    # 但 None 不缓存可能更好，以便后续创建？不，按需清理即可。
    # 这里我们缓存结果。
    if cfg:
        with _CACHE_LOCK:
            _TOOL_CONFIG_CACHE[tool_instance_name] = cfg
            
    return copy.deepcopy(cfg) if cfg else None


def _scan_tool_configs() -> Dict[str, List[str]]:
    """
    扫描配置文件，返回所有工具实例名（不注册到数据库，去重）。
    
    返回：
        {
            "single": [...],  # 实例名列表，如 ["xxx", "yyy"]
            "merge": [...],
            "meta": [...]
        }
    """
    result = {
        "single": set(),
        "merge": set(),
        "meta": set()
    }
    
    def classify(instance_name: str, cfg: Dict[str, Any]) -> Optional[str]:
        # 严格根据 tool_type 返回
        explicit = cfg.get("tool_type")
        if explicit in {"single", "merge", "meta"}:
            return explicit
        return None

    # 获取当前 profile 的工具实例目录
    instances_dir = get_tool_instances_dir()
    
    if not instances_dir.exists():
        return {k: list(v) for k, v in result.items()}
    
    # 扫描所有配置文件（包括根目录和所有子目录）
    for config_file in instances_dir.rglob("*.config.json"):
        if config_file.name.endswith(".template.config.json"):
            continue
        
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if not isinstance(data, dict):
                continue
            
            for tool_instance_name, config in data.items():
                cls = classify(tool_instance_name, config)
                if cls:
                    result[cls].add(tool_instance_name)
        except Exception as e:
            print(f"[TOOL-REGISTRY] Error scanning {config_file}: {e}")
    
    return {k: sorted(list(v)) for k, v in result.items()}


def list_tools_by_directory(directory: str = "") -> Dict[str, List[str]]:
    """
    列出指定目录下的工具实例名。
    
    参数：
        directory: 目录名（""表示根目录，如 "收藏夹" 表示子目录）
    
    返回：
        {
            "single": [...],
            "merge": [...],
            "meta": [...]
        }
    """
    result = {
        "single": [],
        "merge": [],
        "meta": []
    }
    
    instances_dir = get_tool_instances_dir()
    
    if not instances_dir.exists():
        return result
    
    # 确定要扫描的目录
    if directory:
        target_dir = instances_dir / directory
        if not target_dir.exists() or not target_dir.is_dir():
            return result
        config_files = list(target_dir.glob("*.config.json"))
    else:
        # 根目录
        config_files = list(instances_dir.glob("*.config.json"))
    
    def classify(instance_name: str, cfg: Dict[str, Any]) -> Optional[str]:
        # 严格根据 tool_type 返回
        explicit = cfg.get("tool_type")
        if explicit in {"single", "merge", "meta"}:
            return explicit
        return None

    for config_file in config_files:
        if config_file.name.endswith(".template.config.json"):
            continue
        
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if not isinstance(data, dict):
                continue
            
            for tool_instance_name, config in data.items():
                cls = classify(tool_instance_name, config)
                if cls:
                    result[cls].append(tool_instance_name)
        except Exception as e:
            print(f"[TOOL-REGISTRY] Error scanning {config_file}: {e}")
    
    # 排序
    for key in result:
        result[key] = sorted(result[key])
    
    return result


def list_directories() -> List[str]:
    """
    列出当前profile下的所有一级子目录。
    
    返回：
        目录名列表，如 ["收藏夹", "常用工具"]
    """
    instances_dir = get_tool_instances_dir()
    
    if not instances_dir.exists():
        return []
    
    directories = []
    for item in instances_dir.iterdir():
        if item.is_dir():
            directories.append(item.name)
    
    return sorted(directories)


def list_profiles() -> List[str]:
    """
    列出所有可用的profile。
    
    返回：
        profile名列表，如 ["default-profile", "custom-profile"]
    """
    profiles_dir = ROOT_DIR / "tool-instances"
    if not profiles_dir.exists():
        return []
    
    profiles = []
    for item in profiles_dir.iterdir():
        if item.is_dir():
            profiles.append(item.name)
    
    return sorted(profiles)


def get_tool_type_from_file(tool_instance_name: str) -> Optional[str]:
    """
    从配置文件读取工具类型。
    """
    config = get_tool_config_from_file(tool_instance_name)
    if not config:
        return None
    
    explicit_type = config.get("tool_type")
    if explicit_type in {"single", "merge", "meta"}:
        return explicit_type
    
    return None


def check_tool_instance_exists(tool_instance_name: str) -> Optional[str]:
    """
    检查工具实例是否已存在（在当前profile的所有目录中）。
    
    参数：
        tool_instance_name: 工具实例名
    
    返回：
        所属目录名（""表示根目录），如果不存在返回 None
    """
    instances_dir = get_tool_instances_dir()
    
    if not instances_dir.exists():
        return None
    
    pattern = f"{tool_instance_name}.config.json"
    for config_file in instances_dir.rglob(pattern):
        if config_file.name.endswith(".template.config.json"):
            continue
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and tool_instance_name in data:
                # 返回相对于 instances_dir 的路径
                rel_path = config_file.parent.relative_to(instances_dir)
                if str(rel_path) == ".":
                    return ""
                return str(rel_path)
        except Exception:
            pass
    
    return None


def save_tool_instance_to_file(tool_instance_name: str, tool_type: str, config: Dict[str, Any], comment: Optional[str] = None, directory: str = "") -> Path:
    """
    保存工具实例配置到文件系统。
    
    参数：
        tool_instance_name: 工具实例名（不包含路径）
        tool_type: 工具类型 ("single", "merge", "meta")
        config: 配置字典
        comment: 注释（可选）
        directory: 保存到的目录（""表示根目录，如 "收藏夹" 表示子目录）
    
    返回：
        保存的配置文件路径
    
    抛出：
        RuntimeError: 如果同一profile下已存在同名工具实例
    """
    instances_dir = get_tool_instances_dir()
    
    # 检查是否已存在（在不同目录）
    existing_dir = check_tool_instance_exists(tool_instance_name)
    if existing_dir is not None and existing_dir != directory:
        raise RuntimeError(f"工具实例 '{tool_instance_name}' 已存在于目录 '{existing_dir if existing_dir else '根目录'}'，同一profile下不能有重名工具实例")
    
    # 构建文件路径
    if directory:
        config_dir = instances_dir / directory
    else:
        config_dir = instances_dir
    
    # 确保目录存在
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # 配置文件路径
    config_file = config_dir / f"{tool_instance_name}.config.json"
    
    # 再次确保文件所在的父目录存在（防止 tool_instance_name 中包含子路径）
    config_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 读取现有配置（如果存在）
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    
    # 如果 comment 为 None，尝试保留原有注释
    if comment is None and tool_instance_name in data:
        old_config = data[tool_instance_name]
        if isinstance(old_config, dict):
            comment = old_config.get("comment")
    
    # 准备配置数据
    config_to_save = config.copy()
    if tool_type:
        config_to_save.setdefault("tool_type", tool_type)
    if comment:
        config_to_save["comment"] = comment
    
    # 更新配置
    data[tool_instance_name] = config_to_save
    
    # 保存文件
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 修复：修改文件后清理缓存
    clear_config_cache()
    
    return config_file


import shutil
import logging

logger = logging.getLogger(__name__)

def delete_tool_instance_from_file(tool_instance_name: str) -> bool:
    """
    从文件系统删除工具实例配置（在当前profile的所有目录中搜索）。
    采用软删除逻辑：将原文件备份到项目根目录下的 .backup 文件夹。
    
    参数：
        tool_instance_name: 工具实例名（不包含路径）
    
    返回：
        是否成功删除
    """
    instances_dir = get_tool_instances_dir()
    # 确定备份目录 (项目根目录下的 .backup)
    backup_dir = ROOT_DIR / ".backup"
    if not backup_dir.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
    
    if not instances_dir.exists():
        return False
    
    pattern = f"{tool_instance_name}.config.json"
    deleted = False
    print(f"Searching for {pattern} in {instances_dir}")
    for config_file in list(instances_dir.rglob(pattern)):
        print(f"Found match: {config_file}")
        if config_file.name.endswith(".template.config.json"):
            continue
        try:
            # 始终先全量备份原文件到 .backup
            backup_path = backup_dir / config_file.name
            shutil.copy2(config_file, backup_path)
            
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, dict) and tool_instance_name in data:
                del data[tool_instance_name]
                if not data:
                    # 如果文件中没有其他实例了，直接从原位删除（因为已经备份了）
                    config_file.unlink()
                    # 递归清理空的父目录（直到实例根目录）
                    parent = config_file.parent
                    while parent != instances_dir and parent.is_dir():
                        try:
                            if not any(parent.iterdir()):
                                parent.rmdir()
                                parent = parent.parent
                            else:
                                break
                        except OSError:
                            break
                else:
                    # 如果还有其他实例，更新原文件
                    with open(config_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                deleted = True
        except Exception as e:
            logger.error(f"删除并备份工具实例 {tool_instance_name} 失败: {e}")
            pass
    
    # 修复：删除后清理缓存
    if deleted:
        clear_config_cache()
        
    return deleted


def get_tool_code_comment(code_name: str, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """
    从文件系统读取工具代码的注释（不再使用数据库）。
    
    参数：
        code_name: 工具代码名
        conn: 数据库连接（保留参数以保持兼容性，但不再使用）
    
    返回：
        注释字符串
    """
    template = get_tool_code_template(code_name)
    if template:
        return template.get("comment", "")
    return None


def get_tool_instance_comment(instance_name: str, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """
    从文件系统读取工具实例的注释（不再使用数据库）。
    
    参数：
        instance_name: 工具实例名
        conn: 数据库连接（保留参数以保持兼容性，但不再使用）
    
    返回：
        注释字符串
    """
    config = get_tool_config_from_file(instance_name)
    if config:
        return config.get("comment", "")
    return None


def list_all_tools(conn: Optional[sqlite3.Connection] = None) -> Dict[str, list]:
    """
    列出所有工具实例（从文件系统扫描，不再使用数据库）。
    
    返回：
        {
            "single": [...],
            "merge": [...],
            "meta": [...]
        }
    """
    # 不再从数据库读取，直接从文件系统扫描
    return _scan_tool_configs()
