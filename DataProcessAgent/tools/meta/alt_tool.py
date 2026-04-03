"""
alt_tool.py

Alt 模式的 Meta Tool 代码占位。
实际执行逻辑在 meta_runtime._run_alt_mode 中完成，此文件仅用于注册工具代码。
"""

from tool_runtime import regist_tool


def alt_tool(*args, **kwargs):
    """Alt 模式 Meta Tool（不会被直接调用）。"""
    raise NotImplementedError("Alt tool should be executed through meta_runtime.run_meta_tool")


# 注册工具代码
regist_tool(
    alt_tool,
    tool_name="alt",
    comment="# Alt 模式 Meta Tool\n\n按顺序尝试候选工具，找到首个可用的工具并执行；如果全部不可用则返回错误。",
)
