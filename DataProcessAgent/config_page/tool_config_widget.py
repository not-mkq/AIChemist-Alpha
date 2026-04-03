#!/usr/bin/env python3
"""
tool_config_widget.py

工具实例配置表单组件：
- 左侧基础信息（实例名、工具类型、代码）
- 中部根据模板动态生成配置表单
- 底部操作按钮（保存/重置/删除/导出）

主要约定：
- file_label 参数用于“输入标签映射”；input_cols 参数用于“结果列输入映射”；result_col 字段用于“输出结果列名”。
- 新建时右侧注释面板显示代码注释；编辑时显示实例注释（在外部回调中处理）。
"""

from __future__ import annotations

import logging
import copy
from typing import Any, Dict, List, Optional, Set, Union, Tuple

from pathlib import Path
import re
import requests
try:
    import markdown
except ImportError:
    markdown = None
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from i18n import tr

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QFrame,
    QStyle,
)
try:
    from widgets import ListValueEditor, NoWheelComboBox
except ImportError:
    from .widgets import ListValueEditor, NoWheelComboBox

try:
    from api_client import ApiClient
    from ui_theme import apply_card_shadow
    from param_strategies import ParamEditorFactory
    from form_builder import FormRowBuilder
except ImportError:
    from .api_client import ApiClient
    from .ui_theme import apply_card_shadow

try:
    from param_value_utils import (
        extract_wrapped_mapping,
        extract_wrapped_value,
        rebuild_wrapped_mapping,
        rebuild_wrapped_value,
    )
except ImportError:
    # 这一块可能需要维持 ROOT 查找，因为 param_value_utils 在根目录
    import sys
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from param_value_utils import (
        extract_wrapped_mapping,
        extract_wrapped_value,
        rebuild_wrapped_value,
    )


# 宽松的默认规则：仅要求非空
TEXT_RULE_RE = re.compile(r".+")
TEXT_RULE_HINT = "不能为空"


logger = logging.getLogger(__name__)


