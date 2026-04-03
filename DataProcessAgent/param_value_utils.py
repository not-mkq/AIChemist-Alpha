"""
param_value_utils.py

Utilities for tool instance parameter values, supporting a strict recursive
templating system via template_engine module.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List, Set, Tuple
from template_engine import render_template as render_runtime_text

logger = logging.getLogger("param_value_utils")

_WRAP_KEYS = {"value", "comment"}

# =============================================================================
# Value Wrapping / Unwrapping Logic
# =============================================================================

def extract_wrapped_value(raw: Any) -> Tuple[Any, Optional[Any], bool, bool]:
    if isinstance(raw, dict) and set(raw.keys()).issubset(_WRAP_KEYS):
        if "value" in raw:
            return raw.get("value"), raw.get("comment"), True, True
        if "comment" in raw:
            return None, raw.get("comment"), True, False
    return raw, None, False, True


def extract_wrapped_mapping(
    raw_map: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, Optional[Any]], Set[str]]:
    values: Dict[str, Any] = {}
    comments: Dict[str, Optional[Any]] = {}
    wrapped: Set[str] = set()

    if not isinstance(raw_map, dict):
        return values, comments, wrapped

    for key, raw_value in raw_map.items():
        value, comment, is_wrapped, has_value = extract_wrapped_value(raw_value)
        if has_value:
            values[key] = value
        if comment is not None:
            comments[key] = comment
        if is_wrapped:
            wrapped.add(key)

    return values, comments, wrapped


def rebuild_wrapped_value(
    value: Any,
    comment: Optional[Any],
    force_wrap: bool = False,
    *,
    comment_only: bool = False,
) -> Any:
    if comment_only:
        if comment is None:
            return None
        return {"comment": comment}

    if not force_wrap and comment is None:
        return value

    data = {"value": value}
    if comment is not None:
        data["comment"] = comment
    return data


def rebuild_wrapped_mapping(
    values: Dict[str, Any],
    comments: Optional[Dict[str, Optional[Any]]] = None,
    wrapped_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    comments = comments or {}
    wrapped_keys = wrapped_keys or set()
    rebuilt: Dict[str, Any] = {}
    for key, val in values.items():
        rebuilt[key] = rebuild_wrapped_value(
            val,
            comments.get(key),
            force_wrap=key in wrapped_keys,
        )
    return rebuilt


def is_null_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "null", "none"}:
            return True
    return False