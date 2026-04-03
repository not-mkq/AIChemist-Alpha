#!/usr/bin/env python3
"""
form_builder.py

表单构建器：封装 ToolConfigWidget 中复杂的表单行构建逻辑。
处理控件创建、初始值回填、注释处理、Label生成、行内标签注入以及显隐控制。
"""

from typing import Any, Optional, Dict, Union
import logging

from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit
)

# 尝试导入依赖
try:
    from .widgets import ListValueEditor, NoWheelComboBox
    from .param_strategies import ParamEditorFactory, ParamStrategy
except ImportError:
    from widgets import ListValueEditor
    from param_strategies import ParamEditorFactory, ParamStrategy

# 模拟 markdown 处理 (ToolConfigWidget 中也有类似逻辑)
try:
    import markdown
except ImportError:
    markdown = None

logger = logging.getLogger(__name__)


class FormRowResult:
    """构建结果封装"""
    def __init__(
        self,
        name: str,
        label_widget: QLabel,
        container_widget: QWidget,
        editor_widget: Union[ListValueEditor, QWidget],
        comment_widget: Optional[Union[QLineEdit, ListValueEditor]], # 用于读取注释
        should_show: bool,
        is_list_editor: bool,
        span_row: bool = False  # 新增：是否独占一行（不显示左侧 Label）
    ):
        self.name = name
        self.label_widget = label_widget
        self.container_widget = container_widget
        self.editor_widget = editor_widget
        self.comment_widget = comment_widget
        self.should_show = should_show
        self.is_list_editor = is_list_editor
        self.span_row = span_row


