# tools/single/primitive_sleep.py
import time
from tool_runtime import regist_tool

def primitive_sleep(
    tool_name: str,
    seconds: float = 1.0,
    **kwargs
) -> None:
    """
    休眠指定秒数。
    """
    time.sleep(float(seconds))

regist_tool(primitive_sleep)
