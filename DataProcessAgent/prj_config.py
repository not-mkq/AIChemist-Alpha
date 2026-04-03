"""
prj_config.py

【已简化】项目不再有独立配置，直接使用全局工具实例配置。

保留此文件仅用于向后兼容，实际功能已迁移到 tool_registry.py。
"""

from __future__ import annotations

from typing import Dict, Any, Optional

from tool_registry import get_tool_config_from_file


def get_project_tool_config(
    project_name: str,
    tool_name: str,
) -> Optional[Dict[str, Any]]:
    """
    获取工具配置（项目直接使用全局工具实例配置）。
    
    参数：
        project_name: 项目名（保留参数以保持兼容性，但不再使用）
        tool_name: 工具实例名
    
    返回：
        配置字典，如果不存在返回 None
    """
    return get_tool_config_from_file(tool_name)


# =========================
# 向后兼容：保留旧函数名，但不再执行实际操作
# =========================

def init_project_tool_configs(
    project_name: str,
    conn: Optional[Any] = None,
    force: bool = False,
) -> None:
    """
    【已废弃】项目不再有独立配置，直接使用全局工具实例配置。
    
    保留此函数以保持向后兼容，但不执行任何操作。
    """
    print(f"[PRJ-CONFIG] Note: Project '{project_name}' now uses global tool instance configs directly")
    print("[PRJ-CONFIG] No project-specific configuration needed")


def update_project_tool_config(
    project_name: str,
    tool_name: str,
    new_config: Dict[str, Any],
    conn: Optional[Any] = None,
) -> None:
    """
    【已废弃】项目不再有独立配置。
    
    保留此函数以保持向后兼容，但不执行任何操作。
    如需修改工具配置，请直接编辑 tools/, merge-tools/, meta-tools/ 下的配置文件。
    """
    print(f"[PRJ-CONFIG] Note: Project '{project_name}' now uses global tool instance configs")
    print(f"[PRJ-CONFIG] To modify tool '{tool_name}', edit the config file directly")


def load_default_tool_configs() -> Dict[str, Dict[str, Any]]:
    """
    【已废弃】项目不再有独立配置。
    
    保留此函数以保持向后兼容。
    """
    from tool_registry import get_tool_config_from_file, list_all_tools
    
    all_configs: Dict[str, Dict[str, Any]] = {}
    tools = list_all_tools()
    all_instance_names = tools["single"] + tools["merge"] + tools["meta"]
    
    for instance_name in all_instance_names:
        config = get_tool_config_from_file(instance_name)
        if config:
            all_configs[instance_name] = config
    
    return all_configs
