from __future__ import annotations

import os

_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _env_flag(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized not in _FALSE_VALUES


def should_enable_reload(agent_name: str, default: bool = True) -> bool:
    """Decide whether to enable uvicorn reload based on env or config flags."""
    env_override = _env_flag("AGENT_RELOAD")
    if env_override is not None:
        return env_override
    agent_key = f"{agent_name.upper()}_RELOAD"
    agent_override = _env_flag(agent_key)
    if agent_override is not None:
        return agent_override
    return default
