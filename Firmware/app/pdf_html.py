from __future__ import annotations

import json
from html import escape
from typing import Any, Dict

from jinja2 import BaseLoader, Environment, select_autoescape

try:
    from weasyprint import HTML

    HTML_ENGINE_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    HTML_ENGINE_AVAILABLE = False
    HTML = None  # type: ignore

from .export_utils import normalize_event_record, draft_text
from .pdf_theme import ROLE_THEME, DEFAULT_ROLE_THEME


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang=\"zh-CN\">
  <head>
    <meta charset=\"utf-8\" />
    <style>
      body {
        font-family: 'Source Han Sans', 'Inter', 'Microsoft YaHei', sans-serif;
        background: #05070b;
        color: #e6edf3;
        margin: 0;
        padding: 32px;
      }
      .report {
        max-width: 900px;
        margin: 0 auto;
      }
      .hero {
        background: linear-gradient(135deg, #4c6ef5, #8a63d2);
        border-radius: 24px;
        padding: 24px;
        margin-bottom: 24px;
        color: #fff;
      }
      .hero h1 {
        margin: 0 0 8px;
        font-size: 28px;
      }
      .chips {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }
      .chip {
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.6);
        padding: 4px 12px;
        font-size: 13px;
      }
      .section-title {
        margin: 24px 0 12px;
        font-size: 20px;
        color: #a5b4fc;
      }
      table.agents {
        width: 100%;
        border-collapse: collapse;
        background: #0b121a;
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid #1f2a37;
      }
      table.agents th,
      table.agents td {
        padding: 12px 16px;
        font-size: 14px;
        border-bottom: 1px solid #1f2a37;
        text-align: left;
      }
      table.agents th {
        background: rgba(76, 110, 245, 0.2);
        color: #cfd8ff;
      }
      table.agents tr:last-child td {
        border-bottom: none;
      }
      .timeline {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .event-card {
        display: flex;
        gap: 16px;
        padding: 18px;
        border-radius: 18px;
        border: 1px solid #1f2a37;
        background: #0b121a;
      }
      .avatar {
        width: 52px;
        height: 52px;
        border-radius: 18px;
        border: 1px solid #2c3750;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 26px;
      }
      .event-body {
        flex: 1;
      }
      .event-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 10px;
      }
      .event-title {
        font-size: 16px;
        font-weight: 600;
      }
      .subtitle {
        font-size: 13px;
        color: #93a4b8;
        margin-left: 4px;
      }
      .hint {
        margin: 4px 0 0;
        font-size: 12px;
        color: #93a4b8;
      }
      .event-meta {
        font-size: 12px;
        color: #93a4b8;
      }
      .event-text {
        line-height: 1.6;
        margin-bottom: 8px;
      }
      details.draft {
        background: #08101a;
        border: 1px solid #1f2a37;
        border-radius: 12px;
        padding: 10px 14px;
      }
      details.draft summary {
        cursor: pointer;
        color: #a5b4fc;
        font-size: 14px;
      }
      details.draft[open] summary {
        margin-bottom: 8px;
      }
      pre.code {
        background: #05070b;
        border-radius: 12px;
        padding: 14px;
        border: 1px solid #1f2a37;
        font-size: 12px;
        font-family: 'JetBrains Mono', 'Sarasa Term SC', monospace;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .code-label {
        display: inline-block;
        margin-bottom: 6px;
        font-size: 12px;
        color: #a5b4fc;
      }
    </style>
  </head>
  <body>
    <div class=\"report\">
      <section class=\"hero\">
        <h1>多智能体会话报告</h1>
        <div class=\"chips\">
          <span class=\"chip\">会话 ID：{{ summary.session_id }}</span>
          <span class=\"chip\">事件总数：{{ summary.events }}</span>
        </div>
      </section>

      <section>
        <div class=\"section-title\">第一章：可用智能体一览</div>
        <table class=\"agents\">
          <tr>
            <th>智能体</th>
            <th>简介</th>
          </tr>
          {% for agent in agents %}
          <tr>
            <td>{{ agent.name }}</td>
            <td>{{ agent.intro }}</td>
          </tr>
          {% endfor %}
        </table>
      </section>

      <section>
        <div class=\"section-title\">第二章：会话与审计记录</div>
        <div class=\"timeline\">
          {% for event in events %}
          <div class=\"event-card\">
            <div class=\"avatar\" style=\"border-color: {{ event.color }}; background: {{ event.color }}22\">{{ event.icon }}</div>
            <div class=\"event-body\">
              <div class=\"event-header\">
                <div>
                  <div class=\"event-title\">
                    {{ event.label }}
                    {% if event.subtitle %}
                    <span class=\"subtitle\">· {{ event.subtitle }}</span>
                    {% endif %}
                  </div>
                  {% if event.hint %}
                  <p class=\"hint\">{{ event.hint }}</p>
                  {% endif %}
                </div>
                <div class=\"event-meta\">#{{ loop.index }} · {{ event.timestamp }}</div>
              </div>
              {% if event.body_html %}
              <div class=\"event-text\">{{ event.body_html | safe }}</div>
              {% endif %}
              {% for block in event.code_blocks %}
              <pre class=\"code\"><span class=\"code-label\">{{ block.label }}</span>{{ block.value }}</pre>
              {% endfor %}
            </div>
          </div>
          {% endfor %}
        </div>
      </section>
    </div>
  </body>
</html>
"""

env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
template = env.from_string(HTML_TEMPLATE)


def _format_text(content: str | None) -> str:
    if not content:
        return ""
    return escape(content).replace("\n", "<br/>")


def _color_hex(color) -> str:
    try:
        r = int(color.red * 255)
        g = int(color.green * 255)
        b = int(color.blue * 255)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return "#4c6ef5"


def _build_event(event: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_event_record(event)
    meta = ROLE_THEME.get(normalized.get("type", "system"), DEFAULT_ROLE_THEME)
    subtitle = normalized.get("tool_name") or normalized.get("tool")
    body_text = None
    evt_type = normalized.get("type")
    draft_body = draft_text(normalized)
    if evt_type in {"user_message", "assistant_message"}:
        if draft_body:
            body_text = f"<details class=\"draft\"><summary>思考草稿（点击展开）</summary>{_format_text(draft_body)}</details>"
        else:
            body_text = normalized.get("content")
    elif evt_type == "audit_request":
        summary = normalized.get("ai_decision", {}).get("summary")
        doubts = normalized.get("ai_decision", {}).get("doubts") or []
        parts = [summary] if summary else []
        if doubts:
            parts.append("可能风险：" + "；".join(doubts))
        body_text = "\n".join(filter(None, parts))
    elif evt_type == "audit_decision":
        status = "已通过" if normalized.get("approved") else "已拒绝"
        note = normalized.get("note")
        body_text = f"{status}{' · ' + note if note else ''}"

    code_blocks = []
    for key, value in normalized.items():
        if key in {"type", "timestamp", "content", "tool", "tool_name", "note", "approved"}:
            continue
        if isinstance(value, (dict, list)):
            code_blocks.append({"label": key, "value": json.dumps(value, ensure_ascii=False, indent=2)})

    return {
        "type": evt_type,
        "label": meta.label,
        "icon": meta.avatar,
        "color": _color_hex(getattr(meta, "color", None)),
        "subtitle": subtitle,
        "hint": meta.label if evt_type == "system" else None,
        "timestamp": normalized.get("timestamp", ""),
        "body_html": body_text
        if body_text and body_text.startswith("<details")
        else _format_text(body_text),
        "code_blocks": code_blocks,
    }


def _format_agents(agents: Dict[str, Any]):
    formatted = []
    for name, doc in agents.items():
        intro = (doc.get("intro") or "").strip() or "（暂无介绍）"
        formatted.append({"name": name, "intro": intro})
    return formatted


def build_session_html(summary: Dict[str, Any], events: list[Dict[str, Any]], agents: Dict[str, Any]) -> str:
    formatted_events = [_build_event(evt) for evt in events]
    return template.render(summary=summary, events=formatted_events, agents=_format_agents(agents))


def render_session_pdf(summary: Dict[str, Any], events: list[Dict[str, Any]], agents: Dict[str, Any]) -> bytes:
    if not HTML_ENGINE_AVAILABLE:
        raise RuntimeError("WeasyPrint is not available for HTML-based PDF rendering")

    html = build_session_html(summary, events, agents)
    return HTML(string=html).write_pdf()
