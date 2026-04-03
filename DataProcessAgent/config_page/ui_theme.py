#!/usr/bin/env python3
"""
ui_theme.py

统一的 UI 样式和工具方法。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget


COLORS = {
    "bg_surface": "#f7f8fb",
    "bg_panel": "#ffffff",
    "border_subtle": "#d7dbe3",
    "text_primary": "#1c2430",
    "text_muted": "#5a6474",
    "accent": "#2f7de1",
    "warning": "#c53f3f",
    "success": "#2f8f5b",
}


def build_stylesheet(scale: float = 1.0) -> str:
    """构建统一的 Qt StyleSheet，支持 DPI 缩放。"""
    def px(val: float) -> str:
        return f"{max(1, round(val * scale))}px"

    font_base = px(15)
    font_group = px(17)
    font_badge = px(12)
    input_pad_v = px(4)
    input_pad_h = px(6)
    input_pad_right = px(18)
    card_radius = px(10)
    card_radius_lg = px(10)
    btn_height = px(34)
    btn_radius = px(8)
    scroll_width = px(8)
    scroll_margin = px(2)
    scroll_handle_radius = px(4)
    scroll_handle_min = px(18)

    return f"""
    QWidget {{
        background: {COLORS['bg_surface']};
        color: {COLORS['text_primary']};
        font-family: "Source Sans 3", "Segoe UI", "Arial", sans-serif;
        font-size: {font_base};
    }}

    QTabWidget::pane {{
        border: 1px solid {COLORS['border_subtle']};
        border-radius: 10px;
        background: {COLORS['bg_panel']};
    }}

    QGroupBox {{
        background: {COLORS['bg_panel']};
        border: 1px solid {COLORS['border_subtle']};
        border-radius: {card_radius};
        margin-top: {px(8)};
        padding: {px(8)} {px(8)} {px(8)} {px(8)};
    }}

    QGroupBox#card-config, QGroupBox#card-basic {{
        background: {COLORS['bg_panel']};
        border: 1px solid {COLORS['border_subtle']};
        border-radius: {card_radius_lg};
        padding: {px(8)} {px(8)} {px(8)} {px(8)};
        background-clip: border;
    }}

    QGroupBox#card-inner {{
        background: {COLORS['bg_panel']};
        border: 1px solid {COLORS['border_subtle']};
        border-radius: 10px;
        padding: 8px 8px 6px 8px;
        margin-top: 6px;
        background-clip: border;
    }}

    /* 确保表单行背景与卡片一致，不出现条块 */
    QGroupBox#card-config QWidget, QGroupBox#card-inner QWidget, QGroupBox#card-basic QWidget {{
        background: {COLORS['bg_panel']};
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
        font-size: {font_group};
        font-weight: 700;
        color: {COLORS['text_primary']};
    }}

    QLabel {{
        color: {COLORS['text_primary']};
        background: transparent;
    }}

    QLabel[badge="success"] {{
        background: {COLORS['success']};
        color: white;
        padding: {px(2)} {px(8)};
        border-radius: {px(6)};
        font-size: {font_badge};
        font-weight: 700;
    }}

    QLabel[badge="warn"] {{
        background: {COLORS['warning']};
        color: white;
        padding: {px(2)} {px(8)};
        border-radius: {px(6)};
        font-size: {font_badge};
        font-weight: 700;
    }}

    QLabel[hint="muted"] {{
        color: {COLORS['text_muted']};
        font-size: 13px;
    }}

    QLineEdit, QComboBox, QTextEdit {{
        border: 1px solid {COLORS['border_subtle']};
        border-radius: 8px;
        border-radius: {px(8)};
        padding: {input_pad_v} {input_pad_h};
        padding-right: {input_pad_right}; /* 为箭头预留空间 */
        background-color: {COLORS['bg_panel']};
        selection-background-color: {COLORS['accent']};
        selection-color: white;
        min-height: {px(36)};
    }}

    QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
        border: 1px solid {COLORS['accent']};
        outline: 2px solid rgba(47, 125, 225, 0.3);
        outline-offset: 1px;
    }}

    QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled {{
        color: rgba(28, 36, 48, 0.6);
        background: #f1f2f5;
    }}

    /* 使用默认箭头以避免自绘异常 */
    /* 下拉按钮与箭头（SVG 确保跨平台一致） */
    QComboBox::drop-down {{
        border: none;
        width: {px(30)};
        subcontrol-origin: padding;
        subcontrol-position: right center;
        padding-right: {px(6)};
    }}

    QComboBox::down-arrow {{
		background-color: {COLORS['bg_panel']};
        padding-right: {px(8)};
        width: {px(12)};
        height: {px(12)};
    }}

    QComboBox QAbstractItemView {{
        background-color: {COLORS['bg_panel']};
        border: 1px solid {COLORS['border_subtle']};
        selection-background-color: rgba(47, 125, 225, 0.12);
        selection-color: {COLORS['text_primary']};
    }}

    QPushButton {{
        min-height: {btn_height};
        border-radius: {btn_radius};
        padding: 0 {px(10)};
        font-weight: 600;
        border: 1px solid {COLORS['border_subtle']};
        background: transparent;
        color: {COLORS['text_primary']};
    }}

    QPushButton:hover {{
        background: rgba(47, 125, 225, 0.08);
    }}

    QPushButton[variant="primary"] {{
        background: {COLORS['accent']};
        color: white;
        border: 1px solid {COLORS['accent']};
    }}

    QPushButton[variant="primary"]:hover {{
        background: #2b6fca;
    }}

    QPushButton[variant="secondary"] {{
        background: rgba(47, 125, 225, 0.06);
        color: {COLORS['accent']};
        border: 1px solid {COLORS['border_subtle']};
    }}

    QPushButton[variant="secondary"]:hover {{
        background: rgba(47, 125, 225, 0.12);
    }}

    QPushButton[variant="ghost"] {{
        background: transparent;
        color: {COLORS['accent']};
        border: 1px dashed {COLORS['border_subtle']};
    }}

    QPushButton[variant="ghost"]:hover {{
        background: rgba(47, 125, 225, 0.08);
    }}

    QPushButton[variant="danger"] {{
        background: {COLORS['warning']};
        color: white;
        border: 1px solid {COLORS['warning']};
    }}

    QPushButton[variant="danger"]:hover {{
        background: #a63636;
    }}

    QTreeWidget, QListWidget {{
        background: {COLORS['bg_panel']};
        border: 1px solid {COLORS['border_subtle']};
        border-radius: {card_radius};
        padding: {px(8)};
    }}

    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: {scroll_width};
        margin: {scroll_margin};
    }}

    QScrollBar::handle:vertical {{
        background: #c3c8d3;
        border-radius: {scroll_handle_radius};
        min-height: {scroll_handle_min};
    }}

    QScrollBar::handle:vertical:hover {{
        background: #aeb6c6;
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    /* 横向滚动条与纵向保持一致的外观，避免出现突兀的黑线 */
    QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: {scroll_width};
        margin: {scroll_margin};
    }}

    QScrollBar::handle:horizontal {{
        background: #c3c8d3;
        border-radius: {scroll_handle_radius};
        min-width: {scroll_handle_min};
    }}

    QScrollBar::handle:horizontal:hover {{
        background: #aeb6c6;
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    QToolTip {{
        border: 1px solid {COLORS['border_subtle']};
        background-color: {COLORS['bg_panel']};
        color: {COLORS['text_primary']};
        font-size: {px(round(15 * scale * 0.7))}; /* 相比基础字体小 30% */
        padding: 4px;
        border-radius: 4px;
    }}
    """


def apply_global_style(app: QApplication) -> None:
    """应用全局字体和样式，按屏幕 DPI 进行缩放。"""
    screen = app.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen else 96.0
    scale = dpi / 96.0
    scale = max(0.9, min(1.3, scale))  # 避免过度放大/缩小

    app.setFont(QFont("Source Sans 3", max(10, round(15 * scale))))
    app.setStyleSheet(build_stylesheet(scale))


def apply_card_shadow(widget: QWidget) -> None:
    """为卡片式控件增加轻微阴影。"""
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(12)
    effect.setOffset(0, 4)
    effect.setColor(QColor(0, 0, 0, 30))
    widget.setGraphicsEffect(effect)
