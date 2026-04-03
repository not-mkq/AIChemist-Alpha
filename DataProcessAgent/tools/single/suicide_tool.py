import os
import signal
import time
from tool_runtime import regist_tool, return_value

def suicide_tool(tool_name: str, **kwargs):
    """
    故意在运行中杀掉进程，模拟崩溃。
    """
    print(f"[SuicideTool] Process {os.getpid()} is about to commit suicide...")
    time.sleep(0.5) 
    os.kill(os.getpid(), signal.SIGKILL)
    
    # 物理调用以通过审计
    return_value(0)

# 注册工具
regist_tool(suicide_tool)