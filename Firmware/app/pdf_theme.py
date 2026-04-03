from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib import colors


@dataclass(frozen=True)
class RoleTheme:
    label: str
    color: colors.Color
    avatar: str


LIGHT_BG = colors.HexColor("#f7f7fb")
ACCENT = colors.HexColor("#4c6ef5")
SUB_ACCENT = colors.HexColor("#8a63d2")
TEXT_COLOR = colors.HexColor("#0b1220")
BUBBLE_RADIUS = 12
BUBBLE_PADDING = 10

ROLE_THEME = {
    "user_message": RoleTheme("🧪 USER", colors.HexColor("#dce9ff"), "U"),
    "assistant_message": RoleTheme("🤖 AI", colors.HexColor("#f3e8ff"), "AI"),
    "tool_call": RoleTheme("🛠 TOOL CALL", colors.HexColor("#e8f5e9"), "TC"),
    "tool_result": RoleTheme("📦 TOOL RESULT", colors.HexColor("#ede7f6"), "TR"),
    "audit_request": RoleTheme("🛡 AUDIT", colors.HexColor("#fff3e0"), "AQ"),
    "audit_decision": RoleTheme("✅ AUDIT", colors.HexColor("#f1f8e9"), "AD"),
    "system": RoleTheme("ℹ️ SYSTEM", colors.HexColor("#eceff1"), "SYS"),
}

DEFAULT_ROLE_THEME = RoleTheme("ℹ️ EVENT", colors.HexColor("#eceff1"), "EV")


def tint(color: colors.Color, strength: float) -> colors.Color:
    """Blend a color toward white to simulate a gradient."""
    strength = max(0.0, min(1.0, strength))
    return colors.Color(
        color.red + (1 - color.red) * strength,
        color.green + (1 - color.green) * strength,
        color.blue + (1 - color.blue) * strength,
    )
