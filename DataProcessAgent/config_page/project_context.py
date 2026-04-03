#!/usr/bin/env python3
"""
project_context.py

项目上下文管理：
- 管理当前项目状态 (current_project)
- 管理项目列表 (project_list, local_projects)
- 提供项目操作接口 (import_zip, export_zip, create_project)
- 发出状态变更信号
"""

import logging
from typing import Optional, List, Set

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QFileDialog, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QApplication, QWidget

try:
    from api_client import ApiClient
except ImportError:
    from .api_client import ApiClient

logger = logging.getLogger(__name__)


class ProjectContext(QObject):
    """项目上下文管理器"""

    # 信号
    project_list_changed = pyqtSignal()  # 项目列表变更（加载、新建、导入后）
    current_project_changed = pyqtSignal(str)  # 当前选中项目变更
    
    def __init__(self, api_client: ApiClient, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        
        self._current_project: Optional[str] = None
        self._project_list: List[str] = []
        self._local_projects: Set[str] = set()  # 前端占位项目（未真实创建）

    @property
    def current_project(self) -> Optional[str]:
        return self._current_project

    @property
    def project_list(self) -> List[str]:
        return self._project_list
        
    @property
    def local_projects(self) -> Set[str]:
        return self._local_projects

    def load_projects(self) -> None:
        """从后端加载项目列表，合并本地占位项目"""
        try:
            projects = self.api_client.get_projects()
            # 清理：如果本地占位项目已在后端存在，移除占位标记
            for name in list(self._local_projects):
                if name in projects:
                    self._local_projects.remove(name)
            
            # 合并列表：后端项目 + 本地占位项目
            # 保持后端项目的顺序，将本地项目追加在后（或根据需求排序）
            combined = list(projects)
            for local in self._local_projects:
                if local not in combined:
                    combined.append(local)
            
            self._project_list = combined
            self.project_list_changed.emit()
            
            # 如果当前项目不在列表中（且列表不为空），重置当前项目
            if self._current_project and self._current_project not in self._project_list:
                self.set_current_project(None)
            
            # 如果当前没有选中项目，且列表不为空，默认选中第一个
            if not self._current_project and self._project_list:
                first_project = self._project_list[0]
                logger.info(f"自动选中默认项目: {first_project}")
                self.set_current_project(first_project)
                
        except Exception as e:
            logger.error(f"加载项目列表失败: {e}")
            # 不弹窗，避免启动时干扰，仅日志记录
            
    def set_current_project(self, project_name: Optional[str], force: bool = False) -> None:
        """切换当前项目"""
        if not force and self._current_project == project_name:
            return
        
        self._current_project = project_name
        self.current_project_changed.emit(project_name or "")

    def create_local_project(self, name: str) -> bool:
        """创建本地占位项目"""
        name = name.strip()
        if not name:
            return False
            
        if name in self._project_list:
            return False
            
        self._local_projects.add(name)
        self._project_list.append(name)
        self.project_list_changed.emit()
        self.set_current_project(name)
        return True

    def import_zip(self, parent_widget: QWidget) -> None:
        """导入 ZIP 文件的完整流程（包含UI交互）"""
        if not self._current_project:
            QMessageBox.warning(parent_widget, "错误", "请先选择项目")
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            parent_widget, "选择 ZIP 文件", "", "ZIP Files (*.zip)"
        )
        if not file_path:
            return
            
        # 弹出配置对话框
        dialog = QDialog(parent_widget)
        dialog.setWindowTitle("上传 ZIP 文件")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # ... (复用原有的 UI 构建逻辑，这里简化为核心逻辑) ...
        # 为避免代码重复，最好是将 UploadDialog 封装为独立类，或者在这里构建
        
        # 简单起见，这里直接构建 UI
        from widgets import NoWheelComboBox
        
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("上传类型:"))
        type_combo = NoWheelComboBox()
        type_combo.addItems(["batch", "item", "files"])
        type_combo.setCurrentText("batch")
        type_layout.addWidget(type_combo)
        layout.addLayout(type_layout)
        
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("Batch 前缀:"))
        batch_edit = QLineEdit("Batch")
        batch_layout.addWidget(batch_edit)
        layout.addLayout(batch_layout)
        
        item_layout = QHBoxLayout()
        item_layout.addWidget(QLabel("Item 前缀:"))
        item_edit = QLineEdit("Item")
        item_layout.addWidget(item_edit)
        layout.addLayout(item_layout)
        
        layout.addWidget(QLabel(f"文件: {file_path}"))
        
        btn_layout = QHBoxLayout()
        upload_btn = QPushButton("上传")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(upload_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        dialog.setLayout(layout)
        
        def do_upload():
            upload_type = type_combo.currentText()
            batch_prefix = batch_edit.text().strip()
            item_prefix = item_edit.text().strip()
            
            dialog.accept()
            self._execute_upload(
                parent_widget, 
                file_path, 
                upload_type, 
                batch_prefix, 
                item_prefix
            )
            
        upload_btn.clicked.connect(do_upload)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()

    def _execute_upload(self, parent_widget, file_path, upload_type, batch_prefix, item_prefix):
        # 进度提示
        progress = QMessageBox(parent_widget)
        progress.setWindowTitle("上传中")
        progress.setText(f"正在上传 ZIP 文件...\n项目: {self._current_project}")
        progress.setStandardButtons(QMessageBox.StandardButton.NoButton)
        progress.setModal(False)
        progress.show()
        QApplication.processEvents()
        
        try:
            result = self.api_client.upload_zip(
                project=self._current_project,
                file_path=file_path,
                upload_type=upload_type,
                batch_prefix=batch_prefix,
                item_prefix=item_prefix
            )
            
            progress.hide()
            progress.deleteLater()
            
            if result.get("status") == "error":
                QMessageBox.warning(parent_widget, "错误", f"上传失败: {result.get('detail')}")
            elif "project" in result or "batch" in result:
                self._handle_upload_success(parent_widget, result)
            else:
                QMessageBox.warning(parent_widget, "警告", f"响应格式未知: {result}")
                
        except Exception as e:
            progress.hide()
            progress.deleteLater()
            logger.error(f"上传失败: {e}", exc_info=True)
            QMessageBox.warning(parent_widget, "上传失败", str(e))

    def _handle_upload_success(self, parent_widget, result):
        batch = result.get("batch", "")
        items = result.get("items", [])
        msg = f"上传成功！\n批次: {batch}\n项目项: {len(items)} 个"
        QMessageBox.information(parent_widget, "成功", msg)
        
        # 刷新列表（这会移除本地占位标记）
        self.load_projects()
        
        # 确保当前项目选中（后端可能会规范化项目名）
        returned_project = result.get("project") or self._current_project
        if returned_project:
            self.set_current_project(returned_project, force=True)

    def export_zip(self, parent_widget: QWidget) -> None:
        if not self._current_project:
            QMessageBox.warning(parent_widget, "错误", "请先选择项目")
            return
            
        if self._current_project in self._local_projects:
            QMessageBox.warning(parent_widget, "错误", "该项目尚未导入数据，无法导出")
            return

        default_name = f"{self._current_project}.zip"
        save_path, _ = QFileDialog.getSaveFileName(
            parent_widget, "保存 ZIP", default_name, "ZIP Files (*.zip)"
        )
        if not save_path:
            return

        if not save_path.lower().endswith(".zip"):
            save_path += ".zip"

        try:
            self.api_client.export_project_zip(self._current_project, save_path)
            QMessageBox.information(parent_widget, "成功", f"导出成功:\n{save_path}")
        except Exception as e:
            logger.error(f"导出 ZIP 失败: {e}", exc_info=True)
            QMessageBox.warning(parent_widget, "错误", f"导出失败: {e}")
