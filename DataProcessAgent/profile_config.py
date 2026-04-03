"""
profile_config.py

Profile 配置管理：
- 读取和保存当前使用的 profile
- 默认 profile: default-profile
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# 始终使用项目根目录的绝对路径
# Path(__file__).parent 得到 profile_config.py 所在的目录
ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).resolve()
PROJECT_CONFIG_PATH = ROOT_DIR / "config" / "project_config.json"


def get_current_profile() -> str:
    """
    获取当前使用的 profile。
    
    返回：
        profile 名称，默认为 "default-profile"
    """
    if not PROJECT_CONFIG_PATH.exists():
        return "default-profile"
    
    try:
        with open(PROJECT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("profile", "default-profile")
    except Exception:
        return "default-profile"


def set_current_profile(profile: str) -> None:
    """
    设置当前使用的 profile。
    
    参数：
        profile: profile 名称
    """
    PROJECT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    data = {}
    if PROJECT_CONFIG_PATH.exists():
        try:
            with open(PROJECT_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    
    data["profile"] = profile
    
    with open(PROJECT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_profiles_dir() -> Path:
    """获取所有 profile 所在的根目录"""
    return ROOT_DIR / "tool-instances"


def get_tool_instances_dir(profile: Optional[str] = None) -> Path:
    """
    获取工具实例目录路径。
    
    参数：
        profile: profile 名称，如果为 None 则使用当前 profile
    
    返回：
        工具实例目录路径
    """
    if profile is None:
        profile = get_current_profile()
    return ROOT_DIR / "tool-instances" / profile


def get_tool_codes_dir(tool_type: str) -> Path:
    """
    获取工具代码目录路径。
    
    参数：
        tool_type: 工具类型 ("single", "merge", "meta")
    
    返回：
        工具代码目录路径
    """
    return ROOT_DIR / "tools" / tool_type


