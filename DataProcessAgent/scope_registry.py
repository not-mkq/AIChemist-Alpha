from typing import Optional, Literal

ToolType = Literal["single", "merge", "meta_map", "meta_sequence", "meta_alt"]
Scope = str

def get_child_scope(parent_mode: Literal["sequence", "map"], 
                    parent_scope: Scope, 
                    child_tool_type: ToolType) -> Optional[Scope]:
    """
    计算子工具的 Scope。
    
    Args:
        parent_mode: 调用者的模式 ("sequence" 或 "map")
        parent_scope: 调用者当前的 scope
        child_tool_type: 子工具的类型 ("single", "merge", "meta_map", "meta_sequence", "meta_alt")
        
    Returns:
        传给子工具的 Scope，如果组合非法则返回 None。
    """
    
    # 1. Sequence (负责衰减)
    if parent_mode == "sequence":
        # 如果是 item scope，无法再衰减，只能调 single/sequence/alt
        if parent_scope == "item":
            if child_tool_type in ("single", "meta_sequence", "meta_alt"):
                return "item"
            return None # 非法：item scope 不能调 merge/map

        # 如果是 batch scope
        if parent_scope == "batch":
            if child_tool_type in ("single", "meta_sequence", "meta_alt"):
                return "batch" # 透传
            if child_tool_type in ("merge", "meta_map"):
                return "item->batch" # 衰减：在 batch 下聚合/迭代 items
            return None

        # 如果是 project scope
        if parent_scope == "project":
            if child_tool_type in ("single", "meta_sequence", "meta_alt"):
                return "project" # 透传
            if child_tool_type in ("merge", "meta_map"):
                return "batch->project" # 衰减：在 project 下聚合/迭代 batches
            return None
            
        return None

    # 2. Map (负责解包)
    if parent_mode == "map":
        # 如果是 item->batch (迭代 items)
        if parent_scope == "item->batch":
            if child_tool_type in ("single", "meta_sequence", "meta_alt"):
                return "item" # 解包：对每个 item 执行
            return None # 非法：不能在 item 上跑 merge/map

        # 如果是 batch->project (迭代 batches)
        if parent_scope == "batch->project":
            if child_tool_type in ("single", "meta_sequence", "meta_alt"):
                return "batch" # 解包：对每个 batch 执行
            if child_tool_type in ("merge", "meta_map"):
                return "item->batch" # 解包+匹配：对每个 batch 执行 item->batch
            return None
            
        # 如果是 item->project (全项目迭代 items)
        if parent_scope == "item->project":
             if child_tool_type in ("single", "meta_sequence", "meta_alt"):
                return "item" # 解包：对每个 item 执行
             return None

        return None

    return None
