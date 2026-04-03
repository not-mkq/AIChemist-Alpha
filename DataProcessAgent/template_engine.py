import re
import math
import fnmatch
import logging
from typing import Any, Dict, Optional, List

logger = logging.getLogger("template_engine")

def render_template(template: Any, context: Dict[str, Any]) -> Any:
    if isinstance(template, list):
        return [render_template(item, context) for item in template]
    if isinstance(template, dict):
        return {k: render_template(v, context) for k, v in template.items()}
    if not isinstance(template, str) or "{" not in template:
        return template

    try:
        return _parse(template, context, 0)
    except Exception:
        return template

def _parse(text: str, context: Dict[str, Any], depth: int) -> str:
    if depth > 20:
        raise RecursionError("Template recursion limit exceeded")

    buffer = []
    i = 0
    length = len(text)
    
    while i < length:
        char = text[i]
        
        # 1. LaTeX Math Block
        if char == '$':
            is_double = (i + 1 < length and text[i+1] == '$')
            terminator = '$$' if is_double else '$'
            start_len = 2 if is_double else 1
            
            end_idx = text.find(terminator, i + start_len)
            if end_idx == -1:
                raise ValueError("Unclosed Math Block")
            
            math_content = text[i + start_len : end_idx]
            resolved_math = _resolve_escapes_only(math_content, context, depth)
            
            buffer.append(terminator + resolved_math + terminator)
            i = end_idx + start_len
            continue

        # 2. Open Brace
        elif char == '{':
            brace_depth = 1
            j = i + 1
            while j < length:
                if text[j] == '{': brace_depth += 1
                elif text[j] == '}': 
                    brace_depth -= 1
                    if brace_depth == 0: break
                j += 1
            
            if brace_depth != 0:
                raise ValueError("Unclosed Brace")
            
            inner_raw = text[i+1:j]
            # Recursively parse inner content
            resolved_inner = _parse(inner_raw, context, depth + 1)
            # Evaluate
            val = _evaluate_token(resolved_inner, context)
            buffer.append(str(val))
            i = j + 1
            continue

        elif char == '}':
            raise ValueError("Unexpected Close Brace")

        else:
            buffer.append(char)
            i += 1
            
    return "".join(buffer)

def _resolve_escapes_only(text: str, context: Dict[str, Any], depth: int) -> str:
    buffer = []
    i = 0
    length = len(text)
    while i < length:
        # Check for {@ ... } 
        if text[i] == '{' and i + 1 < length and text[i+1] == '@':
            brace_depth = 1
            j = i + 1
            while j < length:
                if text[j] == '{': brace_depth += 1
                elif text[j] == '}': 
                    brace_depth -= 1
                    if brace_depth == 0: break
                j += 1
            
            if brace_depth != 0:
                buffer.append(text[i])
                i += 1
                continue
                
            # Content is @ ...
            inner_with_at = text[i+1:j] # "@ xxx"
            content_to_parse = inner_with_at[1:] # " xxx"
            resolved_inner = _parse(content_to_parse, context, depth + 1)
            
            # Return {stripped_content}
            buffer.append("{" + resolved_inner.strip() + "}")
            i = j + 1
        else:
            buffer.append(text[i])
            i += 1
    return "".join(buffer)

def _evaluate_token(token: str, context: Dict[str, Any]) -> Any:
    t = token.strip()
    
    if t.startswith("@"):
        return "{" + t[1:].strip() + "}"
        
    if t.startswith("="):
        expr = t[1:].strip()
        try:
            return _safe_eval(expr, context)
        except Exception as e:
            return f"ERROR({e})"
            
    if t.startswith("%"):
        content = t[1:].strip()
        if content.endswith("%"):
            content = content[:-1].strip()
        return _eval_match_dsl(content, context)
        
    if ":" in t:
        key, fmt = t.split(":", 1)
        val = context.get(key.strip())
        if val is not None:
            try: return format(float(val), fmt)
            except: return str(val)
    else:
        val = context.get(t)
        if val is not None: return str(val)
            
    return "{" + token + "}"

def _safe_eval(expr: str, context: Dict[str, Any]) -> Any:
    def _exists(name: str) -> bool:
        return name in context

    def _has_value(name: str) -> bool:
        if name not in context:
            return False
        val = context[name]
        return val is not None and str(val) != ""

    def _typeof(val: Any) -> str:
        return type(val).__name__

    safe_globals = {
        "__builtins__": {},
        "math": math, "re": re, "fnmatch": fnmatch,
        "abs": abs, "min": min, "max": max, "len": len,
        "str": str, "int": int, "float": float,
        "exists": _exists,
        "has_value": _has_value,
        "typeof": _typeof,
    }
    return eval(expr, safe_globals, context)

def _eval_match_dsl(content: str, context: Dict[str, Any]) -> str:
    raw = content.strip()
    if " in " not in raw: return ""
    head, expr_str = raw.rsplit(" in ", 1)
    if " as " not in head: return ""
    match_part, vars_part = head.rsplit(" as ", 1)
    
    if " rematch " in match_part:
        mode, split_kw = "regex", " rematch "
    elif " match " in match_part:
        mode, split_kw = "glob", " match "
    else:
        return ""
        
    target_str, pattern_str = match_part.rsplit(split_kw, 1)
    pattern = pattern_str.strip().strip("'\"")
    target = target_str.strip()
    var_names = [v.strip() for v in vars_part.split(",")]
    
    matched_groups = []
    if mode == "glob":
        regex_pat = re.escape(pattern).replace(r"\*", r"(.*?)")
        m = re.match(f"^{regex_pat}$", target)
        if m: matched_groups = m.groups()
        else: return ""
    else:
        m = re.match(pattern, target)
        if m: matched_groups = m.groups()
        else: return ""

    local_ctx = context.copy()
    for i, vname in enumerate(var_names):
        local_ctx[vname] = matched_groups[i] if i < len(matched_groups) else ""
        
    try:
        return str(_safe_eval(expr_str, local_ctx))
    except:
        return ""