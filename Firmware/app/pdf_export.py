from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List
import json

import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

import logging

from .export_utils import chunk_html, normalize_event_record, soft_break, draft_text
from .pdf_components import BubbleFlowable
from .pdf_html import HTML_ENGINE_AVAILABLE, render_session_pdf
from .pdf_theme import (
    ACCENT,
    DEFAULT_ROLE_THEME,
    LIGHT_BG,
    ROLE_THEME,
    SUB_ACCENT,
    TEXT_COLOR,
)


logger = logging.getLogger(__name__)


def _register_font() -> str:
    custom_env = os.getenv("PDF_FONT_PATH")
    font_dirs = [
        Path(__file__).resolve().parent / "fonts",
        Path.cwd() / "fonts",
    ]

    candidates = [
        ("SourceHanSansCN-Regular", "/usr/share/fonts/adobe-source-han-sans/SourceHanSansCN-Regular.otf", {}),
        ("SourceHanSansCN-Normal", "/usr/share/fonts/adobe-source-han-sans/SourceHanSansCN-Normal.otf", {}),
        ("SarasaGothicSC", "/usr/share/fonts/sarasa-gothic/Sarasa-Regular.ttc", {"subfontIndex": 0}),
        ("WenQuanYiZenHei", "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc", {"subfontIndex": 0}),
        ("NotoSerifCJK-Light", "/usr/share/fonts/noto-cjk/NotoSerifCJK-Light.ttc", {"subfontIndex": 0}),
        ("DejaVu", "/usr/share/fonts/TTF/DejaVuSans.ttf", {}),
        ("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", {}),
        ("STSong-Light", None, {}),
    ]

    def font_entries():
        if custom_env:
            yield ("CustomFont", custom_env, {})
        for directory in font_dirs:
            if directory.exists():
                for font_file in directory.glob("*.ttf"):
                    yield (font_file.stem, str(font_file), {})
                for font_file in directory.glob("*.otf"):
                    yield (font_file.stem, str(font_file), {})
        for entry in candidates:
            yield entry

    for name, path, kwargs in font_entries():
        try:
            if path and Path(path).exists():
                pdfmetrics.registerFont(TTFont(name, path, **kwargs))
                return name
            elif path is None:
                pdfmetrics.registerFont(UnicodeCIDFont(name))
                return name
        except Exception:
            continue
    return "Helvetica"


DEFAULT_FONT = _register_font()


def _chapter_title(text: str, styles) -> Paragraph:
    return Paragraph(text, styles["chapter"])


def _format_value(value: Any) -> str:
    if isinstance(value, dict):
        rows = [f"{escape(str(k))}: {_format_value(v)}" for k, v in value.items()]
        return "<br/>".join(rows)
    if isinstance(value, list):
        rows = [f"- {_format_value(v)}" for v in value]
        return "<br/>".join(rows)
    text = escape(soft_break(value)).replace("\n", "<br/>")
    return text


def _render_event(idx: int, event: Dict[str, Any], styles, width: float):
    normalized = normalize_event_record(event)
    evt_type = normalized.get("type", "system")
    theme = ROLE_THEME.get(evt_type, DEFAULT_ROLE_THEME)
    ts = escape(normalized.get("timestamp", ""))
    header_html = f"<b>{theme.label} · #{idx}</b>　{ts}"

    draft_body = draft_text(normalized)
    body_text = _event_body_text(normalized, draft_body)
    body_chunks = _format_body_chunks(body_text)
    if not body_chunks:
        body_chunks = ["<i>（无文本内容）</i>"]

    flows: List[Any] = []
    bubble = BubbleFlowable(width, header_html, body_chunks, theme, styles["label"], styles["body"])
    flows.append(bubble)

    if draft_body:
        flows.append(Spacer(1, 4))
        flows.append(Paragraph("思考草稿（折叠内容）", styles["code_label"]))
        flows.append(_code_table(soft_break(draft_body), styles, width))

    for label, text in _code_blocks(normalized):
        flows.append(Spacer(1, 4))
        flows.append(Paragraph(label, styles["code_label"]))
        flows.append(_code_table(text, styles, width))

    return flows


