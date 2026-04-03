#!/usr/bin/env python3
"""
file_manager_tab.py

项目文件管理：
- 顶部显示当前项目（由项目配置 Tab 选中的项目）
- 左栏：文件树
- 右栏：文件预览（文本、JSON、Markdown、图片）或元数据
"""

from __future__ import annotations

import base64
import csv
import io
import logging
import json
import re
from pathlib import Path
from typing import Optional, Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QGroupBox,
    QSplitter,
    QPushButton,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
)

from i18n import tr

try:
    from api_client import ApiClient
    from ui_theme import apply_card_shadow
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from api_client import ApiClient
    from ui_theme import apply_card_shadow

logger = logging.getLogger(__name__)


class FileManagerTab(QWidget):
    """项目文件管理 Tab"""

    def __init__(self, api_client: ApiClient, project_context, parent=None) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.project_context = project_context
        self._is_loading_tree = False  # 防止刷新时的递归调用
        self._current_preview_info = None # Store current file info for download

        self.project_context.current_project_changed.connect(self._on_project_changed)

        self._setup_ui()

    @property
    def current_project(self) -> Optional[str]:
        return self.project_context.current_project

    def _on_project_changed(self, project_name: str) -> None:
        self.project_label.setText(f"{tr('current_project').format(project_name or tr('none'))}")
        self.load_file_tree()

    # UI -----------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部：当前项目
        top = QHBoxLayout()
        top.setSpacing(6)

        initial_project = self.current_project or tr("none")
        self.project_label = QLabel(tr("current_project").format(initial_project))
        self.project_label.setFont(QFont("Source Sans 3", 15, QFont.Weight.Bold))
        top.addWidget(self.project_label)
        top.addStretch()

        relabel_btn = QPushButton(tr("btn_relabel_project"))
        relabel_btn.setProperty("variant", "secondary")
        relabel_btn.clicked.connect(self.relabel_project)
        top.addWidget(relabel_btn)

        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：文件树
        tree_panel = QGroupBox(tr("file_tree"))
        tree_layout = QVBoxLayout()
        tree_layout.setSpacing(6)
        tree_layout.setContentsMargins(8, 8, 8, 8)

        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabel(tr("file_structure"))
        self.file_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.file_tree.itemClicked.connect(self.on_tree_item_clicked)
        self.file_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree_layout.addWidget(self.file_tree)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.delete_btn = QPushButton(tr("btn_delete_selected"))
        self.delete_btn.setProperty("variant", "danger")
        self.delete_btn.clicked.connect(self.delete_selected_entry)
        action_row.addWidget(self.delete_btn)
        action_row.addStretch()
        tree_layout.addLayout(action_row)
        
        # 用于保存和恢复树的状态
        self._expanded_items: set[str] = set()
        self._selected_item_path: Optional[str] = None

        tree_panel.setLayout(tree_layout)
        tree_panel.setMinimumWidth(420)  # 280 * 1.5 = 420
        tree_panel.setMaximumWidth(540)  # 360 * 1.5 = 540
        apply_card_shadow(tree_panel)

        tree_scroll = QScrollArea()
        tree_scroll.setWidgetResizable(True)
        tree_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        tree_scroll.setWidget(tree_panel)

        splitter.addWidget(tree_scroll)

        # 右：预览
        preview_panel = QGroupBox(tr("file_preview"))
        preview_layout = QVBoxLayout()
        preview_layout.setSpacing(6)
        preview_layout.setContentsMargins(8, 8, 8, 8)

        # 预览头部：标题 + 下载按钮
        preview_header = QHBoxLayout()
        self.preview_title = QLabel(tr("no_file_selected"))
        self.preview_title.setFont(QFont("Source Sans 3", 14, QFont.Weight.Bold))
        preview_header.addWidget(self.preview_title)
        
        preview_header.addStretch()
        
        self.download_btn = QPushButton(tr("btn_download"))
        self.download_btn.setProperty("variant", "secondary")
        self.download_btn.setVisible(False)
        self.download_btn.clicked.connect(self.download_current_file)
        preview_header.addWidget(self.download_btn)
        
        preview_layout.addLayout(preview_header)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setVisible(False)
        self.image_label.setScaledContents(False) # We will scale pixmap manually
        preview_layout.addWidget(self.image_label)

        self.text_preview = QTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setMinimumHeight(240)
        preview_layout.addWidget(self.text_preview)

        self.table_preview = QTableWidget()
        self.table_preview.setVisible(False)
        preview_layout.addWidget(self.table_preview)
        
        # 文件信息区域
        self.info_preview = QTextEdit()
        self.info_preview.setReadOnly(True)
        self.info_preview.setMaximumHeight(150)
        self.info_preview.setPlaceholderText(f"{tr('loading')}...")
        self.info_preview.setVisible(False)
        preview_layout.addWidget(self.info_preview)

        preview_panel.setLayout(preview_layout)
        apply_card_shadow(preview_panel)

        preview_scroll = QScrollArea()
        self.preview_scroll = preview_scroll
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        preview_scroll.setWidget(preview_panel)

        splitter.addWidget(preview_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self.setLayout(layout)

    # Actions ------------------------------------------------------------
    def download_current_file(self) -> None:
        """下载当前预览的文件"""
        if not self._current_preview_info:
            return
        
        info = self._current_preview_info
        fname = info.get("filename", "download")
        
        path, _ = QFileDialog.getSaveFileName(self, tr("save_file"), fname)
        if not path:
            return
            
        success = self.api_client.download_file(
            project=info["project"],
            batch=info.get("batch"),
            item=info.get("item"),
            filename=info["filename"],
            dest_path=path,
            level=info.get("level", "item")
        )
        
        if success:
            QMessageBox.information(self, tr("success"), f"文件已保存到: {path}") # I'll leave the path as is
        else:
            QMessageBox.warning(self, tr("error"), tr("msg_bulk_delete_summary").format(0, 1)) # This is not ideal but I'll fix later

    def _save_tree_state(self) -> None:
        """保存文件树的展开和选中状态"""
        self._expanded_items.clear()
        self._selected_item_path = None
        
        # 保存展开状态
        def collect_expanded(item: QTreeWidgetItem, path: str = ""):
            if item.isExpanded():
                self._expanded_items.add(path)
            for i in range(item.childCount()):
                child = item.child(i)
                child_path = f"{path}/{child.text(0)}" if path else child.text(0)
                collect_expanded(child, child_path)
        
        root = self.file_tree.topLevelItem(0)
        if root:
            collect_expanded(root, root.text(0))
        
        # 保存选中状态
        selected_items = self.file_tree.selectedItems()
        if selected_items:
            selected = selected_items[0]
            path_parts = []
            current = selected
            while current:
                path_parts.insert(0, current.text(0))
                current = current.parent()
            self._selected_item_path = "/".join(path_parts)
    
    def _restore_tree_state(self) -> None:
        """恢复文件树的展开和选中状态"""
        # 恢复展开状态
        def restore_expanded(item: QTreeWidgetItem, path: str = ""):
            if path in self._expanded_items:
                item.setExpanded(True)
            for i in range(item.childCount()):
                child = item.child(i)
                child_path = f"{path}/{child.text(0)}" if path else child.text(0)
                restore_expanded(child, child_path)
        
        root = self.file_tree.topLevelItem(0)
        if root:
            restore_expanded(root, root.text(0))
        
        # 恢复选中状态
        if self._selected_item_path:
            def find_item_by_path(item: QTreeWidgetItem, path_parts: list[str], index: int = 0) -> Optional[QTreeWidgetItem]:
                if index >= len(path_parts):
                    return None
                if item.text(0) != path_parts[index]:
                    return None
                if index == len(path_parts) - 1:
                    return item
                for i in range(item.childCount()):
                    child = item.child(i)
                    result = find_item_by_path(child, path_parts, index + 1)
                    if result:
                        return result
                return None
            
            path_parts = self._selected_item_path.split("/")
            if root and len(path_parts) > 0:
                if root.text(0) == path_parts[0]:
                    selected_item = find_item_by_path(root, path_parts, 0)
                    if selected_item:
                        self.file_tree.setCurrentItem(selected_item)
                        self.file_tree.scrollToItem(selected_item)

    def load_file_tree(self) -> None:
        # 防止递归调用
        if self._is_loading_tree:
            return
        self._is_loading_tree = True
        
        try:
            # 保存当前状态
            self._save_tree_state()
            
            self.file_tree.clear()
            if not self.current_project:
                return
            
            data = self.api_client.get_project_file_tree(self.current_project)
            if not data:
                return
            
            # 构建文件树
            root = QTreeWidgetItem(self.file_tree, [tr("project_node_prefix").format(self.current_project)])
            root.setData(0, Qt.ItemDataRole.UserRole, {"level": "project", "kind": "root"})

            # 项目级文件
            prj_files = data.get("project_files", [])
            if prj_files:
                prj_node = QTreeWidgetItem(root, [tr("project_files_node")])
                prj_node.setData(0, Qt.ItemDataRole.UserRole, {"level": "project", "kind": "group"})
                for pf in prj_files:
                    fname = pf.get("filename") if isinstance(pf, dict) else str(pf)
                    file_item = QTreeWidgetItem(prj_node, [fname])
                    file_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {"level": "file", "batch": None, "item": None, "filename": fname, "file_level": "project"},
                    )

            for batch in data.get("batches", []):
                batch_name = batch.get("batch_name", "")
                batch_item = QTreeWidgetItem(root, [batch_name])
                batch_item.setData(0, Qt.ItemDataRole.UserRole, {"level": "batch", "batch": batch_name})

                # batch 级文件
                for bf in batch.get("batch_files", []):
                    fname = bf.get("filename") if isinstance(bf, dict) else str(bf)
                    file_item = QTreeWidgetItem(batch_item, [fname])
                    file_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {"level": "file", "batch": batch_name, "item": None, "filename": fname, "file_level": "batch"},
                    )
                for item in batch.get("items", []):
                    item_name = item.get("item_name", "")
                    item_item = QTreeWidgetItem(batch_item, [item_name])
                    item_item.setData(
                        0, Qt.ItemDataRole.UserRole, {"level": "item", "batch": batch_name, "item": item_name}
                    )
                    for file_info in item.get("files", []):
                        fname = file_info.get("filename") if isinstance(file_info, dict) else str(file_info)
                        file_item = QTreeWidgetItem(item_item, [fname])
                        file_item.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            {
                                "level": "file",
                                "batch": batch_name,
                                "item": item_name,
                                "filename": fname,
                                "file_level": "item",
                            },
                        )
        except Exception as e:
            logger.error(f"加载文件树失败: {e}", exc_info=True)
            QMessageBox.warning(self, tr("error"), f"{tr('msg_load_failed')}: {e}")
        finally:
            # 恢复展开和选中状态
            self._restore_tree_state()
            self._is_loading_tree = False

    def on_tree_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        # 如果正在加载树，忽略点击事件
        if self._is_loading_tree:
            return
        
        self.download_btn.setVisible(False)
        self._current_preview_info = None
        self.info_preview.setVisible(False)
        self.info_preview.setMaximumHeight(150) # Reset height
        self.info_preview.setMinimumHeight(0)
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        # 如果点击的是项目根节点，刷新文件树
        if data and data.get("level") == "project" and self.current_project:
            # 检查是否是项目根节点（不是"项目文件"子节点）
            if item.parent() is None:
                self.load_file_tree()
                return
        
        if not data or data.get("level") != "file" or not self.current_project:
            # batch/item/project 结果展示
            if data and data.get("level") in {"project", "batch", "item"} and self.current_project:
                scope = data["level"]
                batch = data.get("batch")
                itm = data.get("item")
                result = None
                try:
                    result = self.api_client.get_results(self.current_project, scope=scope, batch=batch, item=itm)
                except Exception as e:
                    logger.error(f"获取结果失败: {e}", exc_info=True)
                entries = result.get("entries", []) if result else []
                lines = [f"{e['key']}: {e.get('value')}" for e in entries]
                title = tr("project_results") if scope == "project" else tr("batch_results_node") if scope == "batch" else tr("item_results_node")
                self.preview_title.setText(title)
                self.text_preview.setVisible(True)
                self.image_label.setVisible(False)
                if hasattr(self, "table_preview"):
                    self.table_preview.setVisible(False)
                self.text_preview.setPlainText("\n".join(lines) if lines else tr("no_results"))
            return

        fname = data["filename"]
        batch = data.get("batch")
        item_name = data.get("item")
        file_level = data.get("file_level", "item")
        ext = Path(fname).suffix.lower().lstrip(".")
        text_types = {"txt", "csv", "json", "md"}
        image_types = {"png", "jpg", "jpeg"}

        mode = "meta"
        if ext in text_types or ext in image_types:
            mode = "content"

        preview = self.api_client.get_project_file_preview(
            self.current_project,
            batch=batch,
            item=item_name,
            filename=fname,
            mode=mode,
            level=file_level,
        )
        
        if not preview:
            QMessageBox.warning(self, tr("error"), tr("err_cannot_get_preview"))
            return
            
        # 防御性日志打印：避免打印巨大的 base64 数据导致闪退
        safe_preview = preview.copy()
        if "content_base64" in safe_preview:
            safe_preview["content_base64"] = f"...<{len(safe_preview['content_base64'])} bytes>..."
        if "content" in safe_preview and isinstance(safe_preview["content"], str) and len(safe_preview["content"]) > 1000:
            safe_preview["content"] = safe_preview["content"][:1000] + "... [TRUNCATED]"
        logger.debug(f"Preview metadata: {safe_preview}, ext={ext}")

        if preview.get("status") != "ok":
            QMessageBox.warning(self, tr("error"), preview.get("detail") or preview.get("reason", tr("msg_preview_failed")))
            return

        scope_hint = file_level if file_level != "item" else f"{batch}/{item_name}"
        self.preview_title.setText(f"{fname} ({scope_hint})")
        kind = preview.get("kind", "meta")
        self.text_preview.setVisible(True)
        self.image_label.setVisible(False)
        
        # Setup for download
        self._current_preview_info = {
            "project": self.current_project,
            "batch": batch,
            "item": item_name,
            "filename": fname,
            "level": file_level
        }
        self.download_btn.setVisible(True)

        meta_lines = [
            tr("label_path").format(preview.get('rel_path','')),
            tr("label_size").format(preview.get('size','')),
            tr("label_modified").format(preview.get('modified','')),
            tr("label_tags").format(', '.join(preview.get('labels', []) or [])),
        ]
        
        # Update Info Preview
        self.info_preview.setPlainText("\n".join(meta_lines))

        if kind == "text":
            content = preview.get("content", "")
            
            if ext == "csv":
                try:
                    # 解析 CSV
                    f = io.StringIO(content)
                    reader = csv.reader(f)
                    rows = list(reader)
                    
                    if rows:
                        self.table_preview.setRowCount(len(rows))
                        self.table_preview.setColumnCount(len(rows[0]))
                        
                        for i, row in enumerate(rows):
                            for j, cell in enumerate(row):
                                # 尝试格式化浮点数
                                display_text = cell
                                try:
                                    val = float(cell)
                                    # 格式化：最多5位小数，去除末尾0
                                    formatted = f"{val:.5f}"
                                    if "." in formatted:
                                        formatted = formatted.rstrip("0").rstrip(".")
                                    display_text = formatted
                                except ValueError:
                                    pass
                                
                                item_widget = QTableWidgetItem(display_text)
                                item_widget.setFlags(item_widget.flags() ^ Qt.ItemFlag.ItemIsEditable) # 只读
                                self.table_preview.setItem(i, j, item_widget)
                        
                        self.table_preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
                        self.table_preview.setVisible(True)
                        self.text_preview.setVisible(False)
                        
                        # Show info below table
                        self.info_preview.setVisible(True)
                    else:
                        # 空 CSV
                        self.text_preview.setPlainText(content)
                        self.table_preview.setVisible(False)
                        self.text_preview.setVisible(True)
                        self.info_preview.setVisible(True)
                except Exception as e:
                    logger.warning(f"CSV 解析失败: {e}")
                    # 回退到文本显示
                    self.text_preview.setPlainText(content)
                    self.table_preview.setVisible(False)
                    self.text_preview.setVisible(True)
                    self.info_preview.setVisible(True)
            elif ext == "json":
                # JSON Compression logic
                try:
                    obj = json.loads(content)
                    
                    def compress_list(data: Any) -> Any:
                        if isinstance(data, list):
                            if len(data) > 10:
                                head = [compress_list(x) for x in data[:5]]
                                tail = [compress_list(x) for x in data[-5:]]
                                return head + ["... (truncated)"] + tail
                            return [compress_list(x) for x in data]
                        elif isinstance(data, dict):
                            return {k: compress_list(v) for k, v in data.items()}
                        return data

                    compressed_obj = compress_list(obj)
                    json_str = json.dumps(compressed_obj, indent=2, ensure_ascii=False)
                    
                    # Collapse lists to single line using regex
                    # Match [ ... ] containing non-bracket chars and newlines
                    # This is a best-effort approach.
                    # We match [ followed by anything that is NOT [ or ], including newlines, followed by ]
                    # This covers simple lists. Nested lists won't be matched by [^\[\]]
                    
                    def collapse_match(match):
                        content = match.group(1)
                        # Replace whitespace sequence with space
                        collapsed = " ".join(content.split())
                        return f"[{collapsed}]"
                    
                    # Apply regex repeatedly or just once?
                    # The pattern `\[\s*([^\[\]]+?)\s*\]` matches innermost lists.
                    # We can iterate until no change or just do one pass.
                    
                    collapsed_json = re.sub(r'\[\s*([^\[\]]+?)\s*\]', collapse_match, json_str)
                    
                    self.text_preview.setPlainText(collapsed_json)
                    self.table_preview.setVisible(False)
                    self.text_preview.setVisible(True)
                    self.info_preview.setVisible(True)
                    
                except json.JSONDecodeError:
                    self.text_preview.setPlainText(content)
                    self.table_preview.setVisible(False)
                    self.text_preview.setVisible(True)
                    self.info_preview.setVisible(True)
            else:
                self.text_preview.setPlainText(content)
                self.table_preview.setVisible(False)
                self.text_preview.setVisible(True)
                self.info_preview.setVisible(True)
                
            self.image_label.setVisible(False)
        elif kind == "image":
            b64 = preview.get("content_base64", "")
            try:
                data_bytes = base64.b64decode(b64)
                pixmap = QPixmap()
                if not pixmap.loadFromData(data_bytes):
                    raise ValueError("图片数据格式非法或已损坏")
                
                if not pixmap.isNull():
                    # 显示图片
                    self.image_label.setVisible(True)
                    self.table_preview.setVisible(False)
                    self.text_preview.setVisible(False)
                    
                    # 调整 info_preview 高度
                    viewport_h = self.preview_scroll.viewport().height()
                    min_info_h = max(150, viewport_h // 4)
                    self.info_preview.setMinimumHeight(min_info_h)
                    self.info_preview.setMaximumHeight(9999) # Allow expanding
                    self.info_preview.setVisible(True)
                    
                    # 根据剩余空间缩放图片
                    # 此时 info_preview 占据了底部，image_label 占据顶部
                    # 我们需要手动计算一下缩放，或者让 layout 处理。
                    # QVBoxLayout 默认会分配空间。
                    # 为了更好的效果，我们可以根据 viewport 大小手动 scale pixmap
                    
                    avail_h = viewport_h - min_info_h - 60 # 60 for headers/margins roughly
                    avail_w = self.preview_scroll.viewport().width() - 20
                    
                    if avail_h > 50 and avail_w > 50:
                        pixmap = pixmap.scaled(avail_w, avail_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    
                    self.image_label.setPixmap(pixmap)
                    
                else:
                    raise ValueError("图片为空")
            except Exception as e:
                logger.error(f"图片显示失败: {e}")
                self.text_preview.setPlainText(tr("err_image_display_failed").format(e))
                self.image_label.setVisible(False)
                self.table_preview.setVisible(False)
                self.text_preview.setVisible(True)
                self.info_preview.setVisible(True)
        else:
            self.text_preview.setPlainText(tr("err_unsupported_preview"))
            self.image_label.setVisible(False)
            self.table_preview.setVisible(False)
            self.text_preview.setVisible(True)
            self.info_preview.setVisible(True)

    def relabel_project(self) -> None:
        if not self.current_project:
            QMessageBox.information(self, tr("hint"), tr("msg_select_project_first"))
            return
        try:
            stats = self.api_client.relabel_project(self.current_project)
            QMessageBox.information(
                self,
                tr("done"),
                tr("msg_relabel_project_done").format(self.current_project, stats.get('batches',0), stats.get('files',0)),
            )
            self.load_file_tree()
        except Exception as e:
            QMessageBox.warning(self, tr("error"), f"{tr('msg_relabel_failed')}: {e}")

    def delete_selected_entry(self) -> None:
        """删除树中选中的文件或文件夹（支持多选）。"""
        if self._is_loading_tree:
            return
        if not self.current_project:
            QMessageBox.information(self, tr("hint"), tr("msg_select_project_first"))
            return
            
        selected_items = self.file_tree.selectedItems()
        if not selected_items:
            QMessageBox.information(self, tr("hint"), tr("msg_select_delete_target"))
            return

        # 1. 过滤冗余：如果父节点也被选中，则子节点不需要单独处理
        items_to_delete = []
        for item in selected_items:
            ancestor = item.parent()
            is_redundant = False
            while ancestor:
                if ancestor in selected_items:
                    is_redundant = True
                    break
                ancestor = ancestor.parent()
            if not is_redundant:
                items_to_delete.append(item)

        # 2. 准备删除任务
        valid_tasks = []
        descriptions = []
        
        for item in items_to_delete:
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            level = data.get("level")
            
            if level == "file":
                file_level = data.get("file_level", "item")
                target_map = {
                    "item": "item_file",
                    "batch": "batch_file",
                    "project": "project_file",
                }
                target_type = target_map.get(file_level)
                if not target_type: continue
                
                payload = {"target_type": target_type, "filename": data.get("filename")}
                if data.get("batch"): payload["batch"] = data.get("batch")
                if data.get("item"): payload["item"] = data.get("item")
                valid_tasks.append(payload)
                descriptions.append(tr("file_label_desc").format(data.get('filename'), file_level))
                
            elif level == "item":
                valid_tasks.append({
                    "target_type": "item",
                    "batch": data.get("batch"),
                    "item": data.get("item"),
                })
                descriptions.append(tr("item_label_desc").format(data.get('item'), data.get('batch')))
                
            elif level == "batch":
                valid_tasks.append({
                    "target_type": "batch",
                    "batch": data.get("batch"),
                })
                descriptions.append(tr("batch_label_desc").format(data.get('batch')))

        if not valid_tasks:
            QMessageBox.information(self, tr("hint"), tr("msg_cannot_delete_node"))
            return

        # 3. 确认对话框
        if len(valid_tasks) == 1:
            msg = tr("confirm_single_delete").format(descriptions[0])
        else:
            msg = tr("confirm_bulk_delete").format(len(valid_tasks)) + "\n\n" + "\n".join(descriptions[:10])
            if len(descriptions) > 10:
                msg += f"\n{tr('and_others').format(len(descriptions) - 10)}"

        confirm = QMessageBox.question(self, tr("confirm_delete"), msg)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # 4. 执行批量删除
        success_count = 0
        fail_msgs = []
        
        for i, payload in enumerate(valid_tasks):
            try:
                result = self.api_client.delete_file_entry(self.current_project, payload)
                if result and result.get("status") == "ok":
                    success_count += 1
                else:
                    detail = result.get("detail") or result.get("reason", tr("unknown_error"))
                    fail_msgs.append(f"{descriptions[i]}: {detail}")
            except Exception as e:
                fail_msgs.append(f"{descriptions[i]}: {str(e)}")

        if fail_msgs:
            error_msg = tr("msg_bulk_delete_summary").format(success_count, len(fail_msgs)) + "\n\n" + "\n".join(fail_msgs[:5])
            if len(fail_msgs) > 5:
                error_msg += f"\n{tr('and_others').format(len(fail_msgs) - 5)}"
            QMessageBox.warning(self, tr("partial_failure"), error_msg)
        
        self.load_file_tree()