class FormRowBuilder:
    """
    表单行构建器
    
    职责：
    1. 调用 ParamEditorFactory 创建核心编辑控件
    2. 处理初始值 (Initial Value)
    3. 处理注释 (Instance Comment & Template Comment)
    4. 处理 Label 显示逻辑 (包括 label_from_comment, row_labels 注入)
    5. 组装 Layout (Label + Container)
    """

    def __init__(self, context: Any):
        """
        context: ToolConfigWidget 实例或包含其配置的对象
        需要提供以下属性/方法:
        - enable_comments (bool)
        - label_from_comment (bool)
        - lock_list_row_controls (bool)
        - instance_param_meta (dict)
        - _instance_comment(section, name) -> str
        - _has_comment_value(comment) -> bool
        - _markdown_to_html(text) -> str
        - form_changed (Signal) - 用于绑定变更事件
        """
        self.ctx = context

    def build(
        self,
        section: str,
        param_def: Dict[str, Any],
        initial_value: Any,
        param_strategy: Optional[ParamStrategy] = None,
        context_data: Optional[Dict[str, Any]] = None,
        force_show: bool = False
    ) -> FormRowResult:
        """
        构建单行表单
        
        Args:
            section: "run_params", "input_label_map" 等
            param_def: 参数定义字典 (包含 name, comment, type 等)
            initial_value: 初始值 (未 wrap 的原始值)
            param_strategy: 可选，预先创建的策略对象。如果为 None，则使用 Factory 创建。
            context_data: 传递给 Factory 的上下文 (如 labels, result_cols)
            force_show: 强制显示 (忽略 label_from_comment 的隐藏逻辑)，用于必须显示的字段
        """
        name = param_def.get("name")
        template_comment = param_def.get("comment", "")
        
        # 1. 准备策略与控件
        if param_strategy is None:
            param_strategy = ParamEditorFactory.create(param_def, context_data)
        
        editor = param_strategy.create_editor()
        
        # 应用锁定设置
        if self.ctx.lock_list_row_controls:
            editor.set_row_operations_enabled(False)
            
        # 绑定变更信号 (直接绑定到 ctx 的方法，避免 builder 被回收导致连接断开)
        if hasattr(editor, "value_changed"):
            editor.value_changed.connect(self.ctx._emit_form_changed)
        elif hasattr(editor, "textChanged"):
            editor.textChanged.connect(lambda _: self.ctx._emit_form_changed())
        elif hasattr(editor, "currentIndexChanged"):
            editor.currentIndexChanged.connect(lambda _: self.ctx._emit_form_changed())
        
        # 设置 Tooltip
        if template_comment:
            editor.setToolTip(self.ctx._markdown_to_html(template_comment))

        # 2. 回填初始值
        # 这里的 initial_value 应该是已经 unwrap 过的 raw value (list or scalar)
        # 但 ParamEditorFactory 期望的是未 normalize 的值？
        # 不，widgets.py 的 set_value 期望的是 raw value
        # 但我们需要处理 from_result 等特殊结构吗？
        # ToolConfigWidget 里的逻辑是：
        # normalized_value = self._normalize_run_value_for_display(...)
        # editor.set_value(normalized_value)
        # 我们在这里做一个简单的规范化，或者假设传入的 initial_value 已经是规范化好的
        # 为了稳健，我们调用 ctx 的规范化方法（如果存在）
        
        # 复用 ToolConfigWidget 的规范化逻辑
        if hasattr(self.ctx, "_normalize_run_value_for_display"):
            # 需要解析 base_type
            base_type = getattr(param_strategy, "base_type", None) or \
                        getattr(param_strategy, "target_type", None) or \
                        param_def.get("type", "str")
            # 去掉 optional_ 前缀
            if base_type.startswith("optional_"):
                base_type = base_type[9:]
                
            final_val = self.ctx._normalize_run_value_for_display(initial_value, base_type)
            editor.set_value(final_val)
        else:
            editor.set_value(initial_value)

        # 3. 处理注释与显隐逻辑
        existing_comment = self.ctx._instance_comment(section, name)
        
        # 决定是否显示
        # 如果 force_show=True，则忽略 label_from_comment 的隐藏规则
        # 否则，如果开启了 label_from_comment 且没有实例注释，则隐藏
        show_field = True
        if not force_show and self.ctx.label_from_comment:
            if not self.ctx._has_comment_value(existing_comment):
                show_field = False
        
        # 4. 行内标签注入 (Row Labels)
        # 逻辑：如果显示字段，且存在注释，尝试将注释解析为行内标签
        comment_source = existing_comment if self.ctx.label_from_comment else (
            existing_comment if existing_comment is not None else template_comment
        )
        
        has_row_labels = False
        if show_field:
            # _apply_row_comment_labels 是 ToolConfigWidget 的方法，我们需要复用它
            # 或者将其逻辑搬过来。为避免重复，我们假设 ctx 有这个方法。
            if hasattr(self.ctx, "_apply_row_comment_labels"):
                has_row_labels = self.ctx._apply_row_comment_labels(editor, comment_source)
        
        # 决定是否独占一行
        span_row = False
        if self.ctx.label_from_comment and has_row_labels:
            span_row = True

        # 5. 包装注释输入框 (Comment Input)
        # 逻辑：_wrap_with_comment_field
        # 返回 container, 并注册到 comment_widgets
        container = None
        comment_widget = None
        
        if hasattr(self.ctx, "_wrap_with_comment_field"):
            # 注意：_wrap_with_comment_field 会副作用修改 ctx.comment_widgets
            container = self.ctx._wrap_with_comment_field(
                section, name, editor, existing_comment, 
                template_comment=template_comment,
                enabled=(not self.ctx.lock_list_row_controls) # 假设锁定控件时也锁定注释添加？ToolConfigWidget里output_file_label是false
            )
            # 从 ctx.comment_widgets 取回刚刚注册的 widget
            section_widgets = self.ctx.comment_widgets.get(section, {})
            comment_widget = section_widgets.get(name)
        else:
            # Fallback (如果不依赖 ctx 的副作用)
            container = editor # 简化处理
            comment_widget = None

        # 6. 生成主 Label
        # 逻辑：如果使用了行内标签，主 Label 就不显示注释内容了
        label_text_source = None
        if self.ctx.label_from_comment:
            if not has_row_labels:
                label_text_source = existing_comment
            # else: label_text_source = None (已在行内显示)
        else:
            if not has_row_labels:
                label_text_source = self.ctx._comment_with_fallback(section, name, template_comment)
            # else: label_text_source = None
        
        label_text = self.ctx._resolve_label_text(name, label_text_source)
        
        # 类型提示
        type_hint = getattr(param_strategy, "base_type", None) or \
                    getattr(param_strategy, "target_type", None) or \
                    param_def.get("type", "str")
        if type_hint.startswith("optional_"):
            type_hint = type_hint[9:]
        
        is_optional = getattr(param_strategy, "is_optional", False)
        
        label_widget = self.ctx._field_label(
            label_text, 
            type_hint=type_hint, 
            required=not is_optional, 
            tooltip=template_comment
        )

        # 7. 最终显隐设置
        if not show_field:
            label_widget.setVisible(False)
            container.setVisible(False)
            
        return FormRowResult(
            name=name,
            label_widget=label_widget,
            container_widget=container,
            editor_widget=editor,
            comment_widget=comment_widget,
            should_show=show_field,
            is_list_editor=isinstance(editor, ListValueEditor),
            span_row=span_row
        )


    def _emit_form_changed(self):
        if hasattr(self.ctx, "_emit_form_changed"):
            self.ctx._emit_form_changed()