def _event_body_text(event: Dict[str, Any], draft_body: str | None = None) -> str | None:
    evt_type = event.get("type")
    if evt_type in {"user_message", "assistant_message"}:
        if draft_body:
            return "思考草稿（默认折叠，详见附件）"
        return event.get("content")
    if evt_type == "audit_request":
        decision = event.get("ai_decision", {})
        summary = decision.get("summary")
        doubts = decision.get("doubts") or []
        lines = [summary] if summary else []
        if doubts:
            lines.append("可能风险：" + "；".join(doubts))
        return "\n".join(filter(None, lines))
    if evt_type == "audit_decision":
        status = "已通过" if event.get("approved") else "已拒绝"
        note = event.get("note")
        return f"{status}{' · ' + note if note else ''}"
    if evt_type == "tool_call":
        return f"调用 {event.get('tool') or '未知工具'}"
    if evt_type == "tool_result":
        return f"{event.get('tool') or '工具'} 返回结果"
    return None


def _format_body_chunks(text: str | None) -> List[str]:
    if not text:
        return []
    html = escape(text).replace("\n", "<br/>")
    return chunk_html(html, max_chars=2000, max_lines=40)


CODE_LABELS = {
    "arguments": "调用参数",
    "result": "返回结果",
    "ai_decision": "AI 审计分析",
    "analysis": "审计分析",
}


def _code_blocks(event: Dict[str, Any]) -> List[tuple[str, str]]:
    blocks: List[tuple[str, str]] = []
    for key, value in event.items():
        if isinstance(value, (dict, list)):
            label = CODE_LABELS.get(key, key)
            pretty = json.dumps(value, ensure_ascii=False, indent=2)
            blocks.append((label, pretty))
    return blocks


def _code_table(text: str, styles, width: float):
    pre = Preformatted(text, styles["code_block"])
    table = Table([[pre]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#05070b")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1f2a37")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def build_session_pdf(summary: Dict[str, Any], events: List[Dict[str, Any]], agents: Dict[str, Any]) -> bytes:
    if HTML_ENGINE_AVAILABLE:
        try:
            return render_session_pdf(summary, events, agents)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("HTML PDF rendering failed (%s); falling back to ReportLab", exc)
    return _build_reportlab_pdf(summary, events, agents)


def _build_reportlab_pdf(summary: Dict[str, Any], events: List[Dict[str, Any]], agents: Dict[str, Any]) -> bytes:
    buffer = BytesIO()
    doc_template = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    for key in ("Title", "Heading1", "Heading2", "BodyText"):
        if key in styles:
            styles[key].fontName = DEFAULT_FONT
    styles.add(
        ParagraphStyle(
            "chapter",
            parent=styles["Heading1"],
            textColor=ACCENT,
            spaceAfter=12,
            fontName=DEFAULT_FONT,
        )
    )
    styles.add(
        ParagraphStyle(
            "body",
            parent=styles["BodyText"],
            textColor=TEXT_COLOR,
            leading=16,
            fontName=DEFAULT_FONT,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            "label",
            parent=styles["BodyText"],
            textColor=SUB_ACCENT,
            leading=14,
            fontName=DEFAULT_FONT,
        )
    )
    styles.add(
        ParagraphStyle(
            "code_label",
            parent=styles["BodyText"],
            textColor=ACCENT,
            fontName=DEFAULT_FONT,
            fontSize=10,
            leading=12,
            spaceBefore=6,
        )
    )
    styles.add(
        ParagraphStyle(
            "code_block",
            parent=styles["BodyText"],
            fontName="Courier",
            fontSize=8,
            leading=10,
            textColor=colors.whitesmoke,
        )
    )

    story = []
    story.append(Paragraph("多智能体会话报告", styles["Title"]))
    story.append(Paragraph(f"会话 ID：{summary.get('session_id')}", styles["body"]))
    story.append(Paragraph(f"事件总数：{summary.get('events', 0)}", styles["body"]))
    story.append(Spacer(1, 12))

    story.append(_chapter_title("第一章：可用智能体一览", styles))
    agent_rows = [
        [
            Paragraph("Agent", styles["label"]),
            Paragraph("简介", styles["label"]),
        ]
    ]
    for name, doc in agents.items():
        intro = (doc.get("intro") or "").strip() or "（暂无介绍）"
        agent_rows.append(
            [
                Paragraph(escape(name), styles["body"]),
                Paragraph(escape(intro), styles["body"]),
            ]
        )
    table = Table(agent_rows, colWidths=[4 * cm, 11.5 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), LIGHT_BG),
                ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 18))

    story.append(_chapter_title("第二章：会话与审计记录", styles))
    width = doc_template.width
    for idx, event in enumerate(events, start=1):
        story.extend(_render_event(idx, event, styles, width))
        story.append(Spacer(1, 6))

    doc_template.build(story)
    buffer.seek(0)
    return buffer.read()
