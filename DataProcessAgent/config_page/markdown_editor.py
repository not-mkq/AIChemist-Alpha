#!/usr/bin/env python3
"""
markdown_editor.py

Markdown 编辑器组件
"""

from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit
from PyQt6.QtGui import QFont, QTextDocument

from i18n import tr

try:
    from api_client import ApiClient
    from ui_theme import apply_card_shadow
except ImportError:
    # 如果从主文件导入
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from api_client import ApiClient
    from ui_theme import apply_card_shadow


class MarkdownEditor(QWidget):
    """Markdown 编辑器（简化版，使用 QTextEdit）"""
    
    def __init__(self, api_client: ApiClient, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.current_instance_name: Optional[str] = None
        self.is_new_tool = False
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        label = QLabel(tr("label_comment_markdown"))
        label.setFont(QFont("Source Sans 3", 16, QFont.Weight.Bold))
        layout.addWidget(label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(tr("placeholder_markdown"))
        layout.addWidget(self.text_edit)
        
        self.setLayout(layout)
        apply_card_shadow(self)

    def _set_markdown_safe(self, text: str):
        """Sets markdown content with HTML parsing disabled."""
        if not text:
            self.text_edit.clear()
            return
        
        # Use MarkdownNoHTML to prevent <tags> from being interpreted as HTML
        features = QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML
        self.text_edit.document().setMarkdown(text, features)
    
    def load_comment(self, instance_name: Optional[str], tool_type: str, code_name: Optional[str], is_new: bool):
        """加载注释"""
        self.current_instance_name = instance_name
        self.is_new_tool = is_new
        
        self.text_edit.blockSignals(True)
        try:
            if is_new and code_name:
                # 新建工具：显示代码级别的注释
                comment = self.api_client.get_tool_code_comment(code_name)
                self._set_markdown_safe(comment or "")
            elif instance_name:
                # 已有工具：显示实例级别的注释
                data = self.api_client.get_tool_instance(instance_name)
                comment = data.get("comment")
                self._set_markdown_safe(comment or "")
            else:
                self.text_edit.clear()
        except Exception as e:
            self.text_edit.setPlainText(f"{tr('msg_load_comment_failed')}: {e}")
        finally:
            self.text_edit.blockSignals(False)
    
    def get_comment(self) -> str:
        """获取当前注释"""
        # Note: toMarkdown() usually returns strict Markdown, but might lose the NoHTML intent if re-parsed.
        # However, for saving comments, we just want the text content back.
        # The user's input (if they edited it) is now in the document.
        # toMarkdown() converts the document structure back to Markdown text.
        return self.text_edit.toMarkdown().strip()
