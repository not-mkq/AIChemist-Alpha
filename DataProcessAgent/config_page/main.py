#!/usr/bin/env python3
"""
config-page/main.py

工具配置管理页面 - PyQt 应用程序
用于管理工具实例的配置
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

# 确保 config_page 目录在 sys.path 中，使得组件可以相互导入
current_dir = Path(__file__).parent.absolute()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QMessageBox, QSplitter, QTabWidget, QStyle
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from i18n import tr


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('config-page.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 加载配置以获取通讯方式
transport = "uds"
uds_path = "/tmp/dataprocess.sock"
frontend_config_path = Path(__file__).resolve().parents[1] / "config" / "frontend.json"
if frontend_config_path.exists():
    try:
        with open(frontend_config_path, 'r', encoding='utf-8') as f:
            fe_cfg = json.load(f)
            transport = fe_cfg.get("transport", "uds")  # 默认为 uds
            uds_path = fe_cfg.get("uds_path", uds_path)
    except Exception as e:
        logger.warning(f"加载前端配置失败，使用默认通讯方式: {e}")

# ApiClient 已提取到 api_client.py
try:
    from api_client import ApiClient
    api_client = ApiClient(transport=transport, uds_path=uds_path)
    from ui_theme import apply_global_style, apply_card_shadow
    from file_manager_tab import FileManagerTab
    from project_context import ProjectContext
except ImportError:
    from .api_client import ApiClient
    api_client = ApiClient(transport=transport, uds_path=uds_path)
    from .ui_theme import apply_global_style, apply_card_shadow
    from .file_manager_tab import FileManagerTab
    from .project_context import ProjectContext



# ToolConfigWidget 已提取到 tool_config_widget.py
try:
    from tool_config_widget import ToolConfigWidget
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from tool_config_widget import ToolConfigWidget


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
    
    def load_comment(self, instance_name: Optional[str], tool_type: str, code_name: Optional[str], is_new: bool):
        """加载注释"""
        self.current_instance_name = instance_name
        self.is_new_tool = is_new
        
        try:
            if is_new and code_name:
                # 新建工具：显示代码级别的注释
                comment = self.api_client.get_tool_code_comment(code_name)
                self.text_edit.setPlainText(comment or "")
            elif instance_name:
                # 已有工具：显示实例级别的注释
                data = self.api_client.get_tool_instance(instance_name)
                comment = data.get("comment")
                self.text_edit.setPlainText(comment or "")
            else:
                self.text_edit.clear()
        except Exception as e:
            self.text_edit.setPlainText(f"{tr('msg_load_comment_failed')}: {e}")
    
    def get_comment(self) -> str:
        """获取当前注释"""
        return self.text_edit.toPlainText()


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        logger.info("初始化主窗口...")
        # 使用全局配置的 transport 和 uds_path
        self.api_client = ApiClient(transport=transport, uds_path=uds_path)
        logger.info(f"API 客户端已初始化，通讯方式: {transport}, base_url: {self.api_client.base_url}")
        
        # 初始化项目上下文
        self.project_context = ProjectContext(self.api_client, self)

        # 启动时强制同步模板和实例
        try:
            self.api_client.reload_all()
            logger.info(tr("msg_reload_success"))
        except Exception as e:
            logger.warning(f"{tr('msg_reload_failed')}: {e}")
        self.setup_ui()
        logger.info("UI 设置完成")
        # 工具列表加载由各个tab自己处理
    
    def setup_ui(self):
        self.setWindowTitle(tr("app_title"))
        self.setGeometry(100, 100, 1200, 800)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        
        # 使用 Tab 切换
        tab_widget = QTabWidget()
        
        # Tab 1: 全局配置
        try:
            from global_config_tab import GlobalConfigTab
            global_tab = GlobalConfigTab(self.api_client, self)
        except ImportError:
            # 如果导入失败，使用内联版本
            global_tab = QWidget()
            global_layout = QVBoxLayout()
            global_label = QLabel(tr("tab_global_config"))
            global_label.setFont(QFont("Source Sans 3", 18, QFont.Weight.Bold))
            global_layout.addWidget(global_label)
            global_layout.addSpacing(20)
            reload_btn = QPushButton(tr("btn_reload"))
            reload_btn.setMinimumHeight(50)
            reload_btn.clicked.connect(self.reload_all)
            global_layout.addWidget(reload_btn)
            global_layout.addStretch()
            global_tab.setLayout(global_layout)
        tab_widget.addTab(global_tab, self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), tr("tab_global_config"))
        
        # Tab 2: 工具实例配置（三栏布局）
        try:
            from tool_instance_config_tab import ToolInstanceConfigTab
            instance_tab = ToolInstanceConfigTab(self.api_client, self)
            self.tool_instance_tab = instance_tab  # 保存引用，供其他tab访问
        except ImportError:
            self.tool_instance_tab = None
            # 如果导入失败，使用内联版本（回退方案）
            instance_tab = QWidget()
            instance_layout = QHBoxLayout()
            right_splitter = QSplitter(Qt.Orientation.Horizontal)
            
            # 创建回调函数
            def get_comment():
                if hasattr(self, 'markdown_editor'):
                    return self.markdown_editor.get_comment()
                return ""
            
            def on_save_success():
                self.load_tools()
            
            self.config_widget = ToolConfigWidget(
                self.api_client,
                get_comment_callback=get_comment,
                on_save_success_callback=on_save_success
            )
            right_splitter.addWidget(self.config_widget)
            self.markdown_editor = MarkdownEditor(self.api_client)
            right_splitter.addWidget(self.markdown_editor)
            right_splitter.setStretchFactor(0, 2)
            right_splitter.setStretchFactor(1, 1)
            instance_layout.addWidget(right_splitter)
            instance_tab.setLayout(instance_layout)
        tab_widget.addTab(instance_tab, self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), tr("tab_tool_instance"))
        
        # Tab 3: 运行工具页面
        try:
            from project_config_tab import ProjectConfigTab
            project_tab = ProjectConfigTab(self.api_client, self.project_context, self)
            self.project_tab = project_tab  # 保存引用
        except ImportError:
            # 如果导入失败，使用占位符
            project_tab = QWidget()
            project_layout = QVBoxLayout()
            project_label = QLabel(f"{tr('tab_run_tool')} ({tr('msg_load_failed')})")
            project_label.setFont(QFont("Source Sans 3", 18, QFont.Weight.Bold))
            project_layout.addWidget(project_label)
            project_layout.addStretch()
            project_tab.setLayout(project_layout)
            self.project_tab = None
        tab_widget.addTab(project_tab, self.style().standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon), tr("tab_run_tool"))

        # Tab 4: 项目文件管理
        file_tab = FileManagerTab(self.api_client, self.project_context, self)
        self.file_tab = file_tab
        tab_widget.addTab(file_tab, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), tr("tab_file_manager"))

        # 初始化时同步一次当前项目（从项目 Tab 的默认选择，或者直接使用 Context）
        # ProjectContext.load_projects() 会在后续调用（如果需要），或者已经由 project_tab 触发
        # 这里不需要手动 set_project，因为 FileTab 已经监听了 Context 信号
        if hasattr(project_tab, "current_project"):
            pass
        
        # 工具运行完成后自动刷新文件树
        if hasattr(project_tab, "tool_run_completed"):
            project_tab.tool_run_completed.connect(lambda project: file_tab.load_file_tree())
        
        # 工具保存成功后自动刷新运行工具页面的工具列表
        if hasattr(instance_tab, "tool_saved") and hasattr(project_tab, "load_project_tools"):
            instance_tab.tool_saved.connect(lambda: project_tab.load_project_tools(force_reload=True))

        # 工具配置（在运行页面）保存成功后自动刷新工具实例页面的当前表单
        if hasattr(project_tab, "tool_config_updated") and hasattr(instance_tab, "on_external_tool_update"):
            project_tab.tool_config_updated.connect(instance_tab.on_external_tool_update)
        
        main_layout.addWidget(tab_widget)
        
        central_widget.setLayout(main_layout)
        
        # 保存 tab_widget 引用，以便后续访问
        self.tab_widget = tab_widget
        
        # 启动时检查数据库是否有模板数据，如果没有则提示
        self._check_template_data()
        
        # 加载上次的 UI 状态
        self.load_ui_state()

        # [修复] 最后显式触发一次项目列表加载
        self.project_context.load_projects()
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.save_ui_state()
        event.accept()
        
    def save_ui_state(self):
        """保存 UI 状态到配置文件 (保留现有配置项)"""
        try:
            config_path = Path("config/frontend.json")
            config = {}
            
            # 1. 先读取现有配置，以保留 transport 等非 UI 状态项
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except Exception:
                    pass
            
            # 2. 更新 Tab 1 (工具实例配置) 状态
            if self.tool_instance_tab:
                config["tool_instance_tab"] = {
                    "directory": getattr(self.tool_instance_tab, "current_directory", "default"),
                    "selected_tool": getattr(self.tool_instance_tab.config_widget, "current_instance_name", None) if hasattr(self.tool_instance_tab, "config_widget") else None
                }
            
            # 3. 更新 Tab 2 (运行工具页面) 状态
            if self.project_tab:
                config["project_tab"] = {
                    "project": getattr(self.project_tab, "current_project", None),
                    "tool": getattr(self.project_tab, "current_tool_name", None),
                    "scope": self.project_tab.scope_combo.currentText() if hasattr(self.project_tab, "scope_combo") else None,
                    "batch": self.project_tab.batch_combo.currentText() if hasattr(self.project_tab, "batch_combo") else None,
                    "item": self.project_tab.item_combo.currentText() if hasattr(self.project_tab, "item_combo") else None,
                    "tool_directory": self.project_tab.tool_directory_combo.currentData() if hasattr(self.project_tab, "tool_directory_combo") else None,
                }
            
            # 4. 更新当前选中的 Tab 索引
            config["current_tab_index"] = self.tab_widget.currentIndex()
            
            # 写入文件
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            logger.info(f"UI 状态已保存 (保留了其他配置)，路径: {config_path}")
        except Exception as e:
            logger.error(f"保存 UI 状态失败: {e}")
            
    def load_ui_state(self):
        """加载 UI 状态"""
        config_path = Path("config/frontend.json")
        if not config_path.exists():
            return
            
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            # 1. 恢复 Tab 1 (工具实例配置)
            # 关键：必须先恢复目录，这样 Tab 2 才能加载到正确的工具列表
            tab1_config = config.get("tool_instance_tab", {})
            if self.tool_instance_tab and tab1_config:
                directory = tab1_config.get("directory")
                selected_tool = tab1_config.get("selected_tool")
                
                # 恢复目录
                if directory:
                    # 查找目录在下拉框中的索引
                    idx = self.tool_instance_tab.directory_combo.findData(directory)
                    if idx >= 0:
                        self.tool_instance_tab.directory_combo.setCurrentIndex(idx)
                        # setCurrentIndex 会触发 on_directory_changed -> load_tools
                        # 这是一个同步调用，所以此时工具列表已经刷新了
                
                # 恢复选中的工具
                if selected_tool:
                    # 在列表中查找并选中
                    items = self.tool_instance_tab.tool_list.findItems(selected_tool, Qt.MatchFlag.MatchContains)
                    for item in items:
                        # 确保完全匹配实例名（因为 MatchContains 可能会匹配到前缀）
                        # 列表项格式: "[Type] instance_name"
                        if item.text().endswith(f" {selected_tool}"):
                            self.tool_instance_tab.tool_list.setCurrentItem(item)
                            self.tool_instance_tab.on_tool_selected(item)
                            break

            # 2. 恢复 Tab 2 (运行工具页面)
            tab2_config = config.get("project_tab", {})
            if self.project_tab and tab2_config:
                project = tab2_config.get("project")
                tool = tab2_config.get("tool")
                scope = tab2_config.get("scope")
                batch = tab2_config.get("batch")
                item = tab2_config.get("item")
                tool_directory = tab2_config.get("tool_directory")
                
                # 核心改进：通过 Context 恢复项目状态，而不是直接操作 Combo
                if project:
                    logger.info(f"恢复上次选中的项目: {project}")
                    self.project_context.set_current_project(project)
                
                # 恢复工具目录
                if tool_directory and hasattr(self.project_tab, "tool_directory_combo"):
                    idx = self.project_tab.tool_directory_combo.findData(tool_directory)
                    if idx >= 0:
                        self.project_tab.tool_directory_combo.setCurrentIndex(idx)
                        # 这会触发 on_tool_directory_changed -> load_project_tools
                
                # 刷新 Tab 2 的工具列表
                # 显式调用一次 load_project_tools，确保列表是最新的（如果上面设置了目录，其实已经刷新了一次，但多刷一次无妨）
                self.project_tab.load_project_tools()
                
                # 恢复工具
                if tool:
                    idx = self.project_tab.tool_combo.findText(tool)
                    if idx >= 0:
                        self.project_tab.tool_combo.setCurrentIndex(idx)
                        # 触发 on_tool_changed，会加载 Scope 列表
                
                # 恢复 Scope
                if scope:
                    idx = self.project_tab.scope_combo.findText(scope)
                    if idx >= 0:
                        self.project_tab.scope_combo.setCurrentIndex(idx)
                        # 触发 on_scope_changed，会显隐 Batch/Item 并加载相关列表
                
                # 恢复 Batch
                if batch:
                    idx = self.project_tab.batch_combo.findText(batch)
                    if idx >= 0:
                        self.project_tab.batch_combo.setCurrentIndex(idx)
                        # 如果 Scope 是 item，这会触发 on_batch_changed_for_item -> load_item_list
                
                # 恢复 Item
                if item:
                    idx = self.project_tab.item_combo.findText(item)
                    if idx >= 0:
                        self.project_tab.item_combo.setCurrentIndex(idx)
            
            # 3. 恢复选中的 Tab 索引
            current_tab_index = config.get("current_tab_index")
            if current_tab_index is not None and 0 <= current_tab_index < self.tab_widget.count():
                self.tab_widget.setCurrentIndex(current_tab_index)
                
            logger.info("UI 状态已恢复")
            
        except Exception as e:
            logger.error(f"加载 UI 状态失败: {e}")

    def _check_template_data(self):
        """检查数据库是否有模板数据"""
        try:
            codes_data = self.api_client.get_tool_codes()
            total = len(codes_data.get("single", [])) + len(codes_data.get("merge", []))
            if total == 0:
                QMessageBox.information(
                    self, "提示",
                    "数据库中没有工具代码模板数据。\n\n"
                    "请先到'全局配置'标签页点击'加载所有代码模板'按钮。"
                )
        except Exception as e:
            logger.debug(f"检查模板数据失败: {e}")
    
    def reload_all(self):
        """加载代码模板并注册实例"""
        reply = QMessageBox.question(
            self, tr("confirm"),
            tr("confirm_reload_all"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.api_client.reload_all()
            codes = result.get("codes", {})
            tools = result.get("tools", {})
            labels = result.get("labels", {})
            
            # 构建成功消息
            msg_parts = [
                f"{tr('code_templates')}: total={codes.get('total', 0)}, single={codes.get('single', 0)}, merge={codes.get('merge', 0)}",
                f"instances: total={tools.get('total', 0)}, single={tools.get('single', 0)}, merge={tools.get('merge', 0)}, meta={tools.get('meta', 0)}"
            ]
            
            # 添加 label 同步结果
            if labels:
                added_count = len(labels.get("added", []))
                existing_count = len(labels.get("existing", []))
                total_count = labels.get("total", 0)
                if added_count > 0:
                    msg_parts.append(f"\n{tr('label_sync')}: {tr('msg_labels_added').format(added_count)}")
                    if added_count <= 10:
                        msg_parts.append(f"{tr('new_labels')}: {', '.join(labels.get('added', []))}")
                elif existing_count > 0:
                    msg_parts.append(f"\n{tr('label_sync')}: {tr('msg_labels_exist').format(total_count)}")
            
            QMessageBox.information(
                self, tr("success"),
                "\n".join(msg_parts)
            )
            # 刷新列表和表单
            self.load_tools()
            self.on_templates_loaded()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载失败: {e}")
    
    def load_tools(self):
        """加载工具列表（委托给各个 tab）"""
        # 1. 刷新工具实例配置 tab (Tab 1)
        instance_tab = self.tab_widget.widget(1)
        if hasattr(instance_tab, 'load_directories'):
            instance_tab.load_directories()
        if hasattr(instance_tab, 'load_tools'):
            instance_tab.load_tools()
            
        # 2. 刷新运行工具页面 (Tab 2)
        project_tab = self.tab_widget.widget(2)
        if hasattr(project_tab, 'load_directories'):
            project_tab.load_directories()
        if hasattr(project_tab, "on_templates_loaded"):
            # on_templates_loaded 内部会调用 load_project_tools
            project_tab.on_templates_loaded()
            
        # 3. 清空标签缓存，确保新标签可用
        if hasattr(instance_tab, "config_widget") and hasattr(instance_tab.config_widget, "refresh_labels"):
            instance_tab.config_widget.refresh_labels()
        if hasattr(project_tab, "config_widget") and hasattr(project_tab.config_widget, "refresh_labels"):
            project_tab.config_widget.refresh_labels()

    def on_templates_loaded(self):
        """模板加载完成后的回调"""
        # 通知工具实例配置tab刷新
        instance_tab = self.tab_widget.widget(1)
        if hasattr(instance_tab, 'on_templates_loaded'):
            instance_tab.on_templates_loaded()
        # 通知项目配置tab刷新
        project_tab = self.tab_widget.widget(2)
        if hasattr(project_tab, "on_templates_loaded"):
            project_tab.on_templates_loaded()
        # 清空标签缓存，确保新标签可用
        if hasattr(instance_tab, "config_widget") and hasattr(instance_tab.config_widget, "refresh_labels"):
            instance_tab.config_widget.refresh_labels()
        if hasattr(project_tab, "config_widget") and hasattr(project_tab.config_widget, "refresh_labels"):
            project_tab.config_widget.refresh_labels()


def main():
    logger.info("=" * 50)
    logger.info("启动工具配置管理页面")
    logger.info("=" * 50)

    # 启用高 DPI 支持（Qt6 默认开启，但向后兼容 Qt5）
    aa_enable = getattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling", None)
    aa_pixmap = getattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps", None)
    if aa_enable is not None:
        QApplication.setAttribute(aa_enable, True)
    if aa_pixmap is not None:
        QApplication.setAttribute(aa_pixmap, True)
    
    # 支持 Wayland 输入法
    # Qt 会自动处理输入法，只要环境变量正确设置即可
    import os
    
    # 记录输入法环境变量状态（用于调试）
    logger.debug(f"输入法环境变量: QT_IM_MODULE={os.environ.get('QT_IM_MODULE', '未设置')}, "
                 f"GTK_IM_MODULE={os.environ.get('GTK_IM_MODULE', '未设置')}, "
                 f"XMODIFIERS={os.environ.get('XMODIFIERS', '未设置')}")
    
    app = QApplication(sys.argv)
    
    # 记录 Qt 平台插件（用于调试）
    platform_name = app.platformName()
    logger.debug(f"Qt 平台插件: {platform_name}")
    
    apply_global_style(app)
    
    try:
        window = MainWindow()
        window.show()
        logger.info("窗口已显示")
        sys.exit(app.exec())
    except Exception as e:
        logger.exception("程序启动失败")
        QMessageBox.critical(None, "启动失败", f"程序启动失败:\n\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
