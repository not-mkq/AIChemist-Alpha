# tools/lsv_overpotential_from_onset.py
"""
从 onset 电位计算过电位 overpotential_mV:
- 输入: onset_potential_v (V), eq_potential (V)
- 输出: overpotential_mV = (onset_potential_v - eq_potential) * 1000
"""

from tool_runtime import (
    regist_tool,
    return_value,
)


def lsv_overpotential_from_onset(
    tool_name: str,
    onset_potential_v: float,
    eq_potential: float,
) -> None:
    """
    由 onset_potential_v 和 eq_potential 计算过电位 (mV)。
    不再关心 IR 是否启用, 由上游 onset 工具决定。
    """
    overpotential_mV = (float(onset_potential_v) - float(eq_potential)) * 1000.0
    return_value(overpotential_mV)


regist_tool(lsv_overpotential_from_onset)
