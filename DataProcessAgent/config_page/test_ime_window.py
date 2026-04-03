#!/usr/bin/env python3
"""
简单的输入法测试窗口
直接运行此脚本来测试输入法支持
"""
import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QTextEdit
)

def main():
    # 打印输入法相关环境变量，方便调试
    print("GTK_IM_MODULE =", os.environ.get("GTK_IM_MODULE"))
    print("QT_IM_MODULE  =", os.environ.get("QT_IM_MODULE"))
    print("XMODIFIERS    =", os.environ.get("XMODIFIERS"))
    
    app = QApplication(sys.argv)
    
    print("Qt platform   =", app.platformName())  # 应该是 "wayland" 或类似
    
    w = QWidget()
    w.setWindowTitle("Wayland + PyQt IME test")
    layout = QVBoxLayout(w)
    
    info = QLabel(
        "在下面的输入框中试试输入法（例如 fcitx5 下切换到中文）：\n"
        "- QLineEdit：单行输入\n"
        "- QTextEdit：多行输入\n\n"
        "看候选框是否正常、光标位置是否正确。"
    )
    info.setWordWrap(True)
    layout.addWidget(info)
    
    line = QLineEdit()
    line.setPlaceholderText("QLineEdit: 在这里输入")
    layout.addWidget(line)
    
    text = QTextEdit()
    text.setPlaceholderText("QTextEdit: 在这里输入多行文本")
    layout.addWidget(text)
    
    w.resize(500, 300)
    w.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

