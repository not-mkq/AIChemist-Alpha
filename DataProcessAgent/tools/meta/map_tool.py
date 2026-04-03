"""
map_tool.py

Map 模式的 Meta Tool 代码。
这是一个占位代码，实际执行逻辑在 meta_runtime.py 中。
"""

from tool_runtime import regist_tool

def map_tool(*args, **kwargs):
    """
    Map 模式的 Meta Tool。
    
    此函数不会被直接调用，仅用于注册工具代码。
    实际执行逻辑在 meta_runtime.py 的 run_meta_tool 中。
    """
    raise NotImplementedError("Map tool should be executed through meta_runtime.run_meta_tool")


# 注册工具代码
regist_tool(
    map_tool,
    tool_name="map",
    comment="# Map 模式 Meta Tool\n\n对某个范围内的所有项目执行指定的工具。\n\n支持的 scope:\n- `item->batch`: 对某个 batch 下的所有 item 执行工具\n- `batch->project`: 对某个 project 下的所有 batch 执行工具\n- `item->project`: 对某个 project 下的所有 item 执行工具"
)

