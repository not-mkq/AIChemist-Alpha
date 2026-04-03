
"""
param_strategies.py

参数编辑器策略模块：将不同类型参数的 UI 生成、数据读写、校验逻辑封装为独立策略类。
替代 tool_config_widget.py 中的巨型 switch-case 逻辑。
"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple
import re
import logging

from PyQt6.QtWidgets import QWidget, QLineEdit

# 尝试导入 NoWheelComboBox，如果处于独立测试环境可能需要调整导入路径
try:
    from widgets import NoWheelComboBox, ListValueEditor, AutoResizingTextEdit
except ImportError:
    from .widgets import NoWheelComboBox, ListValueEditor, AutoResizingTextEdit

from i18n import tr

logger = logging.getLogger(__name__)

# --- 前端校验规则 ---
# 宽松的默认规则：仅要求非空（允许空格、括号等特殊字符），与 ToolConfigWidget 保持一致
TEXT_RULE_RE = re.compile(r".+")
TEXT_RULE_HINT = tr("cannot_be_empty")


class ParamStrategy(ABC):
    """参数处理策略基类"""

    def __init__(self, param_name: str, is_optional: bool, tooltip: Optional[str] = None):
        self.param_name = param_name
        self.is_optional = is_optional
        self.tooltip = tooltip

    @abstractmethod
    def create_input_widget(self) -> QWidget:
        """创建单个输入控件（不包含 ListValueEditor 包装）"""
        pass

    @abstractmethod
    def get_value(self, widget: QWidget) -> Any:
        """从控件获取原始值（通常是字符串）"""
        pass

    @abstractmethod
    def set_value(self, widget: QWidget, value: Any) -> None:
        """将值设置到控件"""
        pass

    def validate_single(self, value: Any) -> Tuple[bool, Any, str]:
        """
        校验并转换单个值
        Returns: (is_valid, coerced_value, error_type_or_message)
        """
        # 默认实现：如果是必填且为空，则失败
        text = str(value).strip() if value is not None else ""
        if not text and not self.is_optional:
            return False, text, "empty"
        if not text and self.is_optional:
            return True, None, "empty_optional"
        return True, text, "str"

    def create_editor(self, parent=None) -> ListValueEditor:
        """
        工厂方法：创建一个配置好的 ListValueEditor。
        这是对外暴露的主要接口。
        """
        # 1. 定义工厂函数，用于 ListValueEditor 内部创建行
        def widget_factory(tooltip=self.tooltip, _self=self):
            w = _self.create_input_widget()
            if tooltip:
                w.setToolTip(tooltip)
            return w

        # 2. 创建 ListValueEditor
        editor = ListValueEditor(
            widget_factory=widget_factory,
            value_getter=self.get_value,
            value_setter=self.set_value
        )
        
        # 3. 保存策略引用，方便后续访问（如果需要）
        editor._strategy = self
        
        if self.tooltip:
            editor.setToolTip(self.tooltip)
            
        return editor


class TextStrategy(ParamStrategy):
    """处理 str, int, float"""
    
    def __init__(self, param_name: str, is_optional: bool, target_type: str, tooltip: Optional[str] = None):
        super().__init__(param_name, is_optional, tooltip)
        self.target_type = target_type  # 'str', 'int', 'float'

    def create_input_widget(self) -> QWidget:
        if self.target_type == "str":
            edit = AutoResizingTextEdit()
            edit.setPlaceholderText(f"{self.target_type} 参数值")
            return edit
        
        edit = QLineEdit()
        edit.setPlaceholderText(f"{self.target_type} 参数值")
        return edit

    def get_value(self, widget: QWidget) -> Any:
        return widget.text().strip()

    def set_value(self, widget: QWidget, value: Any) -> None:
        text = "" if value is None else str(value)
        widget.setText(text)

    def validate_single(self, value: Any) -> Tuple[bool, Any, str]:
        text = str(value).strip() if value is not None else ""
        
        # 必填检查
        if not text:
            return (True, None, "empty_optional") if self.is_optional else (False, text, "empty")
            
        # 类型转换检查
        if self.target_type == "int":
            try:
                return True, int(text), "int"
            except ValueError:
                return False, text, "not_int"
        elif self.target_type == "float":
            try:
                return True, float(text), "float"
            except ValueError:
                return False, text, "not_float"
        
        return True, text, "str"


class BoolStrategy(ParamStrategy):
    """处理 bool"""

    def create_input_widget(self) -> QWidget:
        combo = NoWheelComboBox()
        if self.is_optional:
            combo.addItem("留空", "")
        combo.addItem("true", "true")
        combo.addItem("false", "false")
        return combo

    def get_value(self, widget: QWidget) -> Any:
        data = widget.currentData()
        if data is None:
            # Fallback for "true"/"false" items which might not have data set explicitly in some legacy code,
            # but here we set it explicitly.
            return widget.currentText()
        return str(data).strip()

    def set_value(self, widget: QWidget, value: Any) -> None:
        # 规范化显示值
        normalized = None
        if value is None:
            normalized = ""
        elif isinstance(value, bool):
            normalized = "true" if value else "false"
        else:
            s = str(value).strip().lower()
            if s in ("true", "1", "yes"): normalized = "true"
            elif s in ("false", "0", "no"): normalized = "false"
            else: normalized = s # Fallback

        # 选中逻辑
        self._set_combo_value(widget, normalized)

    def _set_combo_value(self, combo: NoWheelComboBox, value: str):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            # 尝试文本匹配
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif self.is_optional:
                 # 默认为空
                idx = combo.findData("")
                if idx >= 0: combo.setCurrentIndex(idx)
    
    def validate_single(self, value: Any) -> Tuple[bool, Any, str]:
        text = str(value).strip().lower() if value is not None else ""
        
        if not text:
            return (True, None, "empty_optional") if self.is_optional else (False, text, "empty")
            
        if text in ("true", "1", "yes"):
            return True, True, "bool"
        if text in ("false", "0", "no"):
            return True, False, "bool"
            
        return False, text, "not_bool"


class EnumStrategy(ParamStrategy):
    """处理 enum (str, int, float)"""
    
    def __init__(self, param_name: str, is_optional: bool, base_type: str, choices: List[Any], tooltip: Optional[str] = None):
        super().__init__(param_name, is_optional, tooltip)
        self.base_type = base_type # 'str', 'int', 'float' (without _enum suffix)
        self.choices = choices or []

    def create_input_widget(self) -> QWidget:
        combo = NoWheelComboBox()
        if self.is_optional:
            combo.addItem("留空", "")
        for choice in self.choices:
            combo.addItem(str(choice), choice)
        return combo

    def get_value(self, widget: QWidget) -> Any:
        # 优先取 Data，其次取 Text
        val = widget.currentData()
        if val is None:
            val = widget.currentText()
        return str(val).strip()

    def set_value(self, widget: QWidget, value: Any) -> None:
        # 简单的选中逻辑，假设 value 与 choices 中的类型一致或能转为字符串匹配
        val_str = str(value) if value is not None else ""
        idx = widget.findData(value) 
        if idx < 0:
             idx = widget.findText(val_str)
        
        if idx >= 0:
            widget.setCurrentIndex(idx)
        else:
             if self.is_optional:
                 idx = widget.findData("")
                 if idx >= 0: widget.setCurrentIndex(idx)

    def validate_single(self, value: Any) -> Tuple[bool, Any, str]:
        text = str(value).strip() if value is not None else ""
        if not text:
             return (True, None, "empty_optional") if self.is_optional else (False, text, "empty")

        # 尝试转换类型
        coerced = text
        try:
            if self.base_type == "int":
                coerced = int(text)
            elif self.base_type == "float":
                coerced = float(text)
        except ValueError:
            return False, text, f"not_{self.base_type}"
            
        # 检查是否在选项中
        # 注意：这里的比较可能需要根据具体类型做严格或宽松比较
        # 为简化，转为字符串比较，或者假设 choices 类型已经匹配
        is_valid = False
        for c in self.choices:
            if c == coerced:
                is_valid = True
                break
            # 宽松比较
            if str(c) == str(coerced):
                is_valid = True
                break
        
        if not is_valid:
            return False, coerced, "not_in_enum"
            
        return True, coerced, self.base_type


class DynamicChoiceStrategy(ParamStrategy):
    """处理 from_result, input_col, file_label 等需要动态候选项的场景"""
    
    def __init__(self, param_name: str, is_optional: bool, candidates: List[str], strict: bool = False, tooltip: Optional[str] = None):
        super().__init__(param_name, is_optional, tooltip)
        self.candidates = sorted(candidates)
        self.strict = strict # True=必须在列表中(Result/InputCol), False=可编辑(FileLabel)

    def create_input_widget(self) -> QWidget:
        combo = NoWheelComboBox()
        combo.setEditable(True) # 通常这几个都是可编辑的
        for c in self.candidates:
            combo.addItem(c)
        return combo

    def get_value(self, widget: QWidget) -> Any:
        return widget.currentText().strip()

    def set_value(self, widget: QWidget, value: Any) -> None:
        text = str(value).strip() if value is not None else ""
        if not text:
            widget.setCurrentIndex(-1)
            return
            
        idx = widget.findText(text)
        if idx >= 0:
            widget.setCurrentIndex(idx)
        else:
            # 如果不在列表中，但允许编辑，则设置文本
            widget.setEditText(text)

    def validate_single(self, value: Any) -> Tuple[bool, Any, str]:
        text = str(value).strip() if value is not None else ""
        if not text:
             return (True, None, "empty_optional") if self.is_optional else (False, text, "empty")
        
        # 字符合法性检查
        if not TEXT_RULE_RE.fullmatch(text):
            return False, text, "invalid_chars"
            
        # 暂时不强制要求必须在 candidates 中，除非业务逻辑有强约束
        # 原有逻辑对 result_col / output_file_label 主要是字符检查
        # 对 input_cols 也是字符检查
        
        return True, text, "str"


class ParamEditorFactory:
    """工厂类：根据类型创建对应的策略实例"""
    
    @staticmethod
    def create(param_info: dict, context_data: dict = None) -> ParamStrategy:
        """
        param_info: 模板中的参数定义 (dict)
        context_data: 上下文数据，如 {"result_cols": [], "labels": []}
        """
        name = param_info.get("name")
        raw_type = param_info.get("type", "str")
        tooltip = param_info.get("comment")
        choices = param_info.get("choices")
        
        # 解析 Optional
        is_optional = False
        base_type = raw_type
        if raw_type.startswith("optional_"):
            is_optional = True
            base_type = raw_type[len("optional_"):]
            
        context_data = context_data or {}

        # 1. Bool
        if base_type == "bool":
            return BoolStrategy(name, is_optional, tooltip)
            
        # 2. Enum (str_enum, int_enum, float_enum)
        if base_type.endswith("_enum"):
            pure_type = base_type.replace("_enum", "")
            return EnumStrategy(name, is_optional, pure_type, choices, tooltip)
            
        # 3. From Result
        if base_type == "from_result":
            candidates = []
            candidates.extend(context_data.get("result_cols_item", []))
            candidates.extend(context_data.get("result_cols_batch", []))
            candidates.extend(context_data.get("result_cols_project", []))
            # 去重
            candidates = sorted(list(set(candidates)))
            return DynamicChoiceStrategy(name, is_optional, candidates, strict=False, tooltip=tooltip)

        # 4. Text (int, float, str)
        return TextStrategy(name, is_optional, base_type, tooltip)

    @staticmethod
    def create_special(special_type: str, name: str, context_data: dict = None, tooltip: str = None) -> ParamStrategy:
        """创建特殊用途的编辑器 (input_cols, file_label, result_col)"""
        context_data = context_data or {}
        
        if special_type == "file_label":
            labels = context_data.get("labels", [])
            return DynamicChoiceStrategy(name, False, labels, strict=False, tooltip=tooltip)
            
        if special_type == "input_col":
             # merge 的 input_cols 来源于子级结果 (item/batch)
            candidates = []
            candidates.extend(context_data.get("result_cols_item", []))
            candidates.extend(context_data.get("result_cols_batch", []))
            candidates = sorted(list(set(candidates)))
            # 将默认值从 False 改为 True
            return DynamicChoiceStrategy(name, True, candidates, strict=False, tooltip=tooltip)
            
        if special_type == "simple_str": # result_col, output_pattern
            # 必填与否取决于具体字段，这里假设由外部调用者控制 is_optional
            # 这里简单返回 TextStrategy(str)
            return TextStrategy(name, False, "str", tooltip)
            
        raise ValueError(f"Unknown special type: {special_type}")
