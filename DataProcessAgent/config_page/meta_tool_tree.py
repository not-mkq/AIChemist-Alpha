#!/usr/bin/env python3
"""
meta_tool_tree.py

Meta工具树形配置组件：
- 递归解析meta工具，提取所有被引用的工具
- 检测循环引用
- 提供树形UI展示和编辑
"""

from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolNode:
    """工具节点"""
    name: str  # 工具实例名
    tool_type: str  # "single", "merge", "meta"
    path: str  # 完整路径，如 "meta_tool → sub_meta_tool → my_tool"
    config: Dict[str, Any]  # 工具配置
    children: List['ToolNode']  # 子工具节点
    parent: Optional['ToolNode'] = None  # 父节点
    comment: Optional[str] = None  # 工具注释


def parse_meta_tool_tree(
    tool_name: str,
    tool_type: str,
    config: Dict[str, Any],
    get_tool_instance_func,
    visited: Optional[Set[str]] = None,
    path: Optional[List[str]] = None,
    max_depth: int = 10,
    comment: Optional[str] = None  # 传入当前工具的注释
) -> Tuple[ToolNode, Optional[str]]:
    """
    递归解析meta工具，构建工具树。
    ...
    """
    if visited is None:
        visited = set()
    if path is None:
        path = []
    
    # 检测循环引用
    if tool_name in visited:
        cycle_path = " → ".join(path + [tool_name])
        return None, f"检测到循环引用: {cycle_path}"
    
    # 检测递归深度
    if len(path) >= max_depth:
        return None, f"递归深度超过限制 ({max_depth} 层): {' → '.join(path + [tool_name])}"
    
    # 添加到已访问集合和路径
    visited.add(tool_name)
    path.append(tool_name)
    
    # 构建路径字符串
    path_str = " → ".join(path)
    
    # 创建当前节点
    node = ToolNode(
        name=tool_name,
        tool_type=tool_type,
        path=path_str,
        config=config.copy(),
        children=[],
        parent=None,
        comment=comment
    )
    
    # 如果是meta工具，递归解析子工具
    if tool_type == "meta":
        mode = config.get("code_name", "map")
        
        if mode == "map":
            # Map模式：只有一个子工具
            child_tool_name = config.get("tool")
            if child_tool_name:
                try:
                    child_data = get_tool_instance_func(child_tool_name)
                    if child_data and child_data.get("status") == "ok":
                        child_tool_type = child_data.get("tool_type")
                        child_config = child_data.get("config", {})
                        child_comment = child_data.get("comment")
                        
                        child_node, error = parse_meta_tool_tree(
                            child_tool_name,
                            child_tool_type,
                            child_config,
                            get_tool_instance_func,
                            visited.copy(),  # 使用副本，允许不同分支访问相同工具
                            path.copy(),
                            max_depth,
                            comment=child_comment
                        )
                        
                        if error:
                            return None, error
                        
                        if child_node:
                            child_node.parent = node
                            node.children.append(child_node)
                    else:
                        # ... (同上) ...
                        pass
                except Exception:
                    # ... (同上) ...
                    pass
        
        elif mode == "sequence":
            # Sequence模式：多个子工具按顺序执行
            tool_sequence = config.get("tool_sequence", [])
            for child_tool_name in tool_sequence:
                if not child_tool_name:
                    continue
                
                try:
                    child_data = get_tool_instance_func(child_tool_name)
                    if child_data and child_data.get("status") == "ok":
                        child_tool_type = child_data.get("tool_type")
                        child_config = child_data.get("config", {})
                        child_comment = child_data.get("comment")
                        
                        child_node, error = parse_meta_tool_tree(
                            child_tool_name,
                            child_tool_type,
                            child_config,
                            get_tool_instance_func,
                            visited.copy(),
                            path.copy(),
                            max_depth,
                            comment=child_comment
                        )
                        
                        if error:
                            return None, error
                        
                        if child_node:
                            child_node.parent = node
                            node.children.append(child_node)
                    else:
                        pass
                except Exception:
                    pass
        
        elif mode == "alt":
            # Alt模式：多个候选工具
            candidates = (
                config.get("tool_alternatives")
                or config.get("tool_candidates")
                or config.get("tools")
                or []
            )
            candidates = [c for c in candidates if c]
            
            for child_tool_name in candidates:
                if not child_tool_name:
                    continue
                
                try:
                    child_data = get_tool_instance_func(child_tool_name)
                    if child_data and child_data.get("status") == "ok":
                        child_tool_type = child_data.get("tool_type")
                        child_config = child_data.get("config", {})
                        child_comment = child_data.get("comment")
                        
                        child_node, error = parse_meta_tool_tree(
                            child_tool_name,
                            child_tool_type,
                            child_config,
                            get_tool_instance_func,
                            visited.copy(),
                            path.copy(),
                            max_depth,
                            comment=child_comment
                        )
                        
                        if error:
                            return None, error
                        
                        if child_node:
                            child_node.parent = node
                            node.children.append(child_node)
                    else:
                        pass
                except Exception:
                    pass
    
    # 从路径中移除当前工具（回溯）
    path.pop()
    
    return node, None


def collect_all_tools(node: ToolNode) -> List[ToolNode]:
    """
    收集树中的所有工具节点（包括根节点）。
    
    返回：
        所有工具节点的列表
    """
    result = [node]
    for child in node.children:
        result.extend(collect_all_tools(child))
    return result

