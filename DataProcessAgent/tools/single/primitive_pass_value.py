# tools/primitive_pass_value.py
"""
升级版 primitive_pass_value:
- 支持从 a, b, c, d, e (通常通过 from_result) 获取 5 个数值变量。
- 输入 value：支持直接数值或数学表达式计算。
- 输出：将计算结果返回到结果列。
"""

import math
from tool_runtime import (
    regist_tool,
    return_value,
)


def primitive_pass_value(
    tool_name: str,
    value: str,
    value_type: str = "float",
    **kwargs
) -> None:
    # 定义安全沙盒环境
    env = {"__builtins__": {}}
    safe_funcs = {
        # JSON 兼容性别名
        "null": None,
        "true": True,
        "false": False,
        # 数学函数
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
        "lg": math.log10,
        "log10": math.log10,
        "ln": math.log,
        "log": math.log,
        "exp": math.exp,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "pi": math.pi,
        "e": math.e,
    }

    # 变量上下文
    vars_context = {
        **safe_funcs,
        **kwargs,
    }

    if value_type == "str":
        result = str(value)
    else:
        # 此时 value 已经被框架替换为具体的数值（如果是 {xxx} 格式）
        result = eval(str(value), env, vars_context)
        
        # 稳健转换：如果 eval 得到 None (null)，则保持 None
        if result is not None:
            if value_type == "int":
                result = int(float(result))
            elif value_type == "float":
                result = float(result)
        
    return_value(result)


# 注册工具
regist_tool(primitive_pass_value, tool_name="primitive_pass_value")