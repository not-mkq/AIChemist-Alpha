from __future__ import annotations

from typing import List, Tuple

from reportlab.lib import colors
from reportlab.platypus import Flowable, Paragraph
from reportlab.lib.styles import ParagraphStyle

from .pdf_theme import (
    BUBBLE_PADDING,
    BUBBLE_RADIUS,
    DEFAULT_ROLE_THEME,
    RoleTheme,
    tint,
)


class BubbleFlowable(Flowable):
    """
    Speech bubble style flowable capable of splitting across pages.
    """

    def __init__(
        self,
        width: float,
        header_html: str,
        body_chunks: List[str],
        theme: RoleTheme | None,
        header_style: ParagraphStyle,
        body_style: ParagraphStyle,
        continuation: bool = False,
    ) -> None:
        super().__init__()
        self.width = width
        self.header_html = header_html
        self.body_chunks = body_chunks
        self.theme = theme or DEFAULT_ROLE_THEME
        self.header_style = header_style
        self.body_style = body_style
        self.continuation = continuation

        self.avatar_size = 28
        self.body_spacing = 6

        self._header_para: Paragraph | None = None
        self._header_height: float = 0.0
        self._wrapped_body: List[Tuple[str, Paragraph, float]] = []
        self.height: float = 0.0
        self.text_width: float = 0.0

    def wrap(self, availWidth, availHeight):
        self.text_width = self.width - self.avatar_size - BUBBLE_PADDING * 2
        header_html = self.header_html
        if self.continuation:
            header_html = f"{header_html} <font size=9 color='#5c6370'>(续)</font>"

        self._header_para = Paragraph(header_html, self.header_style)
        _, header_h = self._header_para.wrap(self.text_width, availHeight)
        self._header_height = header_h

        self._wrapped_body = []
        total_body_height = 0.0

        for chunk in self.body_chunks:
            paragraph = Paragraph(chunk, self.body_style)
            _, h = paragraph.wrap(self.text_width, availHeight)
            self._wrapped_body.append((chunk, paragraph, h))
            total_body_height += h

        spacing = self.body_spacing * max(0, len(self._wrapped_body) - 1)
        self.height = header_h + total_body_height + spacing + BUBBLE_PADDING * 2
        return self.width, self.height

    def split(self, availWidth, availHeight):
        available = availHeight - BUBBLE_PADDING * 2
        if available <= self._header_height or not self._wrapped_body:
            return []

        chunks: List[str] = []
        height_used = self._header_height
        consumed = 0

        for chunk, _, paragraph_height in self._wrapped_body:
            gap = self.body_spacing if chunks else 0
            if height_used + gap + paragraph_height > available:
                break
            height_used += gap + paragraph_height
            chunks.append(chunk)
            consumed += 1

        if not chunks:
            return []

        remaining_chunks = [chunk for chunk, _, _ in self._wrapped_body][consumed:]
        flowables = [
            BubbleFlowable(
                self.width,
                self.header_html,
                chunks,
                self.theme,
                self.header_style,
                self.body_style,
                continuation=self.continuation,
            )
        ]

        if remaining_chunks:
            flowables.append(
                BubbleFlowable(
                    self.width,
                    self.header_html,
                    remaining_chunks,
                    self.theme,
                    self.header_style,
                    self.body_style,
                    continuation=True,
                )
            )

        return flowables

    def draw(self):
        canvas = self.canv
        bubble_x = self.avatar_size
        text_x = bubble_x + BUBBLE_PADDING

        self._draw_bubble(canvas, bubble_x, 0, self.width - bubble_x, self.height)
        self._draw_avatar(canvas, self.avatar_size / 2, self.height - self.avatar_size / 2 - 1)

        cursor = self.height - BUBBLE_PADDING
        header_para = self._header_para
        if header_para is None:
            return
        header_y = cursor - self._header_height
        header_para.drawOn(canvas, text_x, header_y)
        cursor = header_y - self.body_spacing

        for _, paragraph, height in self._wrapped_body:
            body_y = cursor - height
            paragraph.drawOn(canvas, text_x, body_y)
            cursor = body_y - self.body_spacing

    # drawing helpers --------------------------------------------------

    def _draw_bubble(self, canvas, x: float, y: float, width: float, height: float):
        base = tint(self.theme.color, 0.35)
        canvas.saveState()
        canvas.setFillColor(base)
        canvas.setStrokeColor(tint(self.theme.color, 0.15))
        canvas.setLineWidth(0.4)
        canvas.roundRect(x, y, width, height, BUBBLE_RADIUS, fill=1, stroke=1)

        highlight = tint(self.theme.color, 0.7)
        canvas.setFillColor(highlight)
        canvas.roundRect(x, y + height / 2, width, height / 2, BUBBLE_RADIUS, fill=1, stroke=0)
        canvas.restoreState()

    def _draw_avatar(self, canvas, center_x: float, center_y: float):
        canvas.saveState()
        canvas.setFillColor(self.theme.color)
        canvas.circle(center_x, center_y, self.avatar_size / 2, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(center_x, center_y - 4, self.theme.avatar)
        canvas.restoreState()
