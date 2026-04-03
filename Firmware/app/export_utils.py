from __future__ import annotations

from typing import Any, Dict, List, Optional


def soft_break(text: str, width: int = 90) -> str:
    """
    Insert soft breaks into very long lines to aid PDF/HTML layout engines.
    """
    lines = []
    content = str(text)
    if not content:
        return ""

    for raw_line in content.splitlines() or [""]:
        if len(raw_line) <= width:
            lines.append(raw_line)
            continue
        for start in range(0, len(raw_line), width):
            lines.append(raw_line[start : start + width])
    return "\n".join(lines)


def chunk_html(body: str, max_chars: int = 1500, max_lines: int = 35) -> List[str]:
    """
    Split a HTML string (using <br/> separators) into chunks that paginate safely.
    """
    if not body:
        return ["(空)"]

    lines = body.split("<br/>")
    chunks: List[str] = []
    current: List[str] = []
    chars = 0

    for line in lines:
        current.append(line)
        chars += len(line)
        if len(current) >= max_lines or chars >= max_chars:
            chunks.append("<br/>".join(current))
            current = []
            chars = 0

    if current:
        chunks.append("<br/>".join(current))

    return chunks or ["(空)"]


def normalize_event_record(event: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten DB event payload into top-level fields while preserving metadata."""
    payload = dict(event.get("payload") or {})
    normalized = {k: v for k, v in event.items() if k != "payload"}

    payload_type = payload.get("type")
    if payload_type:
        normalized.setdefault("raw_type", normalized.get("type"))
        normalized["type"] = payload_type

    for key, value in payload.items():
        if key == "type":
            continue
        normalized.setdefault(key, value)

    if payload and "payload" not in normalized:
        normalized["payload"] = payload
    return normalized


def draft_text(event: Dict[str, Any]) -> Optional[str]:
    content = event.get("content")
    if not isinstance(content, str):
        return None
    flags = event.get("flags") or {}
    if isinstance(flags, dict) and flags.get("draft") is True:
        return content
    if "【思考草稿】" in content:
        return content
    return None
