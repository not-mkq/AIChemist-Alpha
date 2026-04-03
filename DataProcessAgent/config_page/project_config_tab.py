#!/usr/bin/env python3
"""
project_config_tab.py

运行工具页面（原项目配置 Tab，已改为直接编辑全局工具实例配置）
- 顶部：项目下拉框、导入zip按钮、当前项目名称
- 中栏：工具配置（下拉菜单选择工具、配置表单）
- 右栏：运行工具实例
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSplitter, QMessageBox,
    QGroupBox, QFormLayout, QTextEdit,
    QInputDialog, QStyle, QSizePolicy, QScrollArea
)
try:
    from widgets import NoWheelComboBox
except ImportError:
    from .widgets import NoWheelComboBox

from i18n import tr
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6 import sip
from typing import Optional, Dict, Any
import logging
import re
import json
import uuid
import threading
import sys

try:
    from api_client import ApiClient
    from tool_config_widget import ToolConfigWidget
    from ui_theme import apply_card_shadow
except ImportError:
    from .api_client import ApiClient
    from .tool_config_widget import ToolConfigWidget
    from .ui_theme import apply_card_shadow

# 确保 ToolConfigWidget 存在
if 'ToolConfigWidget' not in locals():
    ToolConfigWidget = None

# 确保日志配置（如果主程序没有配置）
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ProjectConfigTab(QWidget):
    """运行工具页面（直接编辑全局工具实例配置）"""
    project_changed = pyqtSignal(str)
    tool_run_completed = pyqtSignal(str)  # 工具运行完成信号，参数为项目名
    tool_config_updated = pyqtSignal(str)  # 工具配置已更新信号，参数为工具名
    
    def __init__(self, api_client: ApiClient, project_context, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.project_context = project_context
        self.current_tool_name: Optional[str] = None
        self.current_tool_comment: Optional[str] = None  # 缓存工具注释，避免保存时丢失
        self.main_window = parent  # 保存主窗口引用，用于访问tool_instance_tab
        
        self.project_context.project_list_changed.connect(self.load_projects)
        self.project_context.current_project_changed.connect(self.on_context_project_changed)
        
        self.setup_ui()
        self.load_projects()
        self.load_directories()
        # 延迟加载工具列表，确保工具实例配置页面已初始化
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self.load_project_tools)

    @property
    def current_project(self) -> Optional[str]:
        return self.project_context.current_project

    @property
    def local_projects(self) -> set[str]:
        return self.project_context.local_projects

    def on_templates_loaded(self):
        """模板重载后刷新代码下拉缓存并更新工具列表"""
        # 刷新目录列表（可能新增了目录）
        self.load_directories()
        current_tool = self.tool_combo.currentText()
        # 模板/实例变更后需要刷新工具下拉，确保新注册的实例可见
        self.load_project_tools()
        if current_tool:
            idx = self.tool_combo.findText(current_tool)
            if idx >= 0:
                self.tool_combo.setCurrentIndex(idx)
        if hasattr(self.config_widget, "refresh_tool_codes"):
            self.config_widget.refresh_tool_codes()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 顶部：项目选择和控制
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # 项目下拉框
        project_label = QLabel(tr("project"))
        self.project_combo = NoWheelComboBox()
        self.project_combo.setAccessibleName("项目选择")
        self.project_combo.currentTextChanged.connect(self.on_project_changed)
        top_layout.addWidget(project_label)
        top_layout.addWidget(self.project_combo)

        # 新建项目（仅前端占位，导入 ZIP 后才真正创建）
        new_project_btn = QPushButton(f"{tr('btn_new_project')}(FE Only)")
        new_project_btn.setProperty("variant", "secondary")
        new_project_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        new_project_btn.clicked.connect(self.new_project_placeholder)
        top_layout.addWidget(new_project_btn)
        
        # 导入zip按钮
        import_btn = QPushButton(tr("btn_import_zip"))
        import_btn.setProperty("variant", "primary")
        import_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        import_btn.clicked.connect(self.import_zip)
        top_layout.addWidget(import_btn)

        export_btn = QPushButton("导出 ZIP") # Assume this is another btn I might need to translate later
        export_btn.setProperty("variant", "secondary")
        export_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        export_btn.clicked.connect(self.export_zip)
        top_layout.addWidget(export_btn)
        
        # 当前项目名称显示
        top_layout.addStretch()
        self.project_name_label = QLabel(tr("current_project").format(tr("none")))
        self.project_name_label.setFont(QFont("Source Sans 3", 14, QFont.Weight.Bold))
        top_layout.addWidget(self.project_name_label)
        
        top_bar = QWidget()
        top_bar.setLayout(top_layout)
        top_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(top_bar)
        
        # 中下部：双栏布局
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 中栏：工具配置
        center_panel = QGroupBox(tr("tool_config"))
        center_layout = QVBoxLayout()
        center_layout.setSpacing(8)
        center_layout.setContentsMargins(8, 8, 8, 8)
        
        # 工具选择和操作按钮
        tool_header_layout = QHBoxLayout()
        
        # 工具目录选择
        dir_label = QLabel(tr("directory"))
        self.tool_directory_combo = NoWheelComboBox(self)
        self.tool_directory_combo.setAccessibleName("工具目录选择")
        self.tool_directory_combo.setMinimumWidth(100)
        self.tool_directory_combo.currentTextChanged.connect(self.on_tool_directory_changed)
        tool_header_layout.addWidget(dir_label)
        tool_header_layout.addWidget(self.tool_directory_combo)
        
        tool_label = QLabel(tr("tool"))
        self.tool_combo = NoWheelComboBox(self)
        self.tool_combo.setAccessibleName("工具选择")
        self.tool_combo.currentTextChanged.connect(self.on_tool_changed)
        tool_header_layout.addWidget(tool_label)
        tool_header_layout.addWidget(self.tool_combo)
        
        # 保存状态提示放在标题旁
        self.unsaved_label = QLabel(tr("saved"))
        self.unsaved_label.setProperty("badge", "success")
        tool_header_layout.addWidget(self.unsaved_label)

        center_layout.addLayout(tool_header_layout)
        
        # 显示当前目录（从工具实例配置页面获取）
        self.directory_label = QLabel(f"{tr('directory')} ({tr('none')})")
        self.directory_label.setProperty("hint", "muted")
        center_layout.addWidget(self.directory_label)
        
        # 配置表单容器（用于切换普通工具和meta工具树）
        self.config_container = QWidget()
        self.config_container_layout = QVBoxLayout()
        self.config_container_layout.setContentsMargins(0, 0, 0, 0)
        self.config_container.setLayout(self.config_container_layout)
        
        # 普通工具配置表单（使用 ToolConfigWidget，直接编辑全局工具实例配置）
        if ToolConfigWidget:
            # 创建回调函数
            def get_comment():
                # 工具配置不需要注释
                return ""
            
            def on_save_success():
                # 保存成功后刷新工具列表（如果需要）
                pass
            
            # 创建 ToolConfigWidget，但隐藏实例名称字段
            self.config_widget = ToolConfigWidget(
                api_client=self.api_client,
                get_comment_callback=get_comment,
                on_save_success_callback=on_save_success,
                enable_comments=False,
                hidden_sections={"input_label_map", "output_file_label", "result_col"},
                label_from_comment=True,
                lock_list_row_controls=True,
            )
            # 隐藏内部的保存状态标签（上方已有全局提示）
            if getattr(self.config_widget, "save_status_label", None):
                self.config_widget.save_status_label.hide()
            # 隐藏实例名称字段（工具配置直接编辑全局实例，不需要修改实例名）
            self.config_widget.instance_name_edit.setVisible(False)
            # 隐藏基本信息面板（工具类型和工具代码应该在实例配置页面修改，这里只调整参数）
            if hasattr(self.config_widget, "basic_group"):
                self.config_widget.basic_group.setVisible(False)
            # 隐藏删除和导出按钮（工具配置不需要）
            # 修改保存按钮文本和逻辑
            self.config_widget.save_btn.setText(tr("btn_save_tool_config"))
            # 断开原有的保存连接，连接自定义的保存逻辑
            self.config_widget.save_btn.clicked.disconnect()
            self.config_widget.save_btn.clicked.connect(self.save_current_tool_config)
            
            # 重置按钮改为从全局工具实例配置重新加载当前工具
            self.config_widget.reset_btn.clicked.disconnect()
            self.config_widget.reset_btn.clicked.connect(self.reset_current_tool_config)
            # 监听表单变化
            try:
                self.config_widget.form_changed.connect(self.mark_unsaved)
            except Exception:
                pass
            self.config_container_layout.addWidget(self.config_widget)
        
        # Meta工具树形配置组件
        try:
            from meta_tool_tree_widget import MetaToolTreeWidget
            self.meta_tree_widget = MetaToolTreeWidget(self.api_client, self)
            self.meta_tree_widget.setVisible(False)
            # 监听meta工具树中的表单变化，更新保存状态
            try:
                self.meta_tree_widget.form_changed.connect(self.mark_unsaved)
                self.meta_tree_widget.reset_completed.connect(self.mark_saved)
            except Exception:
                pass
            self.config_container_layout.addWidget(self.meta_tree_widget)
        except ImportError as e:
            logger.warning(f"无法导入MetaToolTreeWidget: {e}")
            self.meta_tree_widget = None
        
        center_layout.addWidget(self.config_container)
        
        center_panel.setLayout(center_layout)
        apply_card_shadow(center_panel)
        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        center_scroll.setWidget(center_panel)
        main_splitter.addWidget(center_scroll)
        
        # 右栏：运行工具实例
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(8, 8, 8, 8)
        
        # Scope 选择
        scope_group = QGroupBox("Scope")
        scope_layout = QFormLayout()

        self.scope_combo = NoWheelComboBox()
        self.scope_combo.setAccessibleName("Scope Selection")
        self.scope_combo.setMinimumWidth(200)
        self.scope_combo.currentTextChanged.connect(self.on_scope_changed)
        scope_layout.addRow(tr("scope"), self.scope_combo)
        
        scope_group.setLayout(scope_layout)
        right_layout.addWidget(scope_group)
        
        # Batch/Item 选择（动态显示）
        self.batch_item_group = QGroupBox(tr("batch_item_group"))
        self.batch_item_layout = QFormLayout()
        
        self.batch_combo = NoWheelComboBox()
        self.item_combo = NoWheelComboBox()
        self.batch_combo.setAccessibleName("Batch Selection")
        self.item_combo.setAccessibleName("Item Selection")
        
        self.batch_item_layout.addRow(tr("batch"), self.batch_combo)
        self.batch_item_layout.addRow(tr("item"), self.item_combo)
        
        self.batch_item_group.setLayout(self.batch_item_layout)
        self.batch_item_group.setVisible(False)  # 默认隐藏
        right_layout.addWidget(self.batch_item_group)


        # 检查状态 + 按钮
        self.check_status_label = QLabel(tr("unchecked"))
        self.check_status_label.setProperty("badge", "warn")
        check_btn = QPushButton(tr("btn_check"))
        check_btn.setProperty("variant", "secondary")
        check_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        check_btn.clicked.connect(self.run_check_only)
        right_layout.addWidget(self.check_status_label)
        right_layout.addWidget(check_btn)
        
        # 运行按钮
        run_btn = QPushButton(tr("btn_run"))
        run_btn.setProperty("variant", "primary")
        run_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        run_btn.clicked.connect(self.run_tool_instance)
        right_layout.addWidget(run_btn)
        
        # 运行结果显示
        result_group = QGroupBox(tr("run_log"))
        result_layout = QVBoxLayout()
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(200)
        result_layout.addWidget(self.result_text)
        
        result_group.setLayout(result_layout)
        right_layout.addWidget(result_group)
        
        right_layout.addStretch()
        
        right_panel.setLayout(right_layout)
        right_panel.setMinimumWidth(450)  # 300 * 1.5 = 450
        apply_card_shadow(right_panel)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        right_scroll.setWidget(right_panel)
        main_splitter.addWidget(right_scroll)
        
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 1)
        
        layout.addWidget(main_splitter)
        self.setLayout(layout)
    
    def load_projects(self):
        """从 Context 加载项目列表"""
        projects = self.project_context.project_list
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItems(projects)
        
        # 核心改进：在填充列表后，检查 Context 中是否已有“当前项目”
        # 这个项目可能是从 UI 状态恢复过来的，也可能是默认选中的
        current = self.current_project
        if current and current in projects:
            idx = self.project_combo.findText(current)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)
                # 即使 block 了信号，也要手动触发一次同步逻辑（加载批次列表等）
                self.on_context_project_changed(current)
        elif projects:
            # 如果 Context 为空但列表不为空，维持 Combo 的默认行为并同步给 Context
            first_prj = self.project_combo.currentText()
            self.on_project_changed(first_prj)
            
        self.project_combo.blockSignals(False)
        
        # 刷新按钮状态等（如果需要）

    def new_project_placeholder(self):
        """前端占位创建项目名"""
        name, ok = QInputDialog.getText(self, f"{tr('btn_new_project')}(FE Only)", f"{tr('prompt_new_project')}:")
        if ok and name:
            # 校验名称合法性
            if not re.match(r"^[a-zA-Z0-9_\-\+\.]+$", name):
                QMessageBox.warning(self, tr("error"), "Project name only allows letters, numbers, _, -, +, .")
                return
            
            if name in self.local_projects:
                QMessageBox.warning(self, tr("hint"), "Project already exists")
                return
            
            self.project_context.create_local_project(name)

    def on_context_project_changed(self, project_name: str):
        """处理 Context 中的项目变化信号"""
        logger.info(f"监听到项目变化信号: {project_name}")
        idx = self.project_combo.findText(project_name)
        if idx >= 0:
            self.project_combo.setCurrentIndex(idx)
        else:
            self.project_name_label.setText(tr("current_project").format(tr("none")))
        
        # 强制刷新 Batch/Item 列表（如果是 Batch/Item Scope）
        # 即使 Scope 没变，项目内容可能变了（例如刚上传了新 Batch）
        scope = self.scope_combo.currentText()
        logger.info(f"Project changed, scope: {scope}, refreshing batch list if applicable.")
        if scope in ["batch", "item", "item->batch"]:
             self.load_batch_list()
             # 如果是 Item Scope 且已有选中 Batch，也刷新 Item 列表
             if scope == "item" and self.batch_combo.currentText():
                 self.load_item_list(self.batch_combo.currentText())

    def on_project_changed(self, project_name: str):
        """UI 下拉框变更"""
        if sip.isdeleted(self.project_combo):
            return
        self.project_context.set_current_project(project_name)

    def load_directories(self):
        """加载目录列表"""
        try:
            # 记住当前选中的目录名
            current_dir = self.tool_directory_combo.currentData()
            
            directories = self.api_client.get_directories()
            self.tool_directory_combo.blockSignals(True)
            self.tool_directory_combo.clear()
            
            has_default = False
            for directory in directories:
                self.tool_directory_combo.addItem(directory, directory)
                if directory == "default":
                    has_default = True
            
            if not has_default:
                self.tool_directory_combo.addItem("default", "default")
            
            # 尝试恢复之前的选中状态
            if current_dir:
                idx = self.tool_directory_combo.findData(current_dir)
                if idx >= 0:
                    self.tool_directory_combo.setCurrentIndex(idx)
                else:
                    # 如果之前的目录不在新列表中，尝试选中 default
                    idx = self.tool_directory_combo.findData("default")
                    if idx >= 0:
                        self.tool_directory_combo.setCurrentIndex(idx)
                    else:
                        self.tool_directory_combo.setCurrentIndex(0)
            else:
                # 默认选中 default
                idx = self.tool_directory_combo.findData("default")
                if idx >= 0:
                    self.tool_directory_combo.setCurrentIndex(idx)
                elif self.tool_directory_combo.count() > 0:
                    self.tool_directory_combo.setCurrentIndex(0)

            self.tool_directory_combo.blockSignals(False)
        except Exception as e:
            logger.error(f"加载目录列表失败: {e}")

    def on_tool_directory_changed(self, text):
        """目录变更"""
        self.load_project_tools()

    def load_project_tools(self, force_reload: bool = False):
        """加载工具列表（从当前选中的目录）"""
        if sip.isdeleted(self.tool_combo):
            return
        try:
            # 获取当前选中的目录
            idx = self.tool_directory_combo.currentIndex()
            if idx >= 0:
                directory = self.tool_directory_combo.itemData(idx)
                if directory is None:
                    directory = ""
            else:
                directory = "" # 默认 fallback

            logger.info(f"加载工具列表，目录: '{directory}'")
            
            # 更新目录显示
            if hasattr(self, "directory_label"):
                if directory:
                    self.directory_label.setText(f"{tr('directory')} {directory}")
                else:
                    self.directory_label.setText(f"{tr('directory')} ({tr('none')})")
            
            # 加载该目录下的工具（directory为空字符串表示根目录）
            # 如果是根目录，传递 None 给 API 以获取所有工具（递归扫描）
            api_dir = directory if directory else None
            tools_data = self.api_client.get_tools(directory=api_dir)
            all_tools = []
            all_tools.extend(tools_data.get("tools", []))
            all_tools.extend(tools_data.get("merge_tools", []))
            all_tools.extend(tools_data.get("meta_tools", []))
            
            # 记住当前选中的工具名，以便在刷新后恢复
            current_tool = self.tool_combo.currentText() or self.current_tool_name
            
            self.tool_combo.blockSignals(True)
            self.tool_combo.clear()
            self.tool_combo.addItems(all_tools)
            
            if current_tool:
                idx = self.tool_combo.findText(current_tool)
                if idx >= 0:
                    self.tool_combo.setCurrentIndex(idx)
            
            self.tool_combo.blockSignals(False)
            
            # 无论索引是否改变，显式触发一次 on_tool_changed 确保配置同步加载
            new_selection = self.tool_combo.currentText()
            if new_selection:
                # 仅在强制刷新，或工具名确实变了时，才触发 on_tool_changed
                if force_reload or new_selection != self.current_tool_name:
                    self.on_tool_changed(new_selection, force=force_reload)
            elif self.current_tool_name:
                # 如果列表空了，也要重置状态
                self.on_tool_changed("")
        except Exception as e:
            logger.error(f"加载工具列表失败: {e}")
    
    def on_tool_changed(self, tool_name: str, force: bool = False):
        """工具改变时加载全局工具实例配置"""
        logger.info(f"on_tool_changed called with tool_name: '{tool_name}', force: {force}")
        if sip.isdeleted(self.tool_combo):
            return
        
        # 根本修复：当工具名为空（例如列表被清空）时，必须重置内部状态
        if not tool_name:
            logger.info("Tool name is empty, clearing state.")
            self.project_name_label.setText(tr("current_project").format(self.current_project) if self.current_project else tr("current_project").format(tr("none")))
            # 清空依赖于工具的下拉框
            self.scope_combo.clear()
            self.batch_combo.clear()
            self.item_combo.clear()
            # 隐藏配置表单
            if hasattr(self, 'config_widget'):
                self.config_widget.setVisible(False)
            if hasattr(self, 'meta_tree_widget'):
                self.meta_tree_widget.setVisible(False)
            return
        
        # 防止重复调用：如果工具名没有变化且非强制刷新，直接返回
        if not force and self.current_tool_name == tool_name:
            return
        
        self.current_tool_name = tool_name
        
        # 从后端API加载全局工具实例配置
        try:
            tool_instance_data = self.api_client.get_tool_instance(tool_name)
            
            if not tool_instance_data or tool_instance_data.get("status") != "ok":
                logger.warning(f"无法获取工具实例信息: {tool_name}")
                return
            
            tool_type = tool_instance_data.get("tool_type", "single")
            code_name = tool_instance_data.get("code_name")
            config = tool_instance_data.get("config", {})
            self.current_tool_comment = tool_instance_data.get("comment") # 缓存注释
            
            # 如果是meta工具，使用树形配置组件
            if tool_type == "meta" and hasattr(self, 'meta_tree_widget') and self.meta_tree_widget:
                # 隐藏普通配置组件，显示meta树形组件
                if hasattr(self, 'config_widget'):
                    self.config_widget.setVisible(False)
                self.meta_tree_widget.setVisible(True)
                
                # 加载meta工具树
                if not self.meta_tree_widget.load_meta_tool(tool_name):
                    # 加载失败，回退到普通配置组件
                    if hasattr(self, 'config_widget'):
                        self.config_widget.setVisible(True)
                    self.meta_tree_widget.setVisible(False)
                    return
                
                # 标记为已保存
                self.mark_saved()
                # Meta 工具加载成功后，也要刷新 Scope
                self._refresh_scope_by_tool(tool_name)
                return
            
            # 非meta工具，使用普通配置组件
            if hasattr(self, 'meta_tree_widget') and self.meta_tree_widget:
                self.meta_tree_widget.setVisible(False)
            if hasattr(self, 'config_widget'):
                self.config_widget.setVisible(True)
            
            # 加载到 ToolConfigWidget
            if ToolConfigWidget and hasattr(self, 'config_widget'):
                # 按照 load_tool_instance 的方式处理：完全阻止信号，设置值，恢复信号，然后调用 update_config_form
                self.config_widget.tool_type_combo.blockSignals(True)
                self.config_widget.code_name_combo.blockSignals(True)

                try:
                    # 设置工具类型并手动刷新代码列表（信号被阻止，不触发 on_code_changed）
                    self.config_widget.tool_type_combo.setCurrentText(tool_type)
                    if hasattr(self.config_widget, "_load_tool_codes"):
                        self.config_widget._load_tool_codes(tool_type)

                    # 等待代码列表加载完成
                    from PyQt6.QtWidgets import QApplication
                    QApplication.processEvents()

                    # 对于 meta tool，使用 code_name (map/sequence/alt)
                    if tool_type == "meta" and config and "code_name" in config:
                        code_name = config["code_name"]
                        index = self.config_widget.code_name_combo.findText(code_name)
                        if index >= 0:
                            self.config_widget.code_name_combo.setCurrentIndex(index)
                    elif code_name:
                        # Single/Merge tool: 使用 code_name
                        index = self.config_widget.code_name_combo.findText(code_name)
                        if index >= 0:
                            self.config_widget.code_name_combo.setCurrentIndex(index)
                    
                    # 在信号恢复之前，先调用 update_config_form（此时信号仍被阻止）
                    # 这样可以避免恢复信号后触发 on_code_changed
                    if config:
                        self.config_widget.update_config_form(config_data=config)
                    else:
                        # 如果没有配置，显示默认表单
                        self.config_widget.update_config_form()
                    # 加载完成视为已保存状态
                    self.mark_saved()
                finally:
                    # 最后恢复信号（此时 update_config_form 已经完成）
                    self.config_widget.tool_type_combo.blockSignals(False)
                    self.config_widget.code_name_combo.blockSignals(False)
                    # 确保重置后标记为已保存（防止恢复信号后触发form_changed）
                    self.mark_saved()
        except Exception as e:
            logger.error(f"加载工具配置失败: {e}", exc_info=True)
            QMessageBox.warning(self, "错误", f"加载工具配置失败: {e}")
        
        # 无论配置加载是否成功，都尝试刷新 Scope
        # 这样即使表单渲染挂了，至少还能看见 Scope (如果 API 还能工作)
        self._refresh_scope_by_tool(tool_name)
    
    
    def import_zip(self):
        """导入 ZIP 文件"""
        self.project_context.import_zip(self)

    def export_zip(self):
        """导出当前项目为 ZIP"""
        self.project_context.export_zip(self)
    
    def save_current_tool_config(self):
        """保存全局工具实例配置"""
        if not self.current_tool_name:
            QMessageBox.warning(self, "错误", "请先选择工具")
            return
        
        # 如果是meta工具，使用meta_tree_widget的保存方法
        if (hasattr(self, 'meta_tree_widget') and self.meta_tree_widget and 
            self.meta_tree_widget.isVisible()):
            # 调用meta工具树的保存方法
            # MetaToolTreeWidget 保存成功后会发出 reset_completed 信号，从而触发 mark_saved
            self.meta_tree_widget.save_all_tools()
            return
        
        if not ToolConfigWidget or not hasattr(self, 'config_widget'):
            QMessageBox.warning(self, "错误", "配置表单未初始化")
            return

        if hasattr(self.config_widget, "validate_run_param_types"):
            if not self.config_widget.validate_run_param_types(show_message=True, require_instance=False):
                return
        
        # 复用 ToolConfigWidget 构建/校验逻辑（工具配置无需实例名）
        payload = self.config_widget.build_payload(require_instance=False)
        err = self.config_widget.validate_payload(payload, require_instance=False)
        if err:
            QMessageBox.warning(self, "错误", err)
            return
        
        payload.get("tool_type")
        payload.get("code_name")
        config = payload.get("config", {})
        
        # 构建保存到全局工具实例的 body（后端只接受 config 和 comment）
        body = {
            "config": config,
            "comment": self.current_tool_comment,  # 使用缓存的注释，避免丢失
        }
        
        # 保存到全局工具实例配置
        try:
            self.api_client.update_tool_instance(self.current_tool_name, body)
            # 同步导出到文件
            try:
                export_res = self.api_client.export_tool_instance(self.current_tool_name)
                if export_res.get("status") != "ok":
                    logger.warning(f"导出文件失败: {export_res}")
            except Exception as exp:
                logger.warning(f"导出文件失败: {exp}")
            QMessageBox.information(self, "成功", f"工具 '{self.current_tool_name}' 配置已保存")
        except Exception as e:
            logger.error(f"保存工具配置失败: {e}", exc_info=True)
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
        else:
            self.mark_saved()
            self.tool_config_updated.emit(self.current_tool_name)

    def reset_current_tool_config(self):
        """重置当前工具配置为已保存的全局配置"""
        if not self.current_tool_name:
            QMessageBox.information(self, "提示", "请先选择工具")
            return
        
        # 先标记为已保存，避免重置过程中触发form_changed导致状态错误
        self.mark_saved()
        
        # 通过清空当前工具名再触发加载，绕过重复选择判断
        tool_name = self.current_tool_name
        self.current_tool_name = None
        self.on_tool_changed(tool_name)
        
        # 确保重置后标记为已保存（on_tool_changed中也会调用mark_saved，但这里确保一下）
        self.mark_saved()

    def mark_unsaved(self):
        """标记当前配置未保存"""
        if hasattr(self, "unsaved_label"):
            self.unsaved_label.setText(tr("unsaved"))
            self.unsaved_label.setProperty("badge", "warn")
            self.unsaved_label.style().unpolish(self.unsaved_label)
            self.unsaved_label.style().polish(self.unsaved_label)
        if hasattr(self, "config_widget") and hasattr(self.config_widget, "mark_unsaved"):
            self.config_widget.mark_unsaved()

    def mark_saved(self):
        """标记当前配置已保存"""
        if hasattr(self, "unsaved_label"):
            self.unsaved_label.setText(tr("saved"))
            self.unsaved_label.setProperty("badge", "success")
            self.unsaved_label.style().unpolish(self.unsaved_label)
            self.unsaved_label.style().polish(self.unsaved_label)
        if hasattr(self, "config_widget") and hasattr(self.config_widget, "mark_saved"):
            self.config_widget.mark_saved()
        # 同时重置 meta_tree_widget 中的所有工具状态
        if hasattr(self, "meta_tree_widget") and hasattr(self.meta_tree_widget, "config_widgets"):
            for cw in self.meta_tree_widget.config_widgets.values():
                if hasattr(cw, "mark_saved"):
                    cw.mark_saved()
    
    def load_batch_list(self):
        """加载批次列表"""
        if not self.current_project or sip.isdeleted(self.batch_combo):
            logger.warning("load_batch_list skipped: project not set or combo deleted")
            return
        
        try:
            # 从文件树数据中获取批次列表
            logger.info(f"Loading batch list for project: {self.current_project}")
            tree_data = self.api_client.get_project_file_tree(self.current_project)
            logger.info(f"Got tree data keys: {tree_data.keys() if tree_data else 'None'}")
            if tree_data:
                batches = [batch["batch_name"] for batch in tree_data.get("batches", [])]
                logger.info(f"Found batches: {batches}")
                self.batch_combo.clear()
                self.batch_combo.addItems(batches)
        except Exception as e:
            logger.error(f"加载批次列表失败: {e}")
    
    def load_item_list(self, batch_name: str):
        """加载项目项列表"""
        if not self.current_project or not batch_name or sip.isdeleted(self.item_combo):
            return
        
        try:
            tree_data = self.api_client.get_project_file_tree(self.current_project)
            if tree_data:
                for batch_info in tree_data.get("batches", []):
                    if batch_info["batch_name"] == batch_name:
                        items = [item["item_name"] for item in batch_info.get("items", [])]
                        self.item_combo.clear()
                        self.item_combo.addItems(items)
                        return
        except Exception as e:
            logger.error(f"加载项目项列表失败: {e}")
    
    def on_scope_changed(self, scope: str):
        """Scope 改变时更新 batch/item 显示"""
        if not scope:
            self.batch_item_group.setVisible(False)
            return
        
        # 根据 scope 决定显示哪些字段
        if scope == "project":
            # project scope: 不需要 batch 和 item
            self.batch_item_group.setVisible(False)
        elif scope == "batch":
            # batch scope: 需要 batch
            self.batch_item_group.setVisible(True)
            self.batch_combo.setVisible(True)
            self.item_combo.setVisible(False)
            # 更新批次列表
            self.load_batch_list()
        elif scope == "item":
            # item scope: 需要 batch 和 item
            self.batch_item_group.setVisible(True)
            self.batch_combo.setVisible(True)
            self.item_combo.setVisible(True)
            # 更新批次列表
            self.load_batch_list()
            # 如果已选择批次，更新项目项列表
            if self.batch_combo.currentText():
                self.load_item_list(self.batch_combo.currentText())
        elif scope in ["item->batch", "item->project"]:
            # merge scope: item->batch 需要 batch, item->project 不需要
            if scope == "item->batch":
                self.batch_item_group.setVisible(True)
                self.batch_combo.setVisible(True)
                self.item_combo.setVisible(False)
                self.load_batch_list()
            else:  # item->project
                self.batch_item_group.setVisible(False)
        elif scope == "batch->project":
            # batch->project scope: 不需要 batch 和 item
            self.batch_item_group.setVisible(False)
        
        # 连接批次改变事件，更新项目项列表
        try:
            self.batch_combo.currentTextChanged.disconnect()
        except:
            pass
        if scope == "item":
            self.batch_combo.currentTextChanged.connect(self.on_batch_changed_for_item)

    def _refresh_scope_by_tool(self, tool_name: str):
        """根据工具类型刷新可选 scope，依赖中栏选中的工具"""
        logger.info(f"_refresh_scope_by_tool called for: {tool_name}")
        if not tool_name or sip.isdeleted(self.scope_combo):
            return
        
        # 保存当前的 batch 和 item 选择
        saved_batch = self.batch_combo.currentText() if not sip.isdeleted(self.batch_combo) else ""
        saved_item = self.item_combo.currentText() if not sip.isdeleted(self.item_combo) else ""
        saved_scope = self.scope_combo.currentText() if not sip.isdeleted(self.scope_combo) else ""
        
        try:
            tool_instance_data = self.api_client.get_tool_instance(tool_name)
            if not tool_instance_data or tool_instance_data.get("status") != "ok":
                return

            tool_type = tool_instance_data.get("tool_type", "single")
            config = tool_instance_data.get("config", {})

            self.scope_combo.clear()
            if tool_type == "single":
                scopes = ["item", "batch", "project"]
            elif tool_type == "merge":
                scopes = ["item->batch", "item->project", "batch->project"]
            elif tool_type == "meta":
                mode = config.get("code_name", "map")
                if mode == "map":
                    # Map mode only supports backend scopes
                    scopes = ["item->batch", "batch->project", "item->project"]
                else:
                    # sequence/alt 使用与 Sequence 一致的 scope（item/batch/project）
                    scopes = ["item", "batch", "project"]
            else:
                scopes = []
            
            if scopes:
                self.scope_combo.addItems(scopes)
                
                # 尝试恢复之前的 scope（如果新工具类型支持）
                if saved_scope in scopes:
                    self.scope_combo.setCurrentText(saved_scope)
                else:
                    # 如果之前的 scope 不支持，使用第一个可用的 scope
                    self.scope_combo.setCurrentIndex(0)
                
                # 调用 on_scope_changed 更新 UI，但先阻止信号以避免清空选择
                self.batch_combo.blockSignals(True)
                self.item_combo.blockSignals(True)
                try:
                    self.on_scope_changed(self.scope_combo.currentText())
                    
                    # 恢复 batch 选择（如果存在且在新列表中）
                    if saved_batch and saved_batch in [self.batch_combo.itemText(i) for i in range(self.batch_combo.count())]:
                        self.batch_combo.setCurrentText(saved_batch)
                        # 如果 scope 是 item，还需要恢复 item 选择
                        if self.scope_combo.currentText() == "item" and saved_item:
                            self.load_item_list(saved_batch)
                            if saved_item in [self.item_combo.itemText(i) for i in range(self.item_combo.count())]:
                                self.item_combo.setCurrentText(saved_item)
                finally:
                    self.batch_combo.blockSignals(False)
                    self.item_combo.blockSignals(False)
        except Exception as e:
            logger.error(f"加载工具类型失败: {e}", exc_info=True)
    
    def on_batch_changed_for_item(self, batch_name: str):
        """批次改变时更新项目项列表（用于 item scope）"""
        self.load_item_list(batch_name)
    
    def _build_run_args(self):
        if not self.current_project:
            QMessageBox.warning(self, "错误", "请先选择项目")
            return None
        
        tool_name = self.tool_combo.currentText()
        if not tool_name:
            QMessageBox.warning(self, "错误", "请先选择工具实例")
            return None
        
        scope = self.scope_combo.currentText()
        if not scope:
            QMessageBox.warning(self, "错误", "请先选择 Scope")
            return None
        
        # 根据 scope 获取 batch 和 item
        batch = None
        item = None
        
        if scope == "batch":
            batch = self.batch_combo.currentText()
            if not batch:
                QMessageBox.warning(self, "错误", "请选择批次")
                return None
        elif scope == "item":
            batch = self.batch_combo.currentText()
            item = self.item_combo.currentText()
            if not batch or not item:
                QMessageBox.warning(self, "错误", "请选择批次和项目项")
                return None
        elif scope == "item->batch":
            batch = self.batch_combo.currentText()
            if not batch:
                QMessageBox.warning(self, "错误", "请选择批次")
                return None

        return {
            "project": self.current_project,
            "tool": tool_name,
            "scope": scope,
            "batch": batch,
            "item": item,
        }

    def _set_check_status(self, text: str, badge: str) -> None:
        """更新可行性检查徽标"""
        self.check_status_label.setText(tr(text.lower().replace(" ", "_")))
        self.check_status_label.setProperty("badge", badge)
    
    def run_check_only(self):
        """仅执行可行性检查"""
        args = self._build_run_args()
        if not args:
            return
        self._perform_run_check(args, show_message=True)

    def _perform_run_check(self, args: dict, show_message: bool) -> bool:
        try:
            result = self.api_client.check_tool_before_run(**args)
        except Exception as e:
            logger.error(f"运行前检查失败: {e}", exc_info=True)
            if show_message:
                self.result_text.clear()
                self.result_text.append(f"检查失败: {e}")
                # 滚动到顶部
                cursor = self.result_text.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                self.result_text.setTextCursor(cursor)
            self._set_check_status("检查失败", "warn")
            return False

        if result.get("status") == "ok":
            self._set_check_status("可运行", "success")
            if show_message:
                self.result_text.clear()
                self.result_text.append("检查通过，准备运行。")
                # 滚动到顶部
                cursor = self.result_text.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                self.result_text.setTextCursor(cursor)
            return True

        reason = result.get("reason", "unknown")
        detail_lines = [f"原因: {reason}"]
        if result.get("missing_labels"):
            detail_lines.append(f"缺失标签: {result.get('missing_labels')}")
        if result.get("missing_item_results"):
            detail_lines.append(f"缺失结果列: {result.get('missing_item_results')}")
        if result.get("iteration_index") is not None:
            detail_lines.append(f"迭代索引: {result.get('iteration_index')}")
        if result.get("missing_input_details"):
            detail_lines.append("缺失输入详情:")
            for entry in result.get("missing_input_details") or []:
                detail_lines.append(
                    f"  - {entry.get('param', '?')}: {entry.get('label', '')}"
                )
        if result.get("missing_result_details"):
            detail_lines.append("缺失结果列详情:")
            for entry in result.get("missing_result_details") or []:
                detail_lines.append(
                    f"  - {entry.get('param', '?')}: {entry.get('column', '')}"
                )
        if result.get("missing_results"):
            detail_lines.append(f"缺失结果: {result.get('missing_results')}")
        if result.get("detail"):
            detail_lines.append(f"详情: {result.get('detail')}")
        msg = "\n".join(detail_lines)
        if show_message:
            self.result_text.clear()
            self.result_text.append("检查未通过！\n")
            self.result_text.append(msg)
            # 滚动到顶部
            cursor = self.result_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.result_text.setTextCursor(cursor)
        self._set_check_status("不可运行", "warn")
        return False
    
    def run_tool_instance(self):
        """运行工具实例（带实时进度条，加固版）"""
        if not self.current_project:
            QMessageBox.warning(self, "错误", "请先选择项目")
            return
        if not self.current_tool_name:
            QMessageBox.warning(self, "错误", "请先选择工具")
            return
        
        scope = self.scope_combo.currentText()
        batch = self.batch_combo.currentText() if self.batch_combo.isVisible() else None
        item = self.item_combo.currentText() if self.item_combo.isVisible() else None
        
        # --- [修复] 运行前强制执行一次检查 ---
        run_args = self._build_run_args()
        if not run_args or not self._perform_run_check(run_args, show_message=True):
            return
        
        # 1. 状态准备
        run_id = str(uuid.uuid4())
        self.result_text.setPlainText(f"正在启动任务...\nRun ID: {run_id}")
        self._last_run_result = None
        
        # 2. 启动后台任务
        def _bg_run():
            try:
                res = self.api_client.run_tool(
                    project=self.current_project,
                    tool=self.current_tool_name,
                    scope=scope,
                    batch=batch,
                    item=item,
                    run_id=run_id
                )
                self._last_run_result = res
            except Exception as e:
                logger.error(f"后台线程报错: {e}", exc_info=True)
                self._last_run_result = {"status": "error", "reason": "thread_exception", "detail": str(e)}

        bg_thread = threading.Thread(target=_bg_run, daemon=True)
        bg_thread.start()
        
        # 3. 启动进度轮询
        if hasattr(self, "_progress_timer") and self._progress_timer:
            self._progress_timer.stop()
            self._progress_timer.deleteLater()
            
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(500)
        
        def _poll():
            if sip.isdeleted(self):
                return

            try:
                # A. 任务完成处理
                if self._last_run_result is not None:
                    self._progress_timer.stop()
                    # 记录状态
                    self._display_final_result(self._last_run_result)
                    # 发出完成信号
                    self.tool_run_completed.emit(self.current_project or "")
                    return
                
                # B. 轮询进度
                progress = self.api_client.get_run_progress(run_id)
                if progress.get("status") == "ok":
                    percent = progress.get("percent", 0)
                    msg = progress.get("message", "正在执行...")
                    
                    bar_len = 20
                    filled_len = int(bar_len * percent // 100)
                    bar = "█" * filled_len + "░" * (bar_len - filled_len)
                    
                    output = [
                        f"任务正在执行 [Run ID: {run_id}]",
                        f"进度: {bar} {percent}%",
                        f"状态: {msg}",
                        "\n(请稍候...)"
                    ]
                    self.result_text.setPlainText("\n".join(output))
            except Exception as e:
                # 轮询中的任何异常都不应导致程序退出
                logger.debug(f"进度轮询非致命异常: {e}")
        
        self._progress_timer.timeout.connect(_poll)
        self._progress_timer.start()

    def _display_final_result(self, result: Dict[str, Any]):
        """显示最终运行结果"""
        self.result_text.clear()
        # 使用健壮的渲染逻辑展示详情
        self._render_run_result(result)
        
        if result.get("status") == "ok":
            self.check_status_label.setText("运行成功")
            self.check_status_label.setProperty("badge", "success")
        else:
            self.check_status_label.setText("运行失败")
            self.check_status_label.setProperty("badge", "danger")
        self.check_status_label.style().unpolish(self.check_status_label)
        self.check_status_label.style().polish(self.check_status_label)

    def _render_run_result(self, result: Dict[str, Any]) -> None:
        """统一展示运行结果/错误/回滚信息。"""

        status = result.get("status")
        if status == "ok":
            self.result_text.append("运行成功！\n")
        else:
            self.result_text.append("运行失败！\n")
            reason = result.get("reason") or "unknown"
            detail = result.get("detail") or ""
            self.result_text.append(f"原因: {reason}")
            if detail:
                self.result_text.append(f"详情: {detail}")
            if result.get("missing_labels"):
                self.result_text.append(f"缺失标签: {result.get('missing_labels')}")
            if result.get("missing_item_results"):
                self.result_text.append(f"缺失结果列: {result.get('missing_item_results')}")
            if result.get("iteration_index") is not None:
                self.result_text.append(f"迭代索引: {result.get('iteration_index')}")
            if result.get("missing_input_details"):
                self.result_text.append("缺失输入详情:")
                for entry in result.get("missing_input_details") or []:
                    self.result_text.append(
                        f"  - {entry.get('param', '?')}: {entry.get('label', '')}"
                    )
            if result.get("missing_result_details"):
                self.result_text.append("缺失结果列详情:")
                for entry in result.get("missing_result_details") or []:
                    self.result_text.append(
                        f"  - {entry.get('param', '?')}: {entry.get('column', '')}"
                    )
            rollback = result.get("rollback") or {}
            if rollback:
                db_rb = rollback.get("db") or {}
                ws_rb = rollback.get("workspace") or {}
                self.result_text.append(f"DB回滚: {db_rb.get('status', 'n/a')} ({db_rb.get('reason','') or db_rb.get('restored_from','')})")
                self.result_text.append(f"Workspace回滚: {ws_rb.get('status', 'n/a')} ({ws_rb.get('reason','') or ws_rb.get('rollback_to','')})")

        # 总是附带 run_id 和 snapshot 信息便于调试
        run_id = result.get("run_id")
        if run_id:
            self.result_text.append(f"run_id: {run_id}")
        snapshot = result.get("run_snapshot")
        if snapshot:
            self.result_text.append("运行快照:")
            self.result_text.append(json.dumps(snapshot, ensure_ascii=False, indent=2))
