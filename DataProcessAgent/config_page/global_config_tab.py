#!/usr/bin/env python3
"""
global_config_tab.py

全局配置 Tab
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QMessageBox, QGroupBox, QStyle, QFormLayout
from widgets import NoWheelComboBox
import logging

from i18n import tr
from api_client import ApiClient
from ui_theme import apply_card_shadow

logger = logging.getLogger(__name__)


class GlobalConfigTab(QWidget):
    """全局配置 Tab"""
    
    def __init__(self, api_client: ApiClient, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.setup_ui()
        self.load_profiles()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        panel = QGroupBox(tr("tab_global_config"))
        panel_layout = QVBoxLayout()
        panel_layout.setSpacing(12)

        # Profile 选择
        profile_form = QFormLayout()
        profile_label = QLabel(tr("profile"))
        self.profile_combo = NoWheelComboBox()
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        profile_form.addRow(profile_label, self.profile_combo)
        
        # 语言选择
        from i18n import i18n
        lang_label = QLabel("Language:")
        self.lang_combo = NoWheelComboBox()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        
        # 设置当前选中语言
        current_lang = i18n.language
        idx = self.lang_combo.findData(current_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        
        self.lang_combo.currentIndexChanged.connect(self.on_lang_changed)
        profile_form.addRow(lang_label, self.lang_combo)
        
        panel_layout.addLayout(profile_form)
        
        intro = QLabel(tr("sync_hint"))
        intro.setProperty("hint", "muted")
        panel_layout.addWidget(intro)
        
        reload_btn = QPushButton(tr("btn_reload_full"))
        reload_btn.setProperty("variant", "primary")
        reload_btn.setMinimumHeight(44)
        reload_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        reload_btn.clicked.connect(self.reload_all)
        panel_layout.addWidget(reload_btn)

        relabel_btn = QPushButton(tr("btn_relabel_all"))
        relabel_btn.setProperty("variant", "secondary")
        relabel_btn.setMinimumHeight(40)
        relabel_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        relabel_btn.clicked.connect(self.relabel_all)
        panel_layout.addWidget(relabel_btn)
        panel_layout.addStretch()

        panel.setLayout(panel_layout)
        apply_card_shadow(panel)

        layout.addWidget(panel)
        layout.addStretch()
        self.setLayout(layout)

    def on_lang_changed(self, index: int):
        from i18n import i18n
        lang = self.lang_combo.itemData(index)
        if lang != i18n.language:
            i18n.set_language(lang)
            QMessageBox.information(self, tr("success"), "Language changed. Please restart the application for all changes to take effect.")
    
    def load_profiles(self):
        """加载profile列表"""
        try:
            profiles = self.api_client.get_profiles()
            current_profile = self.api_client.get_current_profile()
            
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            self.profile_combo.addItems(profiles)
            
            # 设置当前profile
            idx = self.profile_combo.findText(current_profile)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
            self.profile_combo.blockSignals(False)
        except Exception as e:
            logger.error(f"{tr('msg_load_profiles_failed')}: {e}")
            QMessageBox.warning(self, tr("error"), f"{tr('msg_load_profiles_failed')}: {e}")
    
    def on_profile_changed(self, profile: str):
        """Profile改变时的处理"""
        if not profile:
            return
        try:
            self.api_client.set_current_profile(profile)
            logger.info(f"{tr('msg_profile_switched')}: {profile}")
            
            # 通知主窗口刷新工具列表
            main_window = self.window()
            if hasattr(main_window, 'load_tools'):
                main_window.load_tools()
        except Exception as e:
            logger.error(f"{tr('msg_switch_profile_failed')}: {e}")
            QMessageBox.warning(self, tr("error"), f"{tr('msg_switch_profile_failed')}: {e}")
            # 恢复原来的选择
            self.load_profiles()

    def reload_all(self):
        """加载代码"""
        reply = QMessageBox.question(
            self, tr("confirm"),
            tr("confirm_reload_all"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                result = self.api_client.reload_all()
                codes = result.get("codes", {})
                labels = result.get("labels", {})
                
                # 构建成功消息
                msg_parts = [
                    f"{tr('code_templates')}: total={codes.get('total', 0)}, single={codes.get('single', 0)}, merge={codes.get('merge', 0)}, meta={codes.get('meta', 0)}"
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
                main_window = self.window()
                if hasattr(main_window, 'load_tools'):
                    main_window.load_tools()
                if hasattr(main_window, 'on_templates_loaded'):
                    main_window.on_templates_loaded()
            except Exception as e:
                QMessageBox.warning(self, tr("error"), f"{tr('msg_load_failed')}: {e}")

    def relabel_all(self):
        reply = QMessageBox.question(
            self, tr("confirm"),
            tr("confirm_relabel_all"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            stats = self.api_client.relabel_all()
            QMessageBox.information(
                self,
                tr("done"),
                f"{tr('msg_relabel_done')}: projects={stats.get('projects',0)}, batches={stats.get('batches',0)}, files={stats.get('files',0)}",
            )
        except Exception as e:
            QMessageBox.warning(self, tr("error"), f"{tr('msg_relabel_failed')}: {e}")
