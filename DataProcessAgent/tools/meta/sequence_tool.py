"""
sequence_tool.py

Sequence 模式的 Meta Tool 代码。
这是一个占位代码，实际执行逻辑在 meta_runtime.py 中。
"""

from tool_runtime import regist_tool

def sequence_tool(*args, **kwargs):
    """
    Sequence 模式的 Meta Tool。
    
    此函数不会被直接调用，仅用于注册工具代码。
    实际执行逻辑在 meta_runtime.py 的 run_meta_tool 中。
    """
    raise NotImplementedError("Sequence tool should be executed through meta_runtime.run_meta_tool")


# 注册工具代码
regist_tool(
    sequence_tool,
    tool_name="sequence",
    comment="# Sequence 模式 Meta Tool\n\n按顺序执行一系列工具。\n\n工具会按照 `tool_sequence` 中定义的顺序依次执行，每个工具的输出可以作为下一个工具的输入。\n\n支持的 scope:\n- `item`: 在 item 级别执行\n- `batch`: 在 batch 级别执行\n- `project`: 在 project 级别执行"
)

