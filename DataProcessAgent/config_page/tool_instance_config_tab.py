#!/usr/bin/env python3
"""
tool_instance_config_tab.py

工具实例配置 Tab（三栏布局：工具列表、配置表单、Markdown编辑器）
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QLabel, QSplitter, QMessageBox, QGroupBox, QStyle, QScrollArea
)
from widgets import NoWheelComboBox
from PyQt6.QtCore import Qt, pyqtSignal
import logging

from i18n import tr
try:
    from api_client import ApiClient
    from tool_config_widget import ToolConfigWidget
    from markdown_editor import MarkdownEditor
    from ui_theme import apply_card_shadow
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from api_client import ApiClient
    from tool_config_widget import ToolConfigWidget
    from markdown_editor import MarkdownEditor
    from ui_theme import apply_card_shadow

logger = logging.getLogger(__name__)


class ToolInstanceConfigTab(QWidget):
    """工具实例配置 Tab"""
    tool_saved = pyqtSignal()  # 工具保存成功信号
    
    def __init__(self, api_client: ApiClient, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.current_directory = "default"  # 默认选中 default 目录
        self.setup_ui()
        self.load_directories()
        self.load_tools()
    
    def setup_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 左栏：工具列表
        left_panel = QGroupBox(tr("tool_list"))
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        
        # 目录选择器
        dir_label = QLabel(tr("directory"))
        self.directory_combo = NoWheelComboBox()
        self.directory_combo.currentTextChanged.connect(self.on_directory_changed)
        left_layout.addWidget(dir_label)
        left_layout.addWidget(self.directory_combo)
        
        self.tool_list = QListWidget()
        self.tool_list.itemClicked.connect(self.on_tool_selected)
        self.tool_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 改善滚动条和边框的观感，避免列表过长时出现黑线
        self.tool_list.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #d7dbe3;
                border-radius: 8px;
                padding: 6px;
                background: #ffffff;
            }
            QListWidget::item {
                padding: 8px 10px;
            }
            QListWidget::item:selected {
                background: rgba(47, 125, 225, 0.12);
            }
            """
        )
        left_layout.addWidget(self.tool_list)
        
        new_btn = QPushButton(tr("btn_new_tool"))
        new_btn.setProperty("variant", "secondary")
        new_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        new_btn.clicked.connect(self.new_tool)
        left_layout.addWidget(new_btn)
        
        copy_new_btn = QPushButton(tr("btn_copy_new"))
        copy_new_btn.setProperty("variant", "secondary")
        copy_new_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        copy_new_btn.clicked.connect(self.copy_new_tool)
        left_layout.addWidget(copy_new_btn)
        
        refresh_btn = QPushButton(tr("btn_refresh"))
        refresh_btn.setProperty("variant", "ghost")
        refresh_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        def refresh_all():
            self.load_directories()
            self.load_tools()
        refresh_btn.clicked.connect(refresh_all)
        left_layout.addWidget(refresh_btn)
        
        left_panel.setLayout(left_layout)
        # left_panel.setMaximumWidth(345)  # Removed to allow resizing via splitter
        apply_card_shadow(left_panel)
        
        # 主分割器：分割左侧工具列表和右侧区域
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_panel)
        
        # 中右栏：使用 Splitter 分割配置表单和 Markdown 编辑器
        right_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 中栏：配置表单
        # 创建回调函数来获取注释和保存成功后的操作
        def get_comment():
            return self.markdown_editor.get_comment()
        
        def on_save_success():
            # 刷新目录列表（可能新建了目录）
            self.load_directories()
            # 刷新工具列表
            self.load_tools()
            # 发出工具保存成功信号，通知其他tab刷新工具列表
            self.tool_saved.emit()
        
        self.config_widget = ToolConfigWidget(
            self.api_client,
            get_comment_callback=get_comment,
            on_save_success_callback=on_save_success
        )
        # 保存对 ToolInstanceConfigTab 的引用，以便 ToolConfigWidget 可以访问 current_directory
        self.config_widget.tool_instance_tab = self
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        config_scroll.setWidget(self.config_widget)
        right_splitter.addWidget(config_scroll)
        
        # 右栏：Markdown 编辑器
        self.markdown_editor = MarkdownEditor(self.api_client)
        # 当注释内容变化时，标记为未保存
        self.markdown_editor.text_edit.textChanged.connect(self.config_widget.mark_unsaved)
        right_splitter.addWidget(self.markdown_editor)
        
        right_splitter.setStretchFactor(0, 4)
        right_splitter.setStretchFactor(1, 3)
        
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 5)
        
        layout.addWidget(main_splitter)
        self.setLayout(layout)
        
        # 连接代码改变信号（用于新建工具时更新注释）
        def on_code_changed_signal(tool_type: str, code_name: str):
            if self.config_widget.is_new_tool and code_name:
                self.markdown_editor.load_comment(None, tool_type, code_name, True)
        
        self.config_widget.code_changed.connect(on_code_changed_signal)
    
    def load_directories(self):
        """加载目录列表"""
        try:
            directories = self.api_client.get_directories()
            self.directory_combo.blockSignals(True)
            self.directory_combo.clear()
            # 移除根目录选项，强制用户选择子目录
            # self.directory_combo.addItem("（根目录）", "") 
            
            # 确保 default 目录在列表中（如果API没返回，可能是新创建尚未同步，或者为空目录未被扫描？）
            # api_client.get_directories 通常扫描实际存在的目录。
            # 如果 default 目录为空，get_directories 可能不返回它（取决于实现）。
            # 为了保险，如果 backend 没返回 default，我们手动加上？
            # 实际上 get_directories 实现是列出子目录，空目录也应该列出。
            
            has_default = False
            for directory in directories:
                self.directory_combo.addItem(directory, directory)
                if directory == "default":
                    has_default = True
            
            if not has_default:
                # 如果 default 不在列表中（可能是刚创建的空目录），手动添加
                # 注意：这假设 default 目录确实存在或将被创建
                self.directory_combo.addItem("default", "default")
            
            # 设置当前目录
            idx = self.directory_combo.findData(self.current_directory)
            if idx >= 0:
                self.directory_combo.setCurrentIndex(idx)
            else:
                # 如果当前目录无效（例如之前是根目录""），回退到 default
                idx = self.directory_combo.findData("default")
                if idx >= 0:
                    self.directory_combo.setCurrentIndex(idx)
                    self.current_directory = "default"
                elif self.directory_combo.count() > 0:
                    self.directory_combo.setCurrentIndex(0)
                    self.current_directory = self.directory_combo.currentData()
            
            self.directory_combo.blockSignals(False)
        except Exception as e:
            logger.error(f"加载目录列表失败: {e}")
    
    def on_directory_changed(self, text: str):
        """目录改变时的处理"""
        # 获取实际值（data）
        idx = self.directory_combo.currentIndex()
        if idx >= 0:
            directory = self.directory_combo.itemData(idx)
            if directory is None:
                directory = ""
            self.current_directory = directory
            logger.info(f"工具实例配置页面目录已改变为: '{directory}'")
            self.load_tools()
            
            # 通知运行工具页面刷新工具列表
            main_window = self.window()
            logger.debug(f"通知运行工具页面，主窗口: {main_window}, 类型: {type(main_window)}")
            logger.debug(f"是否有project_tab属性: {hasattr(main_window, 'project_tab') if main_window else False}")
            
            if main_window and hasattr(main_window, "project_tab") and main_window.project_tab is not None:
                logger.debug(f"project_tab: {main_window.project_tab}, 类型: {type(main_window.project_tab)}")
                if hasattr(main_window.project_tab, "load_project_tools"):
                    logger.info(f"通知运行工具页面刷新工具列表（目录: '{directory}'）")
                    main_window.project_tab.load_project_tools()
                else:
                    logger.warning("project_tab没有load_project_tools方法")
            else:
                logger.warning(f"无法通知运行工具页面：main_window={main_window}, has_project_tab={hasattr(main_window, 'project_tab') if main_window else False}")
    
    def load_tools(self):
        """加载工具列表（当前目录下的工具）"""
        try:
            logger.info(f"开始加载工具列表（目录: {self.current_directory if self.current_directory else '根目录'}）...")
            tools_data = self.api_client.get_tools(directory=self.current_directory if self.current_directory else None)
            # 强制刷新代码缓存，确保新模板可用
            if hasattr(self.config_widget, "refresh_tool_codes"):
                self.config_widget.refresh_tool_codes()
            self.tool_list.clear()
            
            # 添加所有工具（只显示实例名）
            tool_count = 0
            for tool_type, tools in [
                ("Single", tools_data.get("tools", [])),
                ("Merge", tools_data.get("merge_tools", [])),
                ("Meta", tools_data.get("meta_tools", []))
            ]:
                for tool_name in tools:
                    self.tool_list.addItem(f"[{tool_type}] {tool_name}")
                    tool_count += 1
            
            logger.info(f"工具列表加载成功，共 {tool_count} 个工具")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"加载工具列表失败: {error_msg}", exc_info=True)
            QMessageBox.critical(
                self, "错误 - 加载工具列表失败",
                f"{error_msg}\n\n"
                f"服务地址: {self.api_client.base_url}\n\n"
                f"请检查:\n"
                f"1. 后端服务是否已启动:\n"
                f"   cd /home/mkq/Documents/2025-12/DataProcess\n"
                f"   uvicorn main:app --reload\n"
                f"2. 服务是否正常运行在端口 8000\n"
                f"3. 防火墙设置是否正确\n"
                f"4. 是否有代理设置影响连接"
            )

    def on_templates_loaded(self):
        """模板加载完成后的回调"""
        # 清除警告标志，允许重新显示警告
        if hasattr(self.config_widget, '_template_warning_shown'):
            delattr(self.config_widget, '_template_warning_shown')
        # 刷新代码下拉缓存
        if hasattr(self.config_widget, "refresh_tool_codes"):
            self.config_widget.refresh_tool_codes()
        # 如果当前正在编辑工具，刷新配置表单
        if not self.config_widget.is_new_tool and self.config_widget.current_instance_name:
            self.config_widget.load_tool_instance(self.config_widget.current_instance_name)
        # 刷新目录列表（可能新增了目录）
        self.load_directories()

    def on_tool_selected(self, item):
        """工具选择事件"""
        text = item.text()
        # 解析 "[Type] instance_name"
        parts = text.split("] ", 1)
        if len(parts) == 2:
            instance_name = parts[1]
            self.config_widget.load_tool_instance(instance_name)
            
            # 加载注释
            try:
                data = self.api_client.get_tool_instance(instance_name)
                if data.get("status") == "ok":
                    self.markdown_editor.load_comment(
                        instance_name,
                        data.get("tool_type", ""),
                        data.get("code_name"),
                        False
                    )
            except Exception as e:
                logger.error(f"加载注释失败: {e}")

    def on_external_tool_update(self, tool_name: str):
        """处理外部（如运行工具页面）对工具配置的更新"""
        logger.info(f"收到外部工具更新通知: {tool_name}")
        # 如果当前正在编辑同一个工具，刷新表单
        if (not self.config_widget.is_new_tool and 
            self.config_widget.current_instance_name == tool_name):
            logger.info(f"刷新当前显示的工具配置: {tool_name}")
            self.config_widget.load_tool_instance(tool_name)
    
    def new_tool(self):
        """新建工具"""
        self.config_widget.new_tool()
        self.markdown_editor.load_comment(None, "", None, True)
        
        # 监听代码选择变化信号，更新注释
        def on_code_changed_signal(tool_type: str, code_name: str):
            if code_name:
                self.markdown_editor.load_comment(None, tool_type, code_name, True)
        
        # 断开之前的连接，避免重复连接
        try:
            self.config_widget.code_changed.disconnect()
        except:
            pass
        self.config_widget.code_changed.connect(on_code_changed_signal)

    def copy_new_tool(self):
        """基于当前选中工具拷贝新建"""
        item = self.tool_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在列表中选中一个要拷贝的工具。")
            return
            
        text = item.text()
        parts = text.split("] ", 1)
        if len(parts) != 2:
            return
            
        instance_name = parts[1]
        try:
            data = self.api_client.get_tool_instance(instance_name)
            if data.get("status") == "ok":
                # 加载到配置表单（拷贝模式）
                self.config_widget.load_for_cloning(data)
                
                # 加载注释（作为新工具的初始注释）
                self.markdown_editor.load_comment(
                    None, # 新工具无实例名
                    data.get("tool_type", ""),
                    data.get("code_name"),
                    True # 标记为新工具，以便编辑器知道要处理初始值
                )
                
                # 监听代码改变
                def on_code_changed_signal(tool_type: str, code_name: str):
                    if self.config_widget.is_new_tool and code_name:
                        self.markdown_editor.load_comment(None, tool_type, code_name, True)
                
                try:
                    self.config_widget.code_changed.disconnect()
                except:
                    pass
                self.config_widget.code_changed.connect(on_code_changed_signal)
                
                logger.info(f"已基于 '{instance_name}' 加载配置，准备拷贝新建。")
        except Exception as e:
            logger.error(f"拷贝新建失败: {e}")
            QMessageBox.warning(self, "错误", f"拷贝新建失败: {e}")
