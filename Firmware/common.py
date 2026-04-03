from __future__ import annotations

import json
from typing import Any, Optional, Tuple


def extract_longest_json(text: str) -> Optional[Tuple[str, Any]]:
    """
    Scan an arbitrary string and return the longest valid JSON substring.

    Returns (raw_json_text, parsed_object) when successful, otherwise None.
    The parser skips braces contained inside double-quoted strings and
    handles both object `{...}` and array `[...]` payloads.
    """

    best: Optional[Tuple[str, Any]] = None
    best_len = -1
    length = len(text)

    for start, ch in enumerate(text):
        if ch not in "{[":
            continue
        stack = [ch]
        in_string = False
        escape = False

        for idx in range(start + 1, length):
            c = text[idx]

            if in_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
                continue

            if c == '"':
                in_string = True
                continue

            if c in "{[":
                stack.append(c)
                continue

            if c in "}]":
                if not stack:
                    break
                opening = stack.pop()
                if (opening == "{" and c != "}") or (opening == "[" and c != "]"):
                    break
                if stack:
                    continue

                segment = text[start : idx + 1]
                try:
                    parsed = json.loads(segment)
                except json.JSONDecodeError:
                    pass
                else:
                    seg_len = idx + 1 - start
                    if seg_len > best_len:
                        best = (segment, parsed)
                        best_len = seg_len
                break

    return best
