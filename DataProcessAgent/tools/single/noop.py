from tool_runtime import regist_tool


def noop(tool_name, **kwargs):
    # Do nothing and succeed
    return


regist_tool(noop, tool_name="noop")
