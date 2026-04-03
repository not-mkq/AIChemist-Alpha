#!/usr/bin/env python3
"""
tool_context.py

工具上下文管理：
- 管理当前目录 (current_directory)
- 管理当前选中的工具实例 (current_instance)
- 协调工具列表的加载
- 发出目录/实例变更信号
"""

import logging
from typing import Optional, List
from PyQt6.QtCore import QObject, pyqtSignal

from api_client import ApiClient

logger = logging.getLogger(__name__)


class ToolContext(QObject):
    """工具上下文管理器"""

    # 信号
    directory_list_changed = pyqtSignal(list)
    directory_changed = pyqtSignal(str)
    tool_list_changed = pyqtSignal(dict)  # 发送完整的 tools_data
    instance_selected = pyqtSignal(str, dict)  # (instance_name, instance_data)
    instance_saved = pyqtSignal(str)  # instance_name

    def __init__(self, api_client: ApiClient, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        
        self._current_directory: str = "default"
        self._directories: List[str] = []
        self._current_instance_name: Optional[str] = None

    @property
    def current_directory(self) -> str:
        return self._current_directory

    @property
    def current_instance_name(self) -> Optional[str]:
        return self._current_instance_name

    def load_directories(self) -> None:
        """从后端加载目录列表"""
        try:
            directories = self.api_client.get_directories()
            if "default" not in directories:
                # 兼容性：确保 default 始终在列表中
                directories = sorted(list(set(directories + ["default"])))
            
            self._directories = directories
            self.directory_list_changed.emit(directories)
            
            # 验证当前目录是否仍然有效
            if self._current_directory not in self._directories:
                self.set_directory("default")
        except Exception as e:
            logger.error(f"加载目录失败: {e}")

    def set_directory(self, directory: str) -> None:
        """切换目录"""
        if self._current_directory == directory:
            return
            
        self._current_directory = directory
        logger.info(f"ToolContext: 目录变更为 '{directory}'")
        self.directory_changed.emit(directory)
        self.load_tools()

    def load_tools(self) -> None:
        """加载当前目录下的工具列表"""
        try:
            # directory=None 对应根目录，这里保持 current_directory 为字符串
            api_dir = self._current_directory if self._current_directory else None
            tools_data = self.api_client.get_tools(directory=api_dir)
            self.tool_list_changed.emit(tools_data)
        except Exception as e:
            logger.error(f"加载工具列表失败: {e}")
            # 这里抛出异常以便 UI 层捕获并显示错误对话框
            raise e

    def select_instance(self, instance_name: str) -> None:
        """选中某个工具实例"""
        try:
            data = self.api_client.get_tool_instance(instance_name)
            if data.get("status") == "ok":
                self._current_instance_name = instance_name
                self.instance_selected.emit(instance_name, data)
            else:
                logger.warning(f"无法选中实例 {instance_name}: {data.get('reason')}")
        except Exception as e:
            logger.error(f"加载实例详情失败: {e}")

    def notify_instance_saved(self, instance_name: str) -> None:
        """通知实例已保存（通常由 ToolConfigWidget 调用成功后触发）"""
        self.instance_saved.emit(instance_name)
        # 保存后可能涉及目录结构变化或列表刷新
        self.load_directories()
        self.load_tools()
