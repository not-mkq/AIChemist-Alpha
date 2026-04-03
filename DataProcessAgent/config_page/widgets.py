#!/usr/bin/env python3
"""
widgets.py

自定义 PyQt6 组件：
- NoWheelComboBox：禁用滚轮切换
- ListValueEditor：为单值字段提供列表输入能力
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Callable, List, Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QTextEdit,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QCompleter,
    QSizePolicy,
)

from i18n import tr


class AutoResizingTextEdit(QTextEdit):
    """
    自动调整高度的文本输入框。
    默认表现类似 QLineEdit（单行），但内容增多时自动增高。
    """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # 初始高度设置（约等于 QLineEdit）
        self.min_height = 30 
        self.max_height = 200 # 限制最大高度，避免无限增长
        self.setFixedHeight(self.min_height)
        
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self):
        doc_height = self.document().size().height()
        # 增加一点 buffer，避免刚好够高时出现滚动条闪烁
        new_height = int(doc_height + 10) 
        
        if new_height < self.min_height:
            new_height = self.min_height
        elif new_height > self.max_height:
            new_height = self.max_height
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            
        if new_height != self.height():
            self.setFixedHeight(new_height)
            self.updateGeometry()

    def keyPressEvent(self, event):
        # 处理 Tab 键：切换焦点而不是插入制表符
        if event.key() == Qt.Key.Key_Tab:
            self.focusNextChild()
        elif event.key() == Qt.Key.Key_Backtab:
            self.focusPreviousChild()
        # Shift+Enter 或 Enter 都允许换行，保持默认行为即可
        # 或者为了类似 LineEdit，Enter 触发提交？
        # 用户需求是 "输入大量文本...折行显示"，所以允许 Enter 换行是合理的，
        # 但在表单中通常 Enter 可能会提交表单。
        # 鉴于这是 "大量文本" 场景，保留 Enter 换行比较好。
        else:
            super().keyPressEvent(event)

    def text(self) -> str:
        """兼容 QLineEdit 接口"""
        return self.toPlainText()

    def setText(self, text: str):
        """兼容 QLineEdit 接口"""
        self.setPlainText(text)
        self._adjust_height()  # 设置初始文本时调整高度

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_height()


class NoWheelComboBox(QComboBox):
    """禁用滚轮切换的 ComboBox"""

    def __init__(self, parent: Optional[QWidget] = None, searchable: bool = False) -> None:
        super().__init__(parent)
        # 限制最大可见项数，防止向上弹出时遮挡顶部
        self.setMaxVisibleItems(15)
        # 确保弹出视图有正确的滚动条策略，避免在某些平台上显示异常
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        if searchable:
            self.setEditable(True)
            self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            # 配置搜索匹配模式为包含匹配
            if self.completer():
                self.completer().setFilterMode(Qt.MatchFlag.MatchContains)
                self.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """重写滚轮事件，禁用滚轮切换选项"""
        event.ignore()


@dataclass
class _ListRow:
    container: QWidget
    layout: QHBoxLayout
    widget: QWidget
    button: QPushButton
    comment_edit: Optional[QLineEdit] = None
    label_widget: Optional[QLabel] = None


class ListValueEditor(QWidget):
    """
    包装基础控件，提供“单值/多值”两种编辑模式。
    - 第一行右侧提供 “+” 按钮添加行
    - 非首行提供 “-” 按钮删除对应行
    - 通过 value_getter/value_setter 在外部完成取值与赋值
    """

    value_changed = pyqtSignal()

    def __init__(
        self,
        widget_factory: Callable[[], QWidget],
        value_getter: Callable[[QWidget], Optional[object]],
        value_setter: Callable[[QWidget, Optional[object]], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.widget_factory = widget_factory
        self.value_getter = value_getter
        self.value_setter = value_setter
        self.rows: List[_ListRow] = []
        self._suspend_signal = False
        self._comments_enabled = False
        self._comment_placeholder = tr("field_comment_placeholder")
        self._comment_tooltip: Optional[str] = None
        self._row_ops_enabled = True
        self._row_label_texts: List[Optional[str]] = []
        self._row_labels_enabled = False
        self._row_visibility: List[bool] = []

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(4)
        self._add_row(is_first=True)

    # ----- 行管理 -----
    def _add_row(
        self,
        *,
        is_first: bool = False,
        value: Optional[object] = None,
    ) -> None:
        container = QWidget()
        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        widget = self.widget_factory()
        self._attach_signal(widget)
        row_layout.addWidget(widget, stretch=1)

        if is_first:
            button = QPushButton("+")
            button.setFixedWidth(28)
            button.clicked.connect(lambda: self._add_row(is_first=False))
        else:
            button = QPushButton("-")
            button.setFixedWidth(28)
            button.clicked.connect(partial(self._remove_row, container))

        row_layout.addWidget(button)
        row = _ListRow(container=container, layout=row_layout, widget=widget, button=button)
        self.rows.append(row)
        self.layout.addWidget(container)
        self._row_visibility.append(True)

        if self._comments_enabled:
            self._attach_comment_edit(row)

        if value is not None:
            self.value_setter(widget, value)

        self._apply_row_control_state(row)
        self._apply_row_label(row, len(self.rows) - 1)
        self._emit_change()

    def _remove_row(self, target_container: QWidget) -> None:
        if len(self.rows) <= 1:
            return
        target = next((row for row in self.rows if row.container is target_container), None)
        if not target:
            return

        idx = self.rows.index(target)
        self.rows.remove(target)
        widget = target.widget
        button = target.button

        widget.deleteLater()
        button.deleteLater()
        target.container.setParent(None)
        target.container.deleteLater()
        if 0 <= idx < len(self._row_visibility):
            self._row_visibility.pop(idx)
        self._refresh_row_labels()
        self._emit_change()

    def _ensure_row_count(self, count: int) -> None:
        if count <= 0:
            count = 1
        while len(self.rows) < count:
            self._add_row(is_first=False)
        while len(self.rows) > count:
            # remove from tail
            container = self.rows[-1].container
            self._remove_row(container)
        self._refresh_row_labels()

    def _apply_row_control_state(self, row: _ListRow) -> None:
        if not row or not row.button:
            return
        row.button.setVisible(self._row_ops_enabled)
        row.button.setEnabled(self._row_ops_enabled)

    def _ensure_row_label_widget(self, row: _ListRow) -> None:
        if row.label_widget is not None:
            return
        label = QLabel()
        label.setProperty("muted", True)
        label.setContentsMargins(0, 0, 0, 0)
        # 与 ToolConfigWidget._field_label 保持一致的对齐样式
        label.setMinimumWidth(140)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.layout.insertWidget(0, label)
        row.label_widget = label

    def _apply_row_label(self, row: _ListRow, index: int) -> None:
        texts = self._row_label_texts if self._row_labels_enabled else []
        if not texts:
            if row.label_widget:
                row.label_widget.hide()
            return
        text = texts[index] if index < len(texts) else texts[-1]
        if text in {None, ""}:
            if row.label_widget:
                row.label_widget.hide()
            return
        self._ensure_row_label_widget(row)
        row.label_widget.setText(str(text))
        row.label_widget.show()

    def _refresh_row_labels(self) -> None:
        for idx, row in enumerate(self.rows):
            self._apply_row_label(row, idx)

    def _attach_comment_edit(self, row: _ListRow) -> None:
        if row.comment_edit is not None:
            return
        comment_edit = QLineEdit()
        comment_edit.setPlaceholderText(self._comment_placeholder)
        if self._comment_tooltip:
            comment_edit.setToolTip(self._comment_tooltip)
        comment_edit.textChanged.connect(self._emit_change)
        # 插入在按钮之前
        insert_pos = max(row.layout.count() - 1, 1)
        row.layout.insertWidget(insert_pos, comment_edit, 1)
        row.comment_edit = comment_edit

    def set_comment_tooltip(self, tooltip: Optional[str]) -> None:
        """设置行内注释输入框的工具提示。"""
        self._comment_tooltip = tooltip
        for row in self.rows:
            if row.comment_edit:
                row.comment_edit.setToolTip(tooltip or "")

    def enable_comments(
        self,
        comments: Optional[Sequence[Optional[object]]] = None,
        placeholder: Optional[str] = None,
    ) -> None:
        """开启行内注释输入，并可选恢复历史注释。"""
        if placeholder:
            self._comment_placeholder = placeholder
        if self._comments_enabled and comments is None:
            return
        self._comments_enabled = True
        for row in self.rows:
            self._attach_comment_edit(row)
        if comments is not None:
            self.set_comment_values(comments)

    def set_comment_values(self, comments: Optional[Sequence[Optional[object]]]) -> None:
        if not self._comments_enabled:
            return
        normalized = self._normalize_comment_entries(comments)
        self._suspend_signal = True
        try:
            for idx, row in enumerate(self.rows):
                text = normalized[idx] if idx < len(normalized) else ""
                if row.comment_edit:
                    row.comment_edit.setText("" if text in {None, ""} else str(text))
        finally:
            self._suspend_signal = False
        self._emit_change()

    def set_row_operations_enabled(self, enabled: bool) -> None:
        self._row_ops_enabled = enabled
        for row in self.rows:
            self._apply_row_control_state(row)

    def set_row_visibility(self, visible_flags: Sequence[bool]) -> None:
        flags = [bool(flag) for flag in visible_flags]
        if not flags:
            flags = [True] * len(self.rows)
        if len(flags) < len(self.rows):
            flags.extend([True] * (len(self.rows) - len(flags)))
        elif len(flags) > len(self.rows):
            flags = flags[: len(self.rows)]
        self._row_visibility = flags
        for idx, row in enumerate(self.rows):
            row.container.setVisible(self._row_visibility[idx])

    def set_row_labels(self, labels: Optional[Sequence[Optional[str]]]) -> None:
        if labels is None:
            self._row_label_texts = []
            self._row_labels_enabled = False
        else:
            normalized: List[Optional[str]] = []
            for entry in labels:
                if entry is None:
                    normalized.append(None)
                else:
                    text = str(entry).strip()
                    normalized.append(text if text else None)
            self._row_label_texts = normalized
            self._row_labels_enabled = any(text is not None for text in normalized)
        self._refresh_row_labels()

    def get_comment_values(self) -> List[Optional[str]]:
        if not self._comments_enabled:
            return []
        values: List[Optional[str]] = []
        for row in self.rows:
            if row.comment_edit is None:
                values.append(None)
                continue
            text = row.comment_edit.text().strip()
            values.append(text or None)
        return values

    def get_comment_widgets(self) -> List[QLineEdit]:
        if not self._comments_enabled:
            return []
        return [row.comment_edit for row in self.rows if row.comment_edit is not None]

    def get_row_visibility(self) -> List[bool]:
        if self._row_visibility:
            return list(self._row_visibility)
        return [True] * len(self.rows)
        return [True] * len(self.rows)

    @staticmethod
    def _normalize_comment_entries(comments: Optional[Sequence[Optional[object]]]) -> List[Optional[object]]:
        if comments is None:
            return []
        if isinstance(comments, (list, tuple)):
            return list(comments)
        return [comments]

    # ----- 信号与值 -----
    def _attach_signal(self, widget: QWidget) -> None:
        if hasattr(widget, "textChanged"):
            widget.textChanged.connect(self._emit_change)
        if hasattr(widget, "currentIndexChanged"):
            widget.currentIndexChanged.connect(self._emit_change)
        if hasattr(widget, "currentTextChanged"):
            widget.currentTextChanged.connect(self._emit_change)

    def _emit_change(self) -> None:
        if self._suspend_signal:
            return
        self.value_changed.emit()

    # ----- 对外接口 -----
    def set_value(self, value: Optional[object]) -> None:
        """
        value 可以是：None / 标量 / list
        """
        if isinstance(value, list):
            values = value
        else:
            values = [value]
        if not values:
            values = [None]

        self._suspend_signal = True
        try:
            self.blockSignals(True)
            self._ensure_row_count(len(values))
            for row, val in zip(self.rows, values):
                self.value_setter(row.widget, val)
        finally:
            self.blockSignals(False)
            self._suspend_signal = False
        self._emit_change()

    def set_scalar_value(self, value: Optional[object]) -> None:
        self._suspend_signal = True
        try:
            self._ensure_row_count(1)
            self.value_setter(self.rows[0].widget, value)
        finally:
            self._suspend_signal = False
        self._emit_change()

    def get_all_values(self) -> List[Optional[object]]:
        return [self.value_getter(row.widget) for row in self.rows]

    def is_list_mode(self) -> bool:
        return len(self.rows) > 1

    def has_any_value(self) -> bool:
        return any(v not in {None, ""} for v in self.get_all_values())

    def first_widget(self) -> Optional[QWidget]:
        return self.rows[0].widget if self.rows else None

    def __getattr__(self, item: str):
        """
        为兼容旧逻辑，将未知属性代理到首个子控件。
        仅当前缀为 __ 时抛出 AttributeError，避免影响内部机制。
        """
        if item.startswith("__"):
            raise AttributeError(item)
        widget = self.first_widget()
        if widget and hasattr(widget, item):
            return getattr(widget, item)
        raise AttributeError(item)
