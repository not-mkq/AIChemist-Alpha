#!/usr/bin/env python3
"""
meta_tool_tree_widget.py

Meta工具扁平列表配置UI组件
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox, 
    QScrollArea, QFrame, QStyle, QToolButton, QSizePolicy, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont

from i18n import tr
from typing import Dict, Any, Optional, List, Set
import logging

try:
    from meta_tool_tree import ToolNode, parse_meta_tool_tree, collect_all_tools
    from tool_config_widget import ToolConfigWidget
    from api_client import ApiClient
except ImportError:
    from .meta_tool_tree import ToolNode, parse_meta_tool_tree, collect_all_tools
    from .tool_config_widget import ToolConfigWidget
    from .api_client import ApiClient

logger = logging.getLogger(__name__)


class AdaptiveTabWidget(QTabWidget):
    """高度自适应的 TabWidget，高度取决于当前选中的标签页"""
    def __init__(self, parent=None):
        super().__init__(parent)
        # 必须允许垂直方向收缩
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        # 切换标签页时触发布局更新
        self.currentChanged.connect(self.updateGeometry)

    def sizeHint(self):
        current = self.currentWidget()
        if not current:
            return super().sizeHint()
        
        # 获取当前页面的 sizeHint
        s = current.sizeHint()
        
        # 计算 TabBar 的高度
        tab_bar = self.tabBar()
        tab_bar_h = tab_bar.sizeHint().height()
        
        # 加上边距（根据 QTabWidget 的样式，通常有一些 padding）
        # 这里估算垂直边距
        vertical_margin = 16 
        
        # 宽度取当前宽度或推荐宽度，高度取当前页高度 + TabBar
        return QSize(super().sizeHint().width(), s.height() + tab_bar_h + vertical_margin)

    def minimumSizeHint(self):
        return self.sizeHint()


class MetaToolTreeWidget(QWidget):
    """Meta工具扁平列表配置组件"""
    
    # 信号：当内部工具配置变化时发出
    form_changed = pyqtSignal()  # 任意表单字段变化
    reset_completed = pyqtSignal()  # 当工具重置完成时发出
    
    def __init__(self, api_client: ApiClient, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.tool_nodes: List[tuple[ToolNode, str]] = []  # 扁平化的工具节点列表，每个元素是(节点, 路径)元组
        self.config_widgets: Dict[str, ToolConfigWidget] = {}  # 工具名 -> 配置组件映射（只保存第一次出现的）
        self.config_containers: Dict[int, QWidget] = {}  # 索引 -> 配置容器映射（使用索引确保唯一性）
        self.expand_buttons: Dict[int, QToolButton] = {}  # 索引 -> 展开按钮映射
        self.row_index_map: Dict[int, tuple[ToolNode, str]] = {}  # 索引 -> (节点, 路径)映射
        self.root_node: Optional[ToolNode] = None
        self.expanded_tools: Set[int] = set()  # 已展开的工具索引集合
        self.first_occurrence: Dict[str, int] = {}  # 工具名 -> 第一次出现的索引
        self._last_loaded_tool_name: Optional[str] = None  # 保存最后加载的工具名，用于重置
        self._display_index_counter: int = 0  # 渲染计数器
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 标题
        title_label = QLabel(tr("meta_tool_config"))
        title_label.setFont(QFont("Source Sans 3", 14, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # 工具列表区域（滚动）
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.list_scroll.setMinimumHeight(200)
        
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        self.list_container.setLayout(self.list_layout)
        self.list_scroll.setWidget(self.list_container)
        
        layout.addWidget(self.list_scroll)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        # 保存按钮
        save_btn = QPushButton(tr("btn_save_all"))
        save_btn.setProperty("variant", "primary")
        save_btn.setMinimumHeight(44)
        save_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        save_btn.clicked.connect(self.save_all_tools)
        button_layout.addWidget(save_btn)
        
        # 重置按钮
        reset_btn = QPushButton(tr("btn_reset"))
        reset_btn.setProperty("variant", "secondary")
        reset_btn.setMinimumHeight(44)
        reset_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        reset_btn.clicked.connect(self.reset_all_tools)
        button_layout.addWidget(reset_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def load_meta_tool(self, tool_name: str):
        """加载meta工具并构建扁平列表"""
        try:
            # 保存当前加载的工具名，用于重置功能
            self._last_loaded_tool_name = tool_name
            
            # 获取工具实例数据
            tool_instance_data = self.api_client.get_tool_instance(tool_name)
            
            if not tool_instance_data or tool_instance_data.get("status") != "ok":
                QMessageBox.warning(self, "错误", f"无法获取工具实例信息: {tool_name}")
                return False
            
            tool_type = tool_instance_data.get("tool_type", "single")
            config = tool_instance_data.get("config", {})
            comment = tool_instance_data.get("comment")
            
            if tool_type != "meta":
                QMessageBox.warning(self, "错误", f"工具 '{tool_name}' 不是meta工具")
                return False
            
            # 解析工具树
            def get_tool_instance(tool_name: str):
                return self.api_client.get_tool_instance(tool_name)
            
            root_node, error = parse_meta_tool_tree(
                tool_name,
                tool_type,
                config,
                get_tool_instance,
                comment=comment
            )
            
            if error:
                QMessageBox.critical(self, "错误", error)
                return False
            
            self.root_node = root_node
            self._build_flat_list()
            return True
            
        except Exception as e:
            logger.error(f"加载meta工具失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"加载meta工具失败: {e}")
            return False
    
    def _build_flat_list(self):
        """构建扁平列表UI"""
        # 清空现有内容
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.tool_nodes.clear()
        self.node_path_map = {}  # 节点 -> 路径 映射
        self.config_widgets.clear()
        self.config_containers.clear()
        self.expand_buttons.clear()
        self.row_index_map.clear()
        self.expanded_tools.clear()
        self.first_occurrence.clear()
        self._display_index_counter = 0
        
        if not self.root_node:
            return
        
        # 收集根层级的显示节点
        root_display_nodes = self._collect_display_nodes(self.root_node, None)
        
        # 渲染节点
        self._render_nodes(root_display_nodes, self.list_layout)
        
        self.list_layout.addStretch()

    def _collect_display_nodes(self, node: ToolNode, parent_path: Optional[str] = None) -> List[tuple[ToolNode, str]]:
        """
        递归收集用于显示的节点列表。
        对于 'alt' 类型的 meta 工具，停止递归并返回该节点本身（后续渲染为 Tab）。
        """
        nodes = []
        
        # 计算当前路径
        if parent_path is None:
            current_path = ""
        elif parent_path == "":
            current_path = node.name
        else:
            current_path = f"{parent_path} -> {node.name}"
        
        # 如果是meta工具
        if node.tool_type == "meta":
            mode = node.config.get("code_name")
            if mode == "alt":
                # Alt 模式：停止递归，将当前节点作为显示单元返回
                nodes.append((node, current_path))
            else:
                # Sequence / Map 模式：递归处理子节点
                for child in node.children:
                    # 如果是根节点，传递 "" 作为 parent_path
                    next_parent = "" if parent_path is None else current_path
                    nodes.extend(self._collect_display_nodes(child, next_parent))
        else:
            # single/merge 工具：添加到列表
            nodes.append((node, current_path))
        
        return nodes

    def _render_nodes(self, nodes: List[tuple[ToolNode, str]], target_layout: QVBoxLayout):
        """将节点列表渲染到指定布局中"""
        print(f"DEBUG: _render_nodes called with {len(nodes)} nodes")
        for node, path in nodes:
            # 记录节点路径 (使用id作为键，因为ToolNode不可哈希)
            self.node_path_map[id(node)] = path
            
            # 检查是否是 Alt 节点
            is_alt = node.tool_type == "meta" and node.config.get("code_name") == "alt"
            
            if is_alt:
                print(f"DEBUG: Rendering Alt node: {node.name}")
                # 创建 Tab 组件
                # Alt 节点本身不占用 index，或者作为一个特殊的 item？
                # 为了保持一致性，我们也可以给它分配 index，但它没有 config_widget
                # 这里我们直接渲染 widget
                alt_widget = self._create_alt_tabs_widget(node, path)
                target_layout.addWidget(alt_widget)
            else:
                print(f"DEBUG: Rendering Tool node: {node.name}")
                # 普通工具行
                index = self._display_index_counter
                self._display_index_counter += 1
                
                self.tool_nodes.append((node, path))
                self.row_index_map[index] = (node, path)
                
                # 判断是否是第一次出现
                is_first_occurrence = node.name not in self.first_occurrence
                if is_first_occurrence:
                    self.first_occurrence[node.name] = index
                
                self._create_tool_row(node, path, index, is_first_occurrence, target_layout)

    def _create_alt_tabs_widget(self, node: ToolNode, path: str) -> QWidget:
        """创建 Alt 工具的 Tab 组件"""
        # 使用 QFrame 作为容器，以便添加边框
        container = QFrame()
        container.setObjectName("AltToolContainer")
        # 添加边框样式，圈出 Alt 工具的范围
        container.setStyleSheet("""
            #AltToolContainer {
                border: 1px solid #dcdfe6;
                border-radius: 6px;
                background-color: #ffffff;
                margin-top: 4px;
                margin-bottom: 4px;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)  # 增加内部边距
        layout.setSpacing(4)
        
        # 标题行：显示 Alt 工具名称和路径
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 0, 4, 0)
        
        name_label = QLabel(f"候选分支: {node.name}")
        name_label.setFont(QFont("Source Sans 3", 10, QFont.Weight.Bold))
        header_layout.addWidget(name_label)
        
        path_label = QLabel(path)
        path_label.setFont(QFont("Source Sans 3", 9))
        path_label.setProperty("hint", "muted")
        path_label.style().unpolish(path_label)
        path_label.style().polish(path_label)
        header_layout.addWidget(path_label)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # 使用高度自适应的 Tab 组件
        tab_widget = AdaptiveTabWidget()
        
        # 遍历子节点创建 Tab 页
        for child in node.children:
            tab_page = QWidget()
            page_layout = QVBoxLayout()
            page_layout.setContentsMargins(8, 8, 8, 8)
            page_layout.setSpacing(8)
            
            # 收集该分支的显示节点
            # 注意：路径需要延续
            child_nodes = self._collect_display_nodes(child, path)
            
            # 递归渲染
            self._render_nodes(child_nodes, page_layout)
            
            page_layout.addStretch()
            tab_page.setLayout(page_layout)
            
            tab_widget.addTab(tab_page, child.name)
        
        layout.addWidget(tab_widget)
        container.setLayout(layout)
        
        # 内部 Tab 不需要边框 (因为外层已经有边框了)
        tab_widget.setStyleSheet("QTabWidget::pane { border: 0; }")
        
        return container

    
    def _create_tool_row(self, node: ToolNode, path: str, index: int, is_first_occurrence: bool, target_layout: Optional[QVBoxLayout] = None):
        """创建工具行UI"""
        # 如果未提供 target_layout，默认使用主列表布局
        if target_layout is None:
            target_layout = self.list_layout

        # 工具行容器
        tool_row = QWidget()
        # 移除边框，保持简洁
        # tool_row.setFrameShape(QFrame.Shape.Box)
        # tool_row.setStyleSheet("QFrame { border: 0px solid #d7dbe3; border-radius: 4px; padding: 2px; }")

        # 关键：不要让每个 row 纵向扩张，保持“需要多少高就占多少高”
        sp = tool_row.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        sp.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        tool_row.setSizePolicy(sp)
        
        row_layout = QVBoxLayout()
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(0)
        
        # 工具信息行（可点击展开/折叠）
        info_layout = QHBoxLayout()
        info_layout.setSpacing(6)
        info_layout.setContentsMargins(0, 0, 0, 0)
        
        # 展开/折叠按钮（使用 QToolButton 和箭头类型，符合系统风格）
        expand_btn = QToolButton()
        expand_btn.setCheckable(True)
        expand_btn.setArrowType(Qt.ArrowType.DownArrow)
        expand_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        expand_btn.setAutoRaise(True)  # 扁平样式
        expand_btn.setFixedSize(20, 20)
        expand_btn.setChecked(True)  # 默认展开
        
        # 存储索引和节点名作为按钮的数据（使用索引确保唯一性）
        expand_btn.setProperty("row_index", index)
        expand_btn.setProperty("tool_path", path)
        expand_btn.setProperty("tool_name", node.name)
        expand_btn.setProperty("is_first_occurrence", is_first_occurrence)
        # 使用局部函数来确保变量被正确捕获
        def make_expand_handler(idx: int, n: str, f: bool, btn: QToolButton):
            def handler(checked: bool):
                self.on_expand_toggled(idx, n, f, checked, btn)
            return handler
        expand_btn.clicked.connect(make_expand_handler(index, node.name, is_first_occurrence, expand_btn))
        
        info_layout.addWidget(expand_btn)
        self.expand_buttons[index] = expand_btn  # 使用索引保存按钮引用
        
        # 将已展开的工具加入集合
        self.expanded_tools.add(index)
        
        # 工具路径标签（小字体，单行，灰色）
        path_label = QLabel(path)
        path_label.setWordWrap(False)  # 不换行
        path_label.setFont(QFont("Source Sans 3", 9))  # 更小的字体
        path_label.setProperty("hint", "muted")  # 统一使用 ui_theme.py 中的 hint="muted"
        path_label.setFixedHeight(18)  # 稍微缩减高度
        if not is_first_occurrence:
            path_label.setText(f"{path} (只读，引用首次出现)")
        
        # 刷新样式以应用 hint="muted"
        path_label.style().unpolish(path_label)
        path_label.style().polish(path_label)
        
        info_layout.addWidget(path_label)
        
        # 添加弹性空间，使工具类型右对齐
        info_layout.addStretch()
        
        # 工具类型标签（右对齐，小字体，灰色）
        type_label = QLabel(node.tool_type)
        type_label.setFont(QFont("Source Sans 3", 9))
        type_label.setProperty("hint", "muted")
        type_label.setFixedHeight(18)
        type_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # 刷新样式
        type_label.style().unpolish(type_label)
        type_label.style().polish(type_label)
        
        info_layout.addWidget(type_label)
        
        row_layout.addLayout(info_layout)
        
        # 配置表单容器（默认显示）
        config_container = QWidget()
        config_container.setVisible(True)
        config_layout = QVBoxLayout()
        config_layout.setContentsMargins(4, 2, 2, 2)
        config_layout.setSpacing(2)
        
        should_render = True

        # 如果是第一次出现，创建可编辑的配置组件
        if is_first_occurrence:
            config_widget_group, config_widget = self._create_config_widget(node, is_editable=True)
            
            # 检查是否有可配置参数
            if config_widget and not config_widget.has_visible_run_params():
                config_widget.deleteLater()
                config_widget_group.deleteLater()
                should_render = False
            else:
                config_layout.addWidget(config_widget_group)
                if config_widget:
                    self.config_widgets[node.name] = config_widget
                    # 监听配置变化，实时同步到只读引用
                    try:
                        config_widget.form_changed.connect(lambda: self._sync_readonly_refs_for_tool(node.name))
                        # 监听配置变化，发出form_changed信号，通知父组件更新保存状态
                        config_widget.form_changed.connect(self.form_changed.emit)
                    except Exception:
                        pass
        else:
            # 不是第一次出现，创建只读的配置组件（引用第一次出现的配置）
            # 先获取第一次出现的配置（如果已经创建）
            first_config = None
            if node.name in self.config_widgets:
                first_widget = self.config_widgets[node.name]
                try:
                    payload = first_widget.build_payload(require_instance=True)
                    first_config = payload.get("config", {})
                except Exception:
                    pass
            
            # 如果无法获取同步配置，使用节点原始配置（后续展开时会同步）
            if first_config is None:
                first_config = node.config
            
            config_widget_group, config_widget = self._create_config_widget(node, is_editable=False, sync_config=first_config)
            
            # 检查是否应该跳过
            if config_widget and not config_widget.has_visible_run_params():
                config_widget.deleteLater()
                config_widget_group.deleteLater()
                should_render = False
            else:
                config_layout.addWidget(config_widget_group)
        
        if not should_render:
            # 清理资源并跳过渲染
            if index in self.expand_buttons:
                del self.expand_buttons[index]
            self.expanded_tools.discard(index)
            tool_row.deleteLater()
            return

        config_container.setLayout(config_layout)
        row_layout.addWidget(config_container)
        
        tool_row.setLayout(row_layout)
        target_layout.addWidget(tool_row)
        
        # 保存配置容器引用（使用索引确保唯一性）
        self.config_containers[index] = config_container
    
    def _create_config_widget(self, node: ToolNode, is_editable: bool, sync_config: Optional[Dict[str, Any]] = None) -> tuple[QWidget, Optional[ToolConfigWidget]]:
        """创建配置组件"""
        # 不使用QGroupBox，直接使用QWidget容器
        container = QWidget()
        
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)
        
        is_readonly = not is_editable
        
        if is_readonly:
            # 只读提示
            readonly_label = QLabel(tr("readonly_reference"))
            readonly_label.setProperty("badge", "warn")
            container_layout.addWidget(readonly_label)
        
        # 创建ToolConfigWidget
        config_widget = ToolConfigWidget(
            api_client=self.api_client,
            get_comment_callback=lambda: node.comment or "",
            on_save_success_callback=None,
            parent=self,
            enable_comments=False,
            hidden_sections={"input_label_map", "output_file_label", "result_col"},
            label_from_comment=True,
            lock_list_row_controls=True,
            compact_mode=True,
        )
        
        # 隐藏不需要的字段
        config_widget.instance_name_edit.setText(node.name)
        config_widget.instance_name_edit.setDisabled(True)
        config_widget.instance_name_edit.setVisible(False)
        config_widget.current_instance_name = node.name
        config_widget.is_new_tool = False
        if hasattr(config_widget, "basic_group"):
            config_widget.basic_group.setVisible(False)
        save_btn = getattr(config_widget, "save_btn", None)
        if save_btn:
            save_btn.setVisible(False)
        reset_btn = getattr(config_widget, "reset_btn", None)
        if reset_btn:
            reset_btn.setVisible(False)
        if hasattr(config_widget, "delete_btn"):
            config_widget.delete_btn.setVisible(False)
        if hasattr(config_widget, "export_btn"):
            config_widget.export_btn.setVisible(False)
        
        # 隐藏"工具配置"标题和双横线（如果存在）
        # 查找并隐藏"工具配置"标签和分隔线
        for widget in config_widget.findChildren(QLabel):
            if widget.text() == "工具配置":
                widget.setVisible(False)
        
        # 隐藏分隔线（QFrame with HLine shape）
        for widget in config_widget.findChildren(QFrame):
            if widget.frameShape() == QFrame.Shape.HLine:
                widget.setVisible(False)
        
        # 如果是只读，禁用所有输入控件
        if not is_editable:
            config_widget.setEnabled(False)
        
        # 加载配置
        tool_type = node.tool_type
        # 如果提供了同步配置，使用同步配置；否则使用节点配置
        config = sync_config if sync_config is not None else node.config
        
        # 设置工具类型和代码名
        config_widget.tool_type_combo.blockSignals(True)
        config_widget.code_name_combo.blockSignals(True)
        
        try:
            config_widget.tool_type_combo.setCurrentText(tool_type)
            if hasattr(config_widget, "_load_tool_codes"):
                config_widget._load_tool_codes(tool_type)
            
            # 获取code_name
            code_name = config.get("code_name")
            if tool_type == "meta":
                code_name = config.get("code_name", "map")
            
            if code_name:
                index = config_widget.code_name_combo.findText(code_name)
                if index >= 0:
                    config_widget.code_name_combo.setCurrentIndex(index)
            
            # 更新配置表单
            config_widget.update_config_form(config_data=config)
        finally:
            config_widget.tool_type_combo.blockSignals(False)
            config_widget.code_name_combo.blockSignals(False)
        
        container_layout.addWidget(config_widget)
        container.setLayout(container_layout)
        
        return container, config_widget
    
    def on_expand_toggled(self, index: int, tool_name: str, is_first_occurrence: bool, expanded: bool, button: QToolButton):
        """展开/折叠切换"""
        # 获取路径用于日志
        path = self.row_index_map.get(index, ("", ""))[1] if index in self.row_index_map else "unknown"
        logger.debug(f"on_expand_toggled: index={index}, path={path}, tool_name={tool_name}, is_first_occurrence={is_first_occurrence}, expanded={expanded}")
        
        if index not in self.config_containers:
            logger.warning(f"索引 {index} 不在 config_containers 中，可用索引: {list(self.config_containers.keys())}")
            return
        
        container = self.config_containers[index]
        container.setVisible(expanded)
        
        # 更新箭头方向
        button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        
        if expanded:
            self.expanded_tools.add(index)
            # 如果是只读引用（不是第一次出现），需要同步第一次出现的配置
            if not is_first_occurrence:
                # 这是重复出现的，需要同步第一次出现的配置
                if tool_name in self.config_widgets:
                    first_widget = self.config_widgets[tool_name]
                    # 同步配置到当前只读组件
                    self._sync_config_to_readonly(index, first_widget)
        else:
            self.expanded_tools.discard(index)
    
    def _get_node_path(self, node: ToolNode) -> str:
        """获取节点的完整路径"""
        if hasattr(self, "node_path_map") and id(node) in self.node_path_map:
            return self.node_path_map[id(node)]
        return node.name
    
    def _sync_readonly_refs_for_tool(self, tool_name: str):
        """同步指定工具的所有只读引用"""
        if tool_name not in self.config_widgets:
            return
        
        first_widget = self.config_widgets[tool_name]
        first_index = self.first_occurrence.get(tool_name)
        
        # 找到所有引用此工具的只读组件
        for index, (node, path) in self.row_index_map.items():
            if node.name == tool_name and index != first_index:
                # 这是重复出现的，需要同步
                if index in self.config_containers and self.config_containers[index].isVisible():
                    self._sync_config_to_readonly(index, first_widget)
    
    def _sync_config_to_readonly(self, readonly_index: int, source_widget: ToolConfigWidget):
        """同步配置到只读组件"""
        # 获取源组件的配置
        try:
            payload = source_widget.build_payload(require_instance=True)
            config_data = payload.get("config", {})
            
            # 找到只读组件并更新
            if readonly_index in self.config_containers:
                container = self.config_containers[readonly_index]
                # 查找其中的ToolConfigWidget
                readonly_widgets = container.findChildren(ToolConfigWidget)
                for child in readonly_widgets:
                    if not child.isEnabled():  # 只读组件
                        child.tool_type_combo.blockSignals(True)
                        child.code_name_combo.blockSignals(True)
                        try:
                            # 更新配置表单
                            child.update_config_form(config_data=config_data)
                        finally:
                            child.tool_type_combo.blockSignals(False)
                            child.code_name_combo.blockSignals(False)
        except Exception as e:
            logger.error(f"同步配置到只读组件失败: {e}", exc_info=True)
    
    def save_all_tools(self):
        """保存所有工具的配置（去重）"""
        if not self.root_node:
            QMessageBox.warning(self, "错误", "没有加载的工具")
            return
        
        try:
            # 收集所有需要保存的工具（去重，只保存第一次出现的）
            tools_to_save = {}  # 工具名 -> 节点
            
            # 使用 collect_all_tools 遍历整棵树，确保包含 tab 中的子节点
            all_nodes = collect_all_tools(self.root_node)
            for node in all_nodes:
                if node.name not in tools_to_save:
                    tools_to_save[node.name] = node
            
            # 保存每个工具
            saved_count = 0
            errors = []
            
            for tool_name, node in tools_to_save.items():
                if tool_name not in self.config_widgets:
                    continue
                
                config_widget = self.config_widgets[tool_name]
                
                # 获取更新后的配置
                try:
                    # 构建payload
                    payload = config_widget.build_payload(require_instance=True)
                    
                    # 验证
                    err = config_widget.validate_payload(payload, require_instance=True)
                    if err:
                        # 查找节点的路径
                        node_path = self._get_node_path(node)
                        errors.append(f"{node_path}: {err}")
                        continue
                    
                    # 更新工具实例
                    # 对于meta工具，需要保留mode字段；对于single/merge工具，需要保留code_name
                    config_to_save = payload.get("config", {}).copy()
                    
                    # 确保meta工具的mode字段被保留
                    if node.tool_type == "meta":
                        if "mode" not in config_to_save:
                            config_to_save["mode"] = node.config.get("mode", "map")
                    
                    body = {
                        "config": config_to_save,
                        "comment": config_widget.get_comment_callback() if config_widget.get_comment_callback else None,
                    }
                    
                    self.api_client.update_tool_instance(tool_name, body)
                    # 保存成功后重置该工具的修改状态
                    config_widget.mark_saved()
                    saved_count += 1
                    
                except Exception as e:
                    logger.error(f"保存工具失败 {tool_name}: {e}", exc_info=True)
                    # 查找节点的路径
                    node_path = self._get_node_path(node)
                    errors.append(f"{node_path}: {str(e)}")
            
            # 显示结果
            if errors:
                error_msg = "\n".join(errors)
                QMessageBox.warning(
                    self, "部分保存失败",
                    f"成功保存 {saved_count} 个工具\n\n失败的工具:\n{error_msg}"
                )
            else:
                QMessageBox.information(
                    self, "成功",
                    f"已成功保存 {saved_count} 个工具的配置"
                )
                # 发出重置完成信号，通知外部更新保存状态
                self.reset_completed.emit()
            
            # 保存后，同步所有只读引用
            self._sync_all_readonly_refs()
                
        except Exception as e:
            logger.error(f"保存所有工具失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
    
    def reset_all_tools(self):
        """重置所有工具的配置到原始状态"""
        if not self.root_node:
            QMessageBox.warning(self, "错误", "没有加载的工具")
            return
        
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要重置所有工具的配置吗？所有未保存的修改将丢失。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            # 重新加载meta工具，恢复原始配置
            if hasattr(self, '_last_loaded_tool_name') and self._last_loaded_tool_name:
                tool_name = self._last_loaded_tool_name
                self.load_meta_tool(tool_name)
                self.reset_completed.emit()
                QMessageBox.information(self, "成功", "已重置所有工具的配置")
            else:
                QMessageBox.warning(self, "错误", "无法重置：未找到已加载的工具")
        except Exception as e:
            logger.error(f"重置所有工具失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"重置失败: {e}")
    
    def _sync_all_readonly_refs(self):
        """同步所有只读引用到第一次出现的配置"""
        for tool_name, first_widget in self.config_widgets.items():
            first_index = self.first_occurrence.get(tool_name)
            # 找到所有引用此工具的只读组件
            for index, (node, path) in self.row_index_map.items():
                if node.name == tool_name and index != first_index:
                    # 这是重复出现的，需要同步
                    if index in self.config_containers and self.config_containers[index].isVisible():
                        self._sync_config_to_readonly(index, first_widget)