class ToolConfigWidget(QWidget):
    """工具配置表单"""

    code_changed = pyqtSignal(str, str)  # (tool_type, code_name)
    form_changed = pyqtSignal()  # 任意表单字段变化

    def __init__(
        self,
        api_client: ApiClient,
        get_comment_callback=lambda: "",
        on_save_success_callback=None,
        parent=None,
        enable_comments: bool = True,
        hidden_sections: Optional[Set[str]] = None,
        label_from_comment: bool = False,
        lock_list_row_controls: bool = False,
        compact_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.get_comment_callback = get_comment_callback
        self.on_save_success_callback = on_save_success_callback
        self.tool_instance_tab = None  # 保存对 ToolInstanceConfigTab 的引用，用于获取 current_directory
        self.enable_comments = enable_comments
        self.hidden_sections: Set[str] = set(hidden_sections or [])
        self.label_from_comment = label_from_comment
        self.lock_list_row_controls = lock_list_row_controls
        self.compact_mode = compact_mode

        self.is_new_tool = True
        self.current_instance_name: Optional[str] = None
        self.labels_cache: List[str] = []
        self.tool_codes_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.result_cols_cache: Dict[str, List[str]] = {}
        self._suppress_form_signal: bool = False
        self.current_template: Optional[Dict[str, Any]] = None
        self.current_param_types: Dict[str, str] = {}
        self.current_param_choices: Dict[str, List[Any]] = {}
        # 保存状态标签用于工具实例配置；项目配置可隐藏
        self.save_status_label: Optional[QLabel] = None

        self.config_widgets: Dict[str, Any] = {}
        self.comment_widgets: Dict[str, Dict[Optional[str], Union[QLineEdit, ListValueEditor]]] = {}
        self._reset_instance_param_meta()

        self._setup_ui()
        self._load_tool_codes("single")
        self._load_result_columns()
        self.update_config_form()

    def _markdown_to_html(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        # 如果 markdown 库未安装，则进行基础的转义和换行处理
        if markdown is None:
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            formatted = escaped.replace("\n", "<br>")
            return f"<div style='min-width: 250px; max-width: 600px; padding: 4px;'>{formatted}</div>"

        # 将 Markdown 转换为 HTML，并包裹在 div 中以控制样式
        try:
            html = markdown.markdown(text, extensions=['extra', 'nl2br'])
            return f"<div style='min-width: 250px; max-width: 600px; padding: 4px;'>{html}</div>"
        except Exception:
            return text

    # ---------- UI ----------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        if self.compact_mode:
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(4)
        else:
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(8)

        if not self.compact_mode:
            header_layout = QHBoxLayout()
            header_label = QLabel(tr("tool_config"))
            header_label.setFont(QFont("Source Sans 3", 18, QFont.Weight.Bold))
            self.save_status_label = QLabel(tr("saved"))
            self.save_status_label.setProperty("badge", "success")
            header_layout.addWidget(header_label)
            header_layout.addWidget(self.save_status_label)
            header_layout.addStretch()
            layout.addLayout(header_layout)

            divider = QFrame()
            divider.setFrameShape(QFrame.Shape.HLine)
            divider.setStyleSheet("color: #d7dbe3;")
            layout.addWidget(divider)
        else:
            self.save_status_label = None

        # 基本信息面板（可在运行工具页面隐藏，但在工具实例配置页面显示）
        self.basic_group = self._create_group_box(tr("basic_info"), "card-basic")
        basic_form = QFormLayout()
        basic_form.setSpacing(10)
        
        self.instance_name_edit = QLineEdit()
        self.instance_name_edit.setPlaceholderText(tr("instance_name_placeholder"))
        self.instance_name_edit.setAccessibleName(tr("instance_name"))
        self.instance_name_edit.textChanged.connect(self.mark_unsaved)
        basic_form.addRow(tr("instance_name"), self.instance_name_edit)
        
        self.tool_type_combo = NoWheelComboBox()
        self.tool_type_combo.addItems(["single", "merge", "meta"])
        self.tool_type_combo.setAccessibleName(tr("tool_type"))
        self.tool_type_combo.currentTextChanged.connect(self.on_tool_type_changed)
        basic_form.addRow(tr("tool_type"), self.tool_type_combo)
        
        self.code_name_combo = NoWheelComboBox()
        self.code_name_combo.setAccessibleName(tr("tool_code"))
        self.code_name_combo.currentTextChanged.connect(self.on_code_changed)
        basic_form.addRow(tr("tool_code"), self.code_name_combo)


        self.basic_group.setLayout(basic_form)
        if not self.compact_mode:
            apply_card_shadow(self.basic_group)
        layout.addWidget(self.basic_group)

        # 配置项
        self.config_group = self._create_group_box(tr("config_items"), "card-config")
        self.config_layout = QVBoxLayout()
        self.config_layout.setSpacing(0)
        self.config_layout.setContentsMargins(0, 0, 0, 0)
        self.config_group.setLayout(self.config_layout)
        if not self.compact_mode:
            apply_card_shadow(self.config_group)
        layout.addWidget(self.config_group, stretch=1)

        # 操作按钮
        if not self.compact_mode:
            btn_row = QHBoxLayout()
            self.save_btn = QPushButton(tr("btn_save"))
            self.save_btn.setProperty("variant", "primary")
            self.save_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
            self.save_btn.clicked.connect(self.save_config)
            
            self.reset_btn = QPushButton(tr("btn_reset"))
            self.reset_btn.setProperty("variant", "secondary")
            self.reset_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            self.reset_btn.clicked.connect(self.reset_form)

            self.delete_btn = QPushButton(tr("btn_delete"))
            self.delete_btn.setProperty("variant", "danger") # 样式提示这是一个危险操作
            self.delete_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
            self.delete_btn.clicked.connect(self.delete_config)

            for btn in [self.save_btn, self.reset_btn, self.delete_btn]:
                btn_row.addWidget(btn)

            btn_row.addStretch()
            layout.addLayout(btn_row)
        else:
            self.save_btn = None
            self.reset_btn = None

        self.setLayout(layout)
        self.form_changed.connect(self.mark_unsaved)

    def _create_group_box(self, title: str, object_name: str) -> QWidget:
        """Create a group container; compact mode uses a plain QWidget."""
        if self.compact_mode:
            box = QWidget()
            box.setObjectName(object_name)
            return box
        box = QGroupBox(title)
        box.setObjectName(object_name)
        return box

    # ---------- 数据加载 ----------
    def _load_tool_codes(self, tool_type: str, force: bool = False) -> None:
        """加载代码列表，force=True 时强制刷新缓存"""
        try:
            if force or not self.tool_codes_cache:
                self.tool_codes_cache = self.api_client.get_tool_codes()
        except Exception as e:
            logger.error(f"加载工具代码失败: {e}")
            QMessageBox.warning(self, "错误", f"加载工具代码失败: {e}\n\n请先调用 /load-metadata")
            self.code_name_combo.clear()
            return

        # 保存当前选中的代码名，以便重新加载后恢复
        current_code_name = self.code_name_combo.currentText()
        
        self.code_name_combo.blockSignals(True)
        self.code_name_combo.clear()

        if tool_type == "single":
            codes = self.tool_codes_cache.get("single", [])
        elif tool_type == "merge":
            codes = self.tool_codes_cache.get("merge", [])
        else:
            codes = self.tool_codes_cache.get("meta") or [
                {"code_name": "map", "comment": "Map 模式 (meta)"},
                {"code_name": "sequence", "comment": "Sequence 模式 (meta)"},
                {"code_name": "alt", "comment": "Alt 模式 (meta)"},
            ]

        for item in codes:
            name = item.get("code_name", "") if isinstance(item, dict) else str(item)
            comment = item.get("comment", "") if isinstance(item, dict) else ""
            if not name:
                continue
            self.code_name_combo.addItem(name)
            index = self.code_name_combo.findText(name)
            if index >= 0 and comment:
                self.code_name_combo.setItemData(index, comment, Qt.ItemDataRole.ToolTipRole)

        # 恢复之前选中的代码名（如果存在且匹配）
        if current_code_name:
            idx = self.code_name_combo.findText(current_code_name)
            if idx >= 0:
                self.code_name_combo.setCurrentIndex(idx)

        self.code_name_combo.blockSignals(False)

    def refresh_tool_codes(self) -> None:
        """外部调用：清空缓存并按当前类型重载代码列表"""
        # 保存当前选中的代码名，以便重新加载后恢复
        current_code_name = self.code_name_combo.currentText()
        current_tool_type = self.tool_type_combo.currentText()
        
        self.tool_codes_cache = {}
        self._load_tool_codes(current_tool_type, force=True)
        
        # 恢复之前选中的代码名
        if current_code_name:
            idx = self.code_name_combo.findText(current_code_name)
            if idx >= 0:
                self.code_name_combo.setCurrentIndex(idx)

    def _load_result_columns(self) -> None:
        """加载结果列列表用于 from_result / input_cols 选择"""
        try:
            self.result_cols_cache = self.api_client.get_result_columns() or {}
        except Exception as e:
            logger.warning(f"加载结果列失败: {e}")
            self.result_cols_cache = {}

    def refresh_labels(self) -> None:
        """外部调用：清空标签缓存，下一次加载表单会重新请求 /labels"""
        self.labels_cache = []

    def _load_labels(self) -> List[str]:
        if self.labels_cache:
            return self.labels_cache
        try:
            data = self.api_client.get_labels()
            labels = set()
            labels.update((data.get("regex") or {}).keys())
            labels.update((data.get("wildcard") or {}).keys())
            self.labels_cache = sorted(labels)
        except Exception as e:
            logger.error(f"加载标签失败: {e}")
            QMessageBox.warning(self, "错误", f"加载标签失败: {e}")
            self.labels_cache = []
        return self.labels_cache

    def _load_all_tools(self) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
        """加载profile内的全部工具（不限制目录），用于meta工具的工具选择"""
        try:
            # 不传递directory参数，返回profile内的所有工具
            data = self.api_client.get_tools(directory=None)
            tools_list: List[Dict[str, str]] = []
            tools_map: Dict[str, str] = {}
            
            def add_group(type_label: str, json_key: str):
                names = data.get(json_key, [])
                for name in names:
                    display = f"[{type_label}] {name}"
                    item = {"name": name, "display": display}
                    tools_list.append(item)
                    tools_map[name] = display

            add_group("Single", "tools")
            add_group("Merge", "merge_tools")
            add_group("Meta", "meta_tools")
            
            return tools_list, tools_map
        except Exception as e:
            logger.error(f"加载工具列表失败: {e}")
            QMessageBox.warning(self, "错误", f"加载工具列表失败: {e}")
            return [], {}

    # ---------- 事件处理 ----------
    def on_tool_type_changed(self, tool_type: str) -> None:
        self._load_tool_codes(tool_type)
        self.update_config_form()

    def on_code_changed(self, code_name: str) -> None:
        self.update_config_form()
        self.code_changed.emit(self.tool_type_combo.currentText(), code_name)

    # ---------- 表单渲染 ----------
    def _clear_config_layout(self) -> None:
        while self.config_layout.count():
            item = self.config_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _emit_form_changed(self) -> None:
        if not self._suppress_form_signal:
            self.form_changed.emit()

    def update_config_form(self, config_data: Optional[Dict[str, Any]] = None):
        """更新配置表单（基于当前选中的代码）"""
        print(f"DEBUG: update_config_form called for code: {self.code_name_combo.currentText()}", flush=True)
        
        # 安全导入：防止顶层导入因路径问题失效
        try:
            from param_strategies import ParamEditorFactory
            from form_builder import FormRowBuilder
        except ImportError:
            try:
                from config_page.param_strategies import ParamEditorFactory
                from config_page.form_builder import FormRowBuilder
            except ImportError:
                logger.error("无法导入 ParamEditorFactory 或 FormRowBuilder，表单生成失败")
                return

        self._clear_config_layout()
        self.config_widgets = {}
        self._reset_instance_param_meta()
        self._reset_comment_widgets()
        self._suppress_form_signal = True

        tool_type = self.tool_type_combo.currentText()
        code_name = self.code_name_combo.currentText().strip()
        print(f"DEBUG: Processing code_name: '{code_name}'", flush=True)
        self.current_template = None
        self.current_param_types = {}
        self.current_param_choices = {}

        if tool_type == "meta":
            self._build_meta_form(config_data)
            self._suppress_form_signal = False
            self.mark_saved()
            return

        if not code_name:
            print("DEBUG: code_name is empty, aborting form build", flush=True)
            self._add_placeholder("请选择工具代码")
            self._suppress_form_signal = False
            self.mark_saved()
            return

        template = self.api_client.get_tool_code_params(code_name)
        print(f"DEBUG: Template fetched: {template.get('status') if template else 'None'}", flush=True)
        if not template or template.get("status") != "ok":
            self._add_placeholder("未找到模板，请先加载 /load-metadata")
            self._suppress_form_signal = False
            self.mark_saved()
            return

        self.current_template = template
        config_data = config_data or {}
        self._last_config_data = copy.deepcopy(config_data) if config_data else {}
        params = template.get("params", [])
        print(f"DEBUG: Params count: {len(params)}", flush=True)

        file_params = template.get("file_params", [])
        input_cols_def = template.get("input_cols", {}) # 获取 input_cols 定义

        # 提取初始值
        input_values, input_comments, input_wrapped = extract_wrapped_mapping(config_data.get("input_label_map"))
        cols_values, cols_comments, cols_wrapped = extract_wrapped_mapping(config_data.get("input_cols"))
        run_values, run_comments, run_wrapped = extract_wrapped_mapping(config_data.get("run_params"))
        output_value, output_comment, output_wrapped, output_has_value = extract_wrapped_value(config_data.get("output_file_label"))
        if not output_has_value:
            output_value = None
        result_value, result_comment, result_wrapped, result_has_value = extract_wrapped_value(config_data.get("result_col"))
        if not result_has_value:
            result_value = None
        pattern_value, pattern_comment, pattern_wrapped, pattern_has_value = extract_wrapped_value(config_data.get("output_pattern"))
        if not pattern_has_value:
            pattern_value = None

        # 初始化元数据
        self.instance_param_meta["input_label_map"] = {"comments": input_comments, "wrapped": input_wrapped}
        self.instance_param_meta["input_cols"] = {"comments": cols_comments, "wrapped": cols_wrapped}
        self.instance_param_meta["run_params"] = {"comments": run_comments, "wrapped": run_wrapped}
        self.instance_param_meta["output_file_label"] = {"comment": output_comment, "wrapped": output_wrapped}
        self.instance_param_meta["output_pattern"] = {"comment": pattern_comment, "wrapped": pattern_wrapped}
        self.instance_param_meta["result_col"] = {"comment": result_comment, "wrapped": result_wrapped}
        
        # 缓存参数类型
        param_types_map = {p.get("name"): p.get("type", "str") for p in params}
        self.current_param_types = {
            name: typ
            for name, typ in param_types_map.items()
            if name not in set(file_params) # input_cols 不在 params 里，所以不需要在这里排除
        }
        param_choices_map = {p.get("name"): p.get("choices") for p in params}
        self.current_param_choices = {
            name: choices if isinstance(choices, list) else []
            for name, choices in param_choices_map.items()
            if name not in set(file_params)
        }

        # 准备上下文数据
        labels = self._load_labels()
        context_data = {
            "result_cols_item": self.result_cols_cache.get("item", []),
            "result_cols_batch": self.result_cols_cache.get("batch", []),
            "result_cols_project": self.result_cols_cache.get("project", []),
            "labels": labels
        }
        
        builder = FormRowBuilder(self)
        form = QFormLayout()

        # 1. 输入标签映射 (input_label_map)
        input_widgets = {}
        if "input_label_map" not in self.hidden_sections:
            input_label_box = self._create_group_box("输入标签映射", "card-inner")
            input_label_form = QFormLayout()
            has_visible_inputs = False
            
            for p in params:
                name = p.get("name")
                if name not in file_params:
                    continue
                
                strategy = ParamEditorFactory.create_special(
                    "file_label", name, context_data, tooltip=p.get("comment")
                )
                
                row = builder.build(
                    section="input_label_map",
                    param_def=p,
                    initial_value=input_values.get(name),
                    param_strategy=strategy
                )
                
                input_widgets[name] = row.editor_widget
                if row.should_show:
                    has_visible_inputs = True
                    if row.span_row:
                        input_label_form.addRow(row.container_widget)
                    else:
                        input_label_form.addRow(row.label_widget, row.container_widget)
            
            if input_widgets:
                input_label_box.setLayout(input_label_form)
                if has_visible_inputs:
                    form.addRow(input_label_box)
                self.config_widgets["input_label_map"] = input_widgets

        # 2. 输入结果列映射 (input_cols) - Merge Only
        if tool_type == "merge" and input_cols_def:
            result_box = self._create_group_box("输入结果列 (input_cols)", "card-inner")
            result_form = QFormLayout()
            result_widgets = {}
            has_visible_cols = False
            
            # 直接遍历 input_cols_def 字典
            for name, meta in input_cols_def.items():
                comment = meta.get("comment") if isinstance(meta, dict) else str(meta)
                
                # 构造临时的 param_def
                p_def = {"name": name, "comment": comment}
                
                strategy = ParamEditorFactory.create_special(
                    "input_col", name, context_data, tooltip=comment
                )
                
                row = builder.build(
                    section="input_cols",
                    param_def=p_def,
                    initial_value=cols_values.get(name),
                    param_strategy=strategy
                )
                
                result_widgets[name] = row.editor_widget
                if row.should_show:
                    if row.span_row:
                        result_form.addRow(row.container_widget)
                    else:
                        result_form.addRow(row.label_widget, row.container_widget)
                    has_visible_cols = True

            if result_widgets:
                result_box.setLayout(result_form)
                if has_visible_cols:
                    form.addRow(result_box)
                self.config_widgets["input_cols"] = result_widgets

        # 3. 运行参数 (run_params)
        run_widgets = {}
        
        for p in params:
            name = p.get("name")
            if name in file_params:
                continue
            # input_cols 不在 params 里，所以不需要在这里排除
            
            try:
                strategy = ParamEditorFactory.create(p, context_data)
                
                row = builder.build(
                    section="run_params",
                    param_def=p,
                    initial_value=run_values.get(name),
                    param_strategy=strategy
                )
                
                run_widgets[name] = row.editor_widget
                if row.should_show:
                    if row.span_row:
                        form.addRow(row.container_widget)
                    else:
                        form.addRow(row.label_widget, row.container_widget)
            except Exception as e:
                logger.error(f"构建参数编辑器失败 {name}: {e}", exc_info=True)
                continue

        self.config_widgets["run_params"] = run_widgets

        # 4. 输出文件标签 (output_file_label)
        if template.get("output_file_label") is not None and "output_file_label" not in self.hidden_sections:
            p_def = {"name": "output_file_label", "comment": template.get("output_file_label", {}).get("comment", "")}
            strategy = ParamEditorFactory.create_special(
                "file_label", "output_file_label", context_data, tooltip=p_def["comment"]
            )
            
            row = builder.build(
                section="output_file_label",
                param_def=p_def,
                initial_value=output_value,
                param_strategy=strategy
            )
            
            if row.should_show:
                if row.span_row:
                    form.addRow(row.container_widget)
                else:
                    form.addRow(row.label_widget, row.container_widget)
            self.config_widgets["output_file_label"] = row.editor_widget

        # 5. 输出文件名模板 (output_pattern)
        if template.get("output_pattern") is not None and "output_pattern" not in self.hidden_sections:
            p_def = {"name": "output_pattern", "comment": template.get("output_pattern", {}).get("comment", "")}
            strategy = ParamEditorFactory.create_special(
                "simple_str", "output_pattern", context_data, tooltip=p_def["comment"]
            )
            # output_pattern 可选
            strategy.is_optional = True
            
            row = builder.build(
                section="output_pattern",
                param_def=p_def,
                initial_value=pattern_value,
                param_strategy=strategy
            )
            
            if row.should_show:
                if row.span_row:
                    form.addRow(row.container_widget)
                else:
                    form.addRow(row.label_widget, row.container_widget)
            self.config_widgets["output_pattern"] = row.editor_widget

        # 6. 输出结果列名 (result_col)
        if template.get("result_col") is not None and "result_col" not in self.hidden_sections:
            p_def = {"name": "result_col", "comment": template.get("result_col", {}).get("comment", "")}
            strategy = ParamEditorFactory.create_special(
                "simple_str", "result_col", context_data, tooltip=p_def["comment"]
            )
            
            row = builder.build(
                section="result_col",
                param_def=p_def,
                initial_value=result_value,
                param_strategy=strategy
            )
            
            if row.should_show:
                if row.span_row:
                    form.addRow(row.container_widget)
                else:
                    form.addRow(row.label_widget, row.container_widget)
            self.config_widgets["result_col"] = row.editor_widget

        wrapper = QWidget(self)
        wrapper.setObjectName("active_config_wrapper")
        wrapper.setLayout(form)
        self.config_layout.addWidget(wrapper)
        
        # 显式显示 wrapper 并刷新布局
        wrapper.show()
        
        # 强制触发布局重新计算
        self.config_layout.activate()
        wrapper.adjustSize()
        
        self._suppress_form_signal = False
        print("DEBUG: update_config_form completed successfully", flush=True)

    def _build_meta_form(self, config_data: Optional[Dict[str, Any]]) -> None:
        mode = self.code_name_combo.currentText() or (config_data or {}).get("mode", "map")
        self.code_name_combo.blockSignals(True)
        idx = self.code_name_combo.findText(mode)
        if idx >= 0:
            self.code_name_combo.setCurrentIndex(idx)
        self.code_name_combo.blockSignals(False)

        form = QFormLayout()

        tools_list, tools_map = self._load_all_tools()

        if mode == "sequence":
            seq_group = self._create_group_box("工具序列", "card-inner")
            seq_layout = QVBoxLayout()
            self.sequence_list = QListWidget()
            for name in (config_data or {}).get("tool_sequence", []):
                display_name = tools_map.get(name, name)
                self.sequence_list.addItem(QListWidgetItem(display_name))

            controls = QHBoxLayout()
            add_combo = NoWheelComboBox(self, searchable=True)
            add_combo.setObjectName("meta_add_combo")
            self.meta_add_combo = add_combo
            for item in tools_list:
                add_combo.addItem(item["display"], item["name"])

            def add_item():
                # add_combo.currentText() 是显示名 "[Type] Name"
                text = add_combo.currentText()
                if not text:
                    return
                self.sequence_list.addItem(QListWidgetItem(text))
                self._emit_form_changed()

            def remove_item():
                row = self.sequence_list.currentRow()
                if row >= 0:
                    self.sequence_list.takeItem(row)
                    self._emit_form_changed()

            def move(delta: int) -> None:
                row = self.sequence_list.currentRow()
                if row < 0:
                    return
                new_row = max(0, min(self.sequence_list.count() - 1, row + delta))
                if new_row == row:
                    return
                item = self.sequence_list.takeItem(row)
                self.sequence_list.insertItem(new_row, item)
                self.sequence_list.setCurrentRow(new_row)
                self._emit_form_changed()

            add_btn = QPushButton("添加")
            add_btn.clicked.connect(add_item)
            del_btn = QPushButton("删除")
            del_btn.clicked.connect(remove_item)
            up_btn = QPushButton("上移")
            up_btn.clicked.connect(lambda: move(-1))
            down_btn = QPushButton("下移")
            down_btn.clicked.connect(lambda: move(1))

            for w in [add_combo, add_btn, del_btn, up_btn, down_btn]:
                controls.addWidget(w)

            seq_layout.addLayout(controls)
            seq_layout.addWidget(self.sequence_list)
            seq_group.setLayout(seq_layout)
            form.addRow(seq_group)
            self.config_widgets["tool_sequence"] = self.sequence_list
        elif mode == "alt":
            alt_group = self._create_group_box("候选工具（按优先级）", "card-inner")
            alt_layout = QVBoxLayout()
            self.alt_list = QListWidget()
            for name in (config_data or {}).get("tool_alternatives", []):
                display_name = tools_map.get(name, name)
                self.alt_list.addItem(QListWidgetItem(display_name))

            controls = QHBoxLayout()
            add_combo = NoWheelComboBox(self, searchable=True)
            add_combo.setObjectName("meta_add_combo")
            self.meta_add_combo = add_combo
            for item in tools_list:
                add_combo.addItem(item["display"], item["name"])

            def add_alt():
                text = add_combo.currentText()
                if not text:
                    return
                self.alt_list.addItem(QListWidgetItem(text))
                self._emit_form_changed()

            def remove_alt():
                row = self.alt_list.currentRow()
                if row >= 0:
                    self.alt_list.takeItem(row)
                    self._emit_form_changed()

            def move_alt(delta: int) -> None:
                row = self.alt_list.currentRow()
                if row < 0:
                    return
                new_row = max(0, min(self.alt_list.count() - 1, row + delta))
                if new_row == row:
                    return
                item = self.alt_list.takeItem(row)
                self.alt_list.insertItem(new_row, item)
                self.alt_list.setCurrentRow(new_row)
                self._emit_form_changed()

            add_btn = QPushButton("添加")
            add_btn.clicked.connect(add_alt)
            del_btn = QPushButton("删除")
            del_btn.clicked.connect(remove_alt)
            up_btn = QPushButton("上移")
            up_btn.clicked.connect(lambda: move_alt(-1))
            down_btn = QPushButton("下移")
            down_btn.clicked.connect(lambda: move_alt(1))

            for w in [add_combo, add_btn, del_btn, up_btn, down_btn]:
                controls.addWidget(w)

            alt_layout.addLayout(controls)
            alt_layout.addWidget(self.alt_list)
            alt_group.setLayout(alt_layout)
            form.addRow(alt_group)
            self.config_widgets["tool_alternatives"] = self.alt_list
        else:
            tool_combo = NoWheelComboBox(searchable=True)
            for item in tools_list:
                tool_combo.addItem(item["display"], item["name"])
                
            preset = (config_data or {}).get("tool")
            if preset:
                idx = tool_combo.findData(preset)
                if idx >= 0:
                    tool_combo.setCurrentIndex(idx)
            tool_combo.setToolTip("Map 模式：选择要调用的工具实例")
            tool_combo.currentTextChanged.connect(self._emit_form_changed)
            form.addRow("调用的工具", tool_combo)
            self.config_widgets["tool"] = tool_combo

        wrapper = QWidget(self)
        wrapper.setObjectName("active_config_wrapper")
        wrapper.setLayout(form)
        self.config_layout.addWidget(wrapper)
        self._suppress_form_signal = False

    def _add_placeholder(self, text: str) -> None:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.config_layout.addWidget(label)

    # ---------- 对外操作 ----------
    def load_tool_instance(self, instance_name: str) -> None:
        """加载已有实例配置"""
        try:
            data = self.api_client.get_tool_instance(instance_name)
            if data.get("status") != "ok":
                raise RuntimeError(data)
            self.is_new_tool = False
            self.current_instance_name = instance_name

            self.instance_name_edit.setText(instance_name)
            self.instance_name_edit.setDisabled(True)

            tool_type = data.get("tool_type", "single")
            code_name = data.get("code_name") or ""
            config = data.get("config", {})

            # 切换类型并加载代码列表
            self.tool_type_combo.blockSignals(True)
            self.tool_type_combo.setCurrentText(tool_type)
            self._load_tool_codes(tool_type)
            self.tool_type_combo.blockSignals(False)

            # 设置代码下拉
            if tool_type == "meta" and config.get("code_name"):
                code_name = config.get("code_name")
            self.code_name_combo.blockSignals(True)
            idx = self.code_name_combo.findText(code_name)
            if idx >= 0:
                self.code_name_combo.setCurrentIndex(idx)
            self.code_name_combo.blockSignals(False)

            self.update_config_form(config_data=config)
            self.mark_saved()
        except Exception as e:
            logger.error(f"加载工具实例失败: {e}", exc_info=True)
            QMessageBox.warning(self, "错误", f"加载工具实例失败: {e}")

    def load_for_cloning(self, data: Dict[str, Any]) -> None:
        """基于已有配置加载，用于拷贝新建"""
        self.is_new_tool = True
        self.current_instance_name = None
        
        self.instance_name_edit.clear()
        self.instance_name_edit.setDisabled(False)
        self.instance_name_edit.setFocus()

        tool_type = data.get("tool_type", "single")
        code_name = data.get("code_name") or ""
        config = data.get("config", {})

        # 设置 UI 状态
        self.tool_type_combo.blockSignals(True)
        self.tool_type_combo.setCurrentText(tool_type)
        self._load_tool_codes(tool_type)
        self.tool_type_combo.blockSignals(False)

        if tool_type == "meta" and config.get("code_name"):
            code_name = config.get("code_name")
        self.code_name_combo.blockSignals(True)
        idx = self.code_name_combo.findText(code_name)
        if idx >= 0:
            self.code_name_combo.setCurrentIndex(idx)
        self.code_name_combo.blockSignals(False)

        self.update_config_form(config_data=config)
        self.mark_unsaved()

    def new_tool(self) -> None:
        """切换到新建模式"""
        self.is_new_tool = True
        self.current_instance_name = None
        self.instance_name_edit.setDisabled(False)
        self.instance_name_edit.clear()
        self.tool_type_combo.setCurrentText("single")
        self._load_tool_codes("single")
        if self.code_name_combo.count() > 0:
            self.code_name_combo.setCurrentIndex(0)
        self.update_config_form()
        self.mark_unsaved()

    def reset_form(self) -> None:
        if self.is_new_tool:
            self.new_tool()
        elif self.current_instance_name:
            self.load_tool_instance(self.current_instance_name)

    def delete_config(self) -> None:
        """删除当前工具实例（备份到 .backup）"""
        if self.is_new_tool or not self.current_instance_name:
            QMessageBox.information(self, "提示", "尚未选中任何已保存的工具。" )
            return

        reply = QMessageBox.warning(
            self,
            "确认删除",
            f"确定要删除工具实例 '{self.current_instance_name}' 吗？\n\n文件将被移动到项目根目录下的 .backup 文件夹中，您可以随时找回。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 调用后端删除接口
                self.api_client.delete_tool_instance(self.current_instance_name)
                QMessageBox.information(self, "成功", f"工具实例 '{self.current_instance_name}' 已删除（已备份）。")
                
                # 清空当前界面并切换到新建模式
                self.new_tool()
                
                # 调用回调刷新列表
                if self.on_save_success_callback:
                    self.on_save_success_callback()
            except Exception as e:
                logger.error(f"删除工具实例失败: {e}", exc_info=True)
                QMessageBox.critical(self, "错误", f"删除工具实例失败: {e}")

    # ---------- CRUD ----------
    def has_run_params(self) -> bool:
        """判断当前是否有配置参数 (run_params 或 input_cols)"""
        run_widgets = self.config_widgets.get("run_params")
        if run_widgets:
            return True
        input_cols_widgets = self.config_widgets.get("input_cols")
        if input_cols_widgets:
            return True
        return False

    def has_visible_run_params(self) -> bool:
        """判断当前是否有可见的配置参数（考虑 label_from_comment 设置）"""
        if not self.has_run_params():
            return False
        
        if not self.label_from_comment:
            return True
            
        # Check run_params
        run_widgets = self.config_widgets.get("run_params", {})
        for name in run_widgets.keys():
            existing_comment = self._instance_comment("run_params", name)
            if self._has_comment_value(existing_comment):
                return True
                
        # Check input_cols (Merge tools)
        cols_widgets = self.config_widgets.get("input_cols", {})
        for name in cols_widgets.keys():
            existing_comment = self._instance_comment("input_cols", name)
            if self._has_comment_value(existing_comment):
                return True
                
        return False

    def _extract_tool_name(self, text: str) -> str:
        """从显示文本 '[Type] Name' 中提取 'Name'"""
        if "] " in text:
            parts = text.split("] ", 1)
            if len(parts) == 2:
                return parts[1]
        return text

    def build_payload(self, require_instance: bool = True) -> Dict[str, Any]:
        tool_type = self.tool_type_combo.currentText()
        code_name = (
            self.code_name_combo.currentText().strip()
            if tool_type != "meta"
            else (self.code_name_combo.currentText().strip() or None)
        )
        config: Dict[str, Any] = {}

        if tool_type == "meta":
            mode = self.code_name_combo.currentText().strip() or "map"
            config["code_name"] = mode
            if mode == "map":
                tool_widget = self.config_widgets.get("tool")
                config["tool"] = self._widget_value(tool_widget) if tool_widget else ""
            elif mode == "sequence":
                seq_widget: QListWidget = self.config_widgets.get("tool_sequence")
                tool_sequence: List[str] = []
                if seq_widget:
                    for i in range(seq_widget.count()):
                        item = seq_widget.item(i)
                        if item and item.text():
                            tool_sequence.append(self._extract_tool_name(item.text()))
                config["tool_sequence"] = tool_sequence
            else:
                alt_widget: QListWidget = self.config_widgets.get("tool_alternatives")
                alt_tools: List[str] = []
                if alt_widget:
                    for i in range(alt_widget.count()):
                        item = alt_widget.item(i)
                        if item and item.text():
                            alt_tools.append(self._extract_tool_name(item.text()))
                config["tool_alternatives"] = alt_tools
            return {"tool_type": tool_type, "code_name": code_name, "config": config}

        # single / merge
        config["code_name"] = code_name

        # input_label_map
        input_widgets: Dict[str, ListValueEditor] = self.config_widgets.get("input_label_map", {})
        input_label_map: Dict[str, Any] = {}
        for name, widget in input_widgets.items():
            values, is_list = self._collect_editor_values(widget)
            normalized = [self._normalize_text_value(v) for v in values]
            if all(val == "" for val in normalized):
                continue
            if is_list:
                input_label_map[name] = normalized
            else:
                input_label_map[name] = normalized[0]
        if input_widgets:
            config["input_label_map"] = self._wrap_mapping_with_meta("input_label_map", input_label_map)
        elif "input_label_map" in self.hidden_sections and self._last_config_data.get("input_label_map") is not None:
            config["input_label_map"] = copy.deepcopy(self._last_config_data.get("input_label_map"))

        # input_cols (merge)
        if tool_type == "merge":
            result_widgets = self.config_widgets.get("input_cols", {})
            input_cols: Dict[str, str] = {}
            for name, widget in result_widgets.items():
                values, is_list = self._collect_editor_values(widget)
                # input_cols 应该总是单值 (column name)
                text = self._normalize_text_value(values[0] if values else None)
                if text:
                    input_cols[name] = text
            if result_widgets:
                config["input_cols"] = self._wrap_mapping_with_meta("input_cols", input_cols)
            elif self._last_config_data.get("input_cols") is not None:
                config["input_cols"] = copy.deepcopy(self._last_config_data.get("input_cols"))

        # run_params
        run_widgets: Dict[str, Any] = self.config_widgets.get("run_params", {})
        
        # 1. Start with existing values (unwrapped) to preserve hidden params
        # Note: extract_wrapped_mapping returns a fresh dict, safe to modify
        run_params, _, _ = extract_wrapped_mapping(self._last_config_data.get("run_params"))
        
        for name, widget in run_widgets.items():
            strategy = getattr(widget, "_strategy", None)
            if not strategy:
                continue

            values, is_list = self._collect_editor_values(widget)
            
            converted_entries: List[Any] = []
            
            expected_type = self.current_param_types.get(name)
            base_type, _ = self._normalize_type(expected_type)

            for raw_val in values:
                # 使用策略进行校验和转换
                # validate_single 返回 (ok, coerced_value, type)
                is_valid, coerced_val, _ = strategy.validate_single(raw_val)
                
                # 如果是可选且为空，validate_single 返回 (True, None, 'empty_optional')
                if coerced_val is None:
                    converted_entries.append(None)
                elif base_type == "from_result":
                    converted_entries.append({"from_result": coerced_val})
                else:
                    converted_entries.append(coerced_val)

            if not converted_entries:
                run_params.pop(name, None)
                continue

            if not is_list:
                value = converted_entries[0]
                if value is None:
                    run_params.pop(name, None)
                    continue
                run_params[name] = value
            else:
                run_params[name] = converted_entries
                
        config["run_params"] = self._wrap_mapping_with_meta("run_params", run_params)

        # output_file_label
        output_widget: Optional[ListValueEditor] = self.config_widgets.get("output_file_label")
        if output_widget:
            values, is_list = self._collect_editor_values(output_widget)
            normalized = [self._normalize_text_value(v) for v in values]
            has_value = any(val != "" for val in normalized)
            if has_value:
                value_obj: Any = normalized if is_list else normalized[0]
                config["output_file_label"] = self._wrap_single_with_meta(
                    "output_file_label", "output_file_label", value_obj
                )
        elif self._last_config_data.get("output_file_label") is not None:
            config["output_file_label"] = copy.deepcopy(self._last_config_data.get("output_file_label"))

        # output_pattern
        pattern_widget: Optional[ListValueEditor] = self.config_widgets.get("output_pattern")
        if pattern_widget:
            values, is_list = self._collect_editor_values(pattern_widget)
            normalized = [self._normalize_text_value(v) for v in values]
            has_value = any(val != "" for val in normalized)
            if has_value:
                value_obj = normalized if is_list else normalized[0]
                config["output_pattern"] = self._wrap_single_with_meta(
                    "output_pattern", "output_pattern", value_obj
                )
        elif self._last_config_data.get("output_pattern") is not None:
            config["output_pattern"] = copy.deepcopy(self._last_config_data.get("output_pattern"))

        # result_col (输出列)
        result_col_widget: Optional[ListValueEditor] = self.config_widgets.get("result_col")
        if result_col_widget:
            values, is_list = self._collect_editor_values(result_col_widget)
            normalized = [self._normalize_text_value(v) for v in values]
            has_value = any(val != "" for val in normalized)
            if has_value:
                value_obj = normalized if is_list else normalized[0]
                config["result_col"] = self._wrap_single_with_meta("result_col", "result_col", value_obj)
        elif self._last_config_data.get("result_col") is not None:
            config["result_col"] = copy.deepcopy(self._last_config_data.get("result_col"))

        return {"tool_type": tool_type, "code_name": code_name, "config": config}

    def validate_payload(self, payload: Dict[str, Any], require_instance: bool = True) -> Optional[str]:
        tool_type = payload.get("tool_type")
        code_name = payload.get("code_name")
        config = payload.get("config", {})

        if tool_type != "meta":
            if require_instance and not self.instance_name_edit.text().strip():
                return "实例名称不能为空"
            if require_instance and not self._is_valid_text(self.instance_name_edit.text().strip()):
                return f"实例名称仅允许{TEXT_RULE_HINT}"
            if not code_name:
                return "请选择工具代码"

        if tool_type == "merge":
            # input_cols 映射需要填写
            for name, widget in self.config_widgets.get("input_cols", {}).items():
                values, _ = self._collect_editor_values(widget)
                val = values[0] if values else None
                text = self._normalize_text_value(val)
                
                # Check optionality
                strategy = getattr(widget, "_strategy", None)
                is_optional = strategy.is_optional if strategy else False
                
                if not text:
                    if not is_optional:
                        return f"输入结果列缺失: {name}"
                    continue
                
                if not self._is_valid_text(text):
                    return f"输入结果列 {name} 仅允许{TEXT_RULE_HINT}"

        if tool_type == "meta":
            mode = config.get("code_name")
            if mode == "map" and not config.get("tool"):
                return "Map 模式需选择调用的工具"
            if mode == "sequence":
                seq = config.get("tool_sequence", [])
                if not seq:
                    return "Sequence 模式需至少一个工具"
            if mode == "alt":
                alts = config.get("tool_alternatives", [])
                if not alts:
                    return "Alt 模式需至少一个候选工具"

        # 输出标签必填（模板声明时）
        if self.current_template:
            if self.current_template.get("output_file_label") is not None:
                output_value, _, _, has_value = extract_wrapped_value(config.get("output_file_label"))
                ok, reason = self._check_text_entries(output_value if has_value else None)
                if not ok:
                    if reason == "invalid":
                        return f"输出标签仅允许{TEXT_RULE_HINT}"
                    return "输出标签不能为空"
            if self.current_template.get("result_col") is not None:
                result_value, _, _, has_value = extract_wrapped_value(config.get("result_col"))
                ok, reason = self._check_text_entries(result_value if has_value else None)
                if not ok:
                    if reason == "invalid":
                        return f"输出结果列仅允许{TEXT_RULE_HINT}"
                    return "输出结果列不能为空"

        return None

    def save_config(self) -> None:
        if not self.validate_run_param_types(show_message=True, require_instance=True):
            return
        payload = self.build_payload(require_instance=True)
        err = self.validate_payload(payload, require_instance=True)
        if err:
            QMessageBox.warning(self, "校验失败", err)
            return

        instance_name = self.instance_name_edit.text().strip() or self.current_instance_name
        if not instance_name:
            QMessageBox.warning(self, "错误", "实例名称不能为空")
            return

        # 获取当前选中的目录（从 ToolInstanceConfigTab）
        # 新建工具时，保存到当前选中的目录
        directory: Optional[str] = None
        if hasattr(self, "tool_instance_tab") and self.tool_instance_tab is not None:
            directory = getattr(self.tool_instance_tab, "current_directory", "") or ""
        
        try:
            if self.is_new_tool:
                # 新建工具：需要发送完整信息
                body = {
                    "instance_name": instance_name,
                    "tool_type": payload["tool_type"],
                    "code_name": payload.get("code_name"),
                    "config": payload.get("config", {}),
                    "comment": self.get_comment_callback() if self.get_comment_callback else None,
                    "directory": directory or "",
                }
                try:
                    self.api_client.create_tool_instance(body)
                except requests.HTTPError as http_err:
                    detail = ""
                    try:
                        detail = http_err.response.json()
                    except Exception:
                        detail = http_err.response.text if http_err.response is not None else ""
                    if isinstance(detail, dict) and detail.get("reason") == "instance_exists":
                        QMessageBox.warning(
                            self,
                            "实例已存在",
                            f"实例名称 {instance_name} 已存在，请更换名称或在列表中选中该实例后保存。",
                        )
                        return
                    raise
            else:
                # 更新工具：只发送后端需要的字段（config, comment, directory）
                body = {
                    "config": payload.get("config", {}),
                    "comment": self.get_comment_callback() if self.get_comment_callback else None,
                }
                if directory is not None:
                    body["directory"] = directory
                self.api_client.update_tool_instance(instance_name, body)
            # 同步导出到文件
            try:
                export_res = self.api_client.export_tool_instance(instance_name)
                if export_res.get("status") != "ok":
                    logger.warning(f"导出文件失败: {export_res}")
            except Exception as exp:
                logger.warning(f"导出文件失败: {exp}")
            QMessageBox.information(self, "成功", "已保存工具配置")
            self.is_new_tool = False
            self.current_instance_name = instance_name
            self.instance_name_edit.setDisabled(True)
            
            # 先调用回调（可能会刷新工具列表），然后再重新加载工具实例
            # 这样可以确保工具列表刷新后，再重新加载当前工具实例，避免代码名被重置
            if self.on_save_success_callback:
                self.on_save_success_callback()
            
            # 重新加载工具实例，确保工具类型和代码名正确显示
            # 这很重要，因为保存后可能工具类型或代码名发生了变化
            try:
                self.load_tool_instance(instance_name)
            except Exception as e:
                logger.warning(f"保存后重新加载工具实例失败: {e}")
                # 如果重新加载失败，至少标记为已保存
                self.mark_saved()
        except Exception as e:
            logger.error(f"保存失败: {e}", exc_info=True)
            QMessageBox.warning(self, "错误", f"保存失败: {e}")

    # ---------- 参数类型校验 ----------
    def _normalize_type(self, expected_type: Optional[str]) -> (Optional[str], bool):
        """解析 optional_xxx 前缀，返回基础类型与是否可选"""
        if not expected_type:
            return expected_type, False
        if expected_type.startswith("optional_"):
            return expected_type[len("optional_") :], True
        return expected_type, False

    def _reset_instance_param_meta(self) -> None:
        self.instance_param_meta = {
            "input_label_map": {"comments": {}, "wrapped": set()},
            "input_cols": {"comments": {}, "wrapped": set()},
            "run_params": {"comments": {}, "wrapped": set()},
            "output_file_label": {"comment": None, "wrapped": False},
            "output_pattern": {"comment": None, "wrapped": False},
            "result_col": {"comment": None, "wrapped": False},
        }

    def _reset_comment_widgets(self) -> None:
        self.comment_widgets = {
            "input_label_map": {},
            "input_cols": {},
            "run_params": {},
            "output_file_label": {},
            "result_col": {},
        }

    def _instance_comment(self, section: str, name: Optional[str] = None) -> Optional[str]:
        """返回实例配置中的注释（若存在）。"""
        meta = self.instance_param_meta.get(section, {})
        if section in {"input_label_map", "run_params", "input_cols"}:
            comments = meta.get("comments") or {}
            return comments.get(name)
        return meta.get("comment")

    def _comment_with_fallback(self, section: str, name: Optional[str], fallback: Optional[str]) -> str:
        comment = self._instance_comment(section, name)
        text = self._clean_comment_entry(comment)
        if text:
            return text
        return fallback or ""

    def _wrap_mapping_with_meta(self, section: str, values: Dict[str, Any]) -> Dict[str, Any]:
        rebuilt: Dict[str, Any] = {}
        processed: Set[str] = set()
        print(f"DEBUG: _wrap_mapping section={section}, values={values}", flush=True)
        for key, val in values.items():
            comment_payload = self._get_comment_payload(section, key, val)
            print(f"DEBUG: key={key}, val={val}, comment={comment_payload}", flush=True)
            rebuilt[key] = rebuild_wrapped_value(val, comment_payload)
            print(f"DEBUG: rebuilt[{key}] = {rebuilt[key]}", flush=True)
            processed.add(key)

        # 额外处理仅有注释的字段
        comment_keys: Set[str] = set(self.comment_widgets.get(section, {}).keys())
        meta_comments = self.instance_param_meta.get(section, {}).get("comments", {})
        comment_keys.update(meta_comments.keys())
        for key in comment_keys:
            if key in processed:
                continue
            comment_payload = self._get_comment_payload(section, key, None)
            if comment_payload:
                rebuilt[key] = rebuild_wrapped_value(
                    None,
                    comment_payload,
                    force_wrap=True,
                    comment_only=True,
                )
        return rebuilt

    def _wrap_single_with_meta(self, section: str, name: Optional[str], value: Any) -> Any:
        comment_payload = self._get_comment_payload(section, name, value)
        if value is None and comment_payload:
            return rebuild_wrapped_value(
                None,
                comment_payload,
                force_wrap=True,
                comment_only=True,
            )
        return rebuild_wrapped_value(value, comment_payload)

    def _get_comment_payload(self, section: str, name: Optional[str], value: Any) -> Optional[Any]:
        has_editor = name in self.comment_widgets.get(section, {})
        widget_comment = self._read_comment_widget(section, name)
        if widget_comment is None and not has_editor:
            widget_comment = self._instance_comment(section, name)
        return self._coerce_comment_shape(value, widget_comment)

    def _read_comment_widget(self, section: str, name: Optional[str]) -> Optional[Any]:
        widget = self.comment_widgets.get(section, {}).get(name)
        print(f"DEBUG: _read_comment_widget section={section} name={name} widget={widget}", flush=True)
        if isinstance(widget, ListValueEditor):
            comments = widget.get_comment_values()
            # 若行内注释均为空则返回 None
            if not comments or all(entry in {None, ""} for entry in comments):
                return None
            return comments
        if isinstance(widget, QLineEdit):
            text = widget.text().strip()
            print(f"DEBUG: QLineEdit text='{text}'", flush=True)
            return text or None
        return None

    def _coerce_comment_shape(self, value: Any, comment: Optional[Any]) -> Optional[Any]:
        if comment is None:
            return None
        if isinstance(value, list):
            return self._normalize_comment_list(comment, len(value))
        if isinstance(comment, list):
            for entry in comment:
                cleaned = self._clean_comment_entry(entry)
                if cleaned:
                    return cleaned
            return None
        return self._clean_comment_entry(comment)

    def _normalize_comment_list(self, comment: Any, length: int) -> Optional[List[Optional[str]]]:
        if isinstance(comment, list):
            entries = [self._clean_comment_entry(c) for c in comment]
        else:
            entries = [self._clean_comment_entry(comment)]
        if length > 0:
            if len(entries) < length:
                entries.extend([None] * (length - len(entries)))
            elif len(entries) > length:
                entries = entries[:length]
        has_value = any(entry is not None for entry in entries)
        return entries if has_value else None

    @staticmethod
    def _clean_comment_entry(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            for entry in value:
                cleaned = ToolConfigWidget._clean_comment_entry(entry)
                if cleaned:
                    return cleaned
            return None
        text = str(value).strip()
        return text or None

    def _has_comment_value(self, comment: Any) -> bool:
        if isinstance(comment, list):
            return any(self._has_comment_value(entry) for entry in comment)
        return self._clean_comment_entry(comment) is not None

    def _resolve_label_text(self, fallback: str, comment: Optional[str]) -> str:
        if self.label_from_comment:
            cleaned = self._clean_comment_entry(comment)
            if cleaned:
                return cleaned
        return fallback

    def _apply_row_comment_labels(self, editor: Any, comment_source: Any) -> bool:
        if not self.label_from_comment or not isinstance(editor, ListValueEditor):
            return False
        entries, is_sequence = self._comment_entries_from_source(comment_source)
        
        # print(f"DEBUG: _apply_row_comment_labels: is_sequence={is_sequence}, source_type={type(comment_source)}, entries={entries}", flush=True)

        # 如果不是序列（即标量注释），不要将其作为行内标签
        # 而是让它显示在左侧的主标签上，这样保持两栏布局 (标签 | 输入框)
        if not is_sequence:
            return False
            
        # 如果编辑器只有一行，强制作为主标签显示（忽略注释列表长度）
        # 即使注释是列表（例如 ["c1", "c2"]），对于单行输入框，我们只取第一个作为外层标签，避免显示内层标签
        if len(editor.rows) <= 1:
            return False
            
        if len(entries) < len(editor.rows):
            entries.extend([None] * (len(editor.rows) - len(entries)))
        elif len(entries) > len(editor.rows):
            entries = entries[: len(editor.rows)]
        has_visible = any(entry is not None for entry in entries)
        editor.set_row_labels(entries if has_visible else [])
        # 注意：如果使用了行内标签，可能需要根据标签可见性控制行可见性
        # 但对于非序列模式，我们已经返回False，所以这里主要处理序列模式（元组输入等）
        if has_visible:
            editor.set_row_visibility([entry is not None for entry in entries])
        return has_visible

    def _comment_entries_from_source(self, comment_source: Any) -> (List[Optional[str]], bool):
        if isinstance(comment_source, (list, tuple)):
            return [self._clean_comment_entry(entry) for entry in comment_source], True
        return [self._clean_comment_entry(comment_source)], False

    def _wrap_with_comment_field(
        self,
        section: str,
        name: Optional[str],
        main_widget: QWidget,
        existing_comment: Optional[str],
        template_comment: Optional[str] = None,
        enabled: bool = True,
    ) -> QWidget:
        if not self.enable_comments or not enabled:
            return main_widget

        self.comment_widgets.setdefault(section, {})

        if isinstance(main_widget, ListValueEditor):
            main_widget.enable_comments(existing_comment)
            if template_comment:
                main_widget.set_comment_tooltip(self._markdown_to_html(template_comment))
            self.comment_widgets[section][name] = main_widget
            return main_widget

        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(main_widget)
        comment_edit = QLineEdit()
        comment_edit.setPlaceholderText("字段注释（可选）")
        if template_comment:
            comment_edit.setToolTip(self._markdown_to_html(template_comment))
        if existing_comment:
            if isinstance(existing_comment, list):
                comment_edit.setText("; ".join([str(c) for c in existing_comment if c is not None]))
            else:
                comment_edit.setText(str(existing_comment))
        comment_edit.textChanged.connect(self._emit_form_changed)
        layout.addWidget(comment_edit)
        container.setLayout(layout)
        self.comment_widgets[section][name] = comment_edit
        return container

    def _field_label(self, name: str, type_hint: Optional[str], required: bool = True, tooltip: Optional[str] = None) -> QLabel:
        """生成带可选/必填与类型提示的标签"""
        label = QLabel()
        if tooltip:
            label.setToolTip(self._markdown_to_html(tooltip))
        
        # 设置最小宽度以实现对齐效果
        # 如果标签内容较短，会占用固定宽度；如果较长，会撑开（不对齐）
        label.setMinimumWidth(140)
        # 右对齐通常在表单中看起来更整洁，但根据用户"对齐"的描述，左对齐可能更符合直觉
        # 这里使用左对齐，并保持足够的宽度
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        if self.label_from_comment:
            # 简洁模式：只显示名称（已经是解析后的注释/标签）
            label.setText(name)
            label.setProperty("muted", True)
            return label
            
        use_meta = True
        meta = []
        if use_meta and required:
            # 使用星号代替 "必填" 字样，更加简洁
            meta.append("*")
        if use_meta and type_hint:
            meta.append(type_hint)
        suffix = f" ({''.join(meta)})" if meta else ""
        label.setText(f"{name}{suffix}")
        label.setProperty("muted", True)
        return label

    @staticmethod
    def _widget_value(widget: Union[QLineEdit, NoWheelComboBox]) -> str:
        if isinstance(widget, NoWheelComboBox):
            data = widget.currentData()
            if data is None:
                data = widget.currentText()
            return "" if data is None else str(data).strip()
        return widget.text().strip()

    @staticmethod
    def _clear_widget(widget: Union[QLineEdit, NoWheelComboBox], optional: bool = False) -> None:
        if isinstance(widget, NoWheelComboBox):
            if optional:
                idx = widget.findData("")
                widget.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                widget.setCurrentIndex(0 if widget.count() else -1)
        else:
            widget.clear()

    def _reset_widget_value(self, widget: Any, optional: bool = False) -> None:
        if isinstance(widget, ListValueEditor):
            widget.set_value([None])
        else:
            self._clear_widget(widget, optional=optional)

    @staticmethod
    def _set_combo_value(combo: NoWheelComboBox, value: Optional[Any]) -> None:
        # 防御性处理：确保 value 是可哈希的
        is_unhashable = isinstance(value, (dict, list))
        if is_unhashable or value in {None, ""}:
            if is_unhashable:
                logger.warning(f"[_set_combo_value] 收到不可哈希的值: {value}，已跳过 Set 检查")
            
            idx = combo.findData("")
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif combo.count():
                combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(-1)
            return

        candidates = [value]
        if isinstance(value, bool):
            candidates.extend(["true" if value else "false", str(value).lower()])
        if isinstance(value, (int, float)):
            candidates.append(str(value))

        for candidate in candidates:
            idx = combo.findData(candidate)
            if idx >= 0:
                combo.setCurrentIndex(idx)
                return
        for candidate in candidates:
            if candidate is None:
                continue
            idx = combo.findText(str(candidate))
            if idx >= 0:
                combo.setCurrentIndex(idx)
                return
        text_value = "" if value is None else str(value)
        if text_value:
            if combo.findText(text_value) < 0:
                combo.addItem(text_value, text_value)
            idx = combo.findText(text_value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
                return
        if combo.isEditable():
            combo.setEditText(text_value)

    @staticmethod
    def _normalize_text_value(value: Optional[Any]) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _check_text_entries(self, value: Any) -> (bool, str):
        if value is None:
            return False, "empty"
        values = value if isinstance(value, list) else [value]
        if not values:
            return False, "empty"
        for entry in values:
            text = self._normalize_text_value(entry)
            if not text:
                return False, "empty"
            if not self._is_valid_text(text):
                return False, "invalid"
        return True, ""

    def _collect_editor_values(self, widget: Any) -> (List[Any], bool):
        if isinstance(widget, ListValueEditor):
            return widget.get_all_values(), widget.is_list_mode()
        # 兼容旧逻辑
        return [self._widget_value(widget)], False

    @staticmethod
    def _normalize_bool_display(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "false"}:
                return lowered
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).strip().lower()

    def _normalize_run_value_for_display(self, value: Any, base_type: Optional[str]) -> Any:
        def normalize_single(val: Any) -> Any:
            if val is None:
                return None
            if base_type == "bool":
                return self._normalize_bool_display(val)
            if base_type == "from_result" and isinstance(val, dict):
                if val:
                    return next(iter(val.values()))
            return val

        if isinstance(value, list):
            return [normalize_single(v) for v in value]
        return normalize_single(value)

    def validate_run_param_types(self, show_message: bool = True, require_instance: bool = True) -> bool:
        """检查运行参数/输出字段/实例名的合法性，错误时清空并提示"""
        # 实例名校验（仅工具实例场景）
        if require_instance:
            inst = self.instance_name_edit.text().strip()
            if not inst:
                if show_message:
                    QMessageBox.warning(
                        self,
                        "参数检查不通过",
                        "<span style='color:red;'>参数检查不通过：实例名称未填写</span>",
                    )
                self._emit_form_changed()
                return False
            
            # 仅在新建时或实例名可编辑时进行严格校验
            # 如果是编辑现有实例（输入框被禁用），则跳过格式校验，允许保存存量数据
            if self.instance_name_edit.isEnabled() and not self._is_valid_text(inst):
                if show_message:
                    QMessageBox.warning(
                        self,
                        "参数检查不通过",
                        f"<span style='color:red;'>参数检查不通过：实例名称仅允许{TEXT_RULE_HINT}</span>",
                    )
                self._emit_form_changed()
                return False

        run_widgets: Dict[str, Any] = self.config_widgets.get("run_params", {})
        if run_widgets and self.tool_type_combo.currentText() != "meta":
            for name, widget in run_widgets.items():
                # 从 widget 中获取绑定的策略对象
                strategy = getattr(widget, "_strategy", None)
                if not strategy:
                    # 如果不是通过 Factory 创建的（比如某些特殊字段），暂时跳过或使用旧逻辑
                    # 但在这里我们的 run_params 应该都是新逻辑创建的
                    continue

                values, is_list = self._collect_editor_values(widget)
                entries = list(enumerate(values))
                if not entries:
                    continue
                if not is_list:
                    entries = [(0, entries[0][1])]
                    
                for idx, raw_val in entries:
                    # 使用策略进行校验
                    # validate_single 会自动处理 strip 和 optional
                    is_valid, _, error_msg = strategy.validate_single(raw_val)
                    
                    if not is_valid:
                        # 校验失败
                        # 重置值（如果是 optional 的话，validate_single 已经处理了 empty_optional 返回 True）
                        # 这里如果返回 False，说明是真的非法
                        self._reset_widget_value(widget, optional=strategy.is_optional)
                        
                        if show_message:
                            suffix = f" 第{idx + 1}项" if is_list else ""
                            # 根据 error_msg 生成友好的提示
                            hint = ""
                            if error_msg == "empty":
                                hint = "未填写"
                            elif error_msg == "invalid_chars":
                                hint = f"仅允许{TEXT_RULE_HINT}"
                            elif error_msg.startswith("not_"):
                                hint = f"类型错误 (期望 {error_msg.replace('not_', '')})"
                            else:
                                hint = f"格式错误 ({error_msg})"
                                
                            QMessageBox.warning(
                                self,
                                "参数检查不通过",
                                f"<span style='color:red;'>参数检查不通过：运行参数 {name}{suffix} {hint}</span>",
                            )
                        self._emit_form_changed()
                        return False

        # 输出标签/result_col/input_cols 校验（字符限制）
        output_widget: Optional[Any] = self.config_widgets.get("output_file_label")
        if output_widget:
            values, _ = self._collect_editor_values(output_widget)
            for val in values:
                text = self._normalize_text_value(val)
                if text and not self._is_valid_text(text):
                    self._reset_widget_value(output_widget)
                    if show_message:
                        QMessageBox.warning(
                            self,
                            "参数检查不通过",
                            f"<span style='color:red;'>参数检查不通过：输出标签仅允许{TEXT_RULE_HINT}</span>",
                        )
                    self._emit_form_changed()
                    return False

        result_col_widget: Optional[Any] = self.config_widgets.get("result_col")
        if result_col_widget:
            values, _ = self._collect_editor_values(result_col_widget)
            for val in values:
                text = self._normalize_text_value(val)
                if text and not self._is_valid_text(text):
                    self._reset_widget_value(result_col_widget)
                    if show_message:
                        QMessageBox.warning(
                            self,
                            "参数检查不通过",
                            f"<span style='color:red;'>参数检查不通过：输出结果列仅允许{TEXT_RULE_HINT}</span>",
                        )
                    self._emit_form_changed()
                    return False

        result_widgets = self.config_widgets.get("input_cols", {})
        for name, widget in result_widgets.items():
            values, _ = self._collect_editor_values(widget)
            txt = self._normalize_text_value(values[0] if values else None)
            
            if txt and not self._is_valid_text(txt):
                self._reset_widget_value(widget)
                if show_message:
                    QMessageBox.warning(
                        self,
                        "参数检查不通过",
                        f"<span style='color:red;'>参数检查不通过：{name} 仅允许{TEXT_RULE_HINT}</span>",
                    )
                self._emit_form_changed()
                return False

        if show_message:
            QMessageBox.information(
                self,
                "参数检查通过",
                "<span style='color:green;'>参数检查通过</span>",
            )
        return True

    @staticmethod
    def _is_valid_text(text: str) -> bool:
        """基于 frontend.json 的字符规则"""
        return bool(TEXT_RULE_RE.fullmatch(text))

    # ---------- 保存状态 ----------
    def mark_unsaved(self) -> None:
        if self.save_status_label:
            self.save_status_label.setText(tr("unsaved"))
            self.save_status_label.setProperty("badge", "warn")
            self.save_status_label.style().unpolish(self.save_status_label)
            self.save_status_label.style().polish(self.save_status_label)

    def mark_saved(self) -> None:
        if self.save_status_label:
            self.save_status_label.setText(tr("saved"))
            self.save_status_label.setProperty("badge", "success")
            self.save_status_label.style().unpolish(self.save_status_label)
            self.save_status_label.style().polish(self.save_status_label)
