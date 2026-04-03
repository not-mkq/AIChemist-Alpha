from tool_runtime import regist_tool


def always_fail(tool_name, **kwargs):
    # Simulate a runtime failure after doing minimal work
    raise RuntimeError("intentional failure for testing rollback")


regist_tool(always_fail, tool_name="always_fail")
