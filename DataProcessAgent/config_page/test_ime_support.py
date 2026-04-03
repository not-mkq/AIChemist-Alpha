#!/usr/bin/env python3
"""
测试 PyQt6 在 Wayland 下的输入法支持
"""
import sys
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(reason="IME diagnostics require manual interaction and Wayland session")

def check_qt_platform():
    """检查Qt平台插件"""
    print("=" * 60)
    print("1. 检查 Qt 平台插件")
    print("=" * 60)
    
    try:
        from PyQt6.QtWidgets import QApplication
        # 创建临时应用来检测平台
        app = QApplication(sys.argv)
        platform = app.platformName()
        print(f"✓ Qt 平台插件: {platform}")
        
        if platform == "wayland":
            print("  → 正在使用 Wayland 原生插件")
        elif platform == "xcb":
            print("  → 正在使用 X11/XWayland 插件")
            print("  ⚠ 警告: 如果期望 Wayland 原生支持，请检查:")
            print("    - 是否安装了 qt6-wayland")
            print("    - 环境变量 QT_QPA_PLATFORM 是否设置为 wayland")
        else:
            print(f"  → 未知平台: {platform}")
        
        return platform
    except Exception as e:
        print(f"✗ 无法检测 Qt 平台: {e}")
        return None

def check_ime_framework():
    """检查输入法框架"""
    print("\n" + "=" * 60)
    print("2. 检查输入法框架")
    print("=" * 60)
    
    # 检查环境变量
    qt_im = os.environ.get("QT_IM_MODULE", "未设置")
    gtk_im = os.environ.get("GTK_IM_MODULE", "未设置")
    xmodifiers = os.environ.get("XMODIFIERS", "未设置")
    
    print("环境变量:")
    print(f"  QT_IM_MODULE={qt_im}")
    print(f"  GTK_IM_MODULE={gtk_im}")
    print(f"  XMODIFIERS={xmodifiers}")
    
    # 检测 fcitx5
    fcitx5_detected = False
    fcitx5_qt_detected = False
    
    try:
        result = subprocess.run(
            ["which", "fcitx5"],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            fcitx5_detected = True
            print(f"\n✓ fcitx5 已安装: {result.stdout.strip()}")
            
            # 检查 fcitx5 进程
            try:
                proc_result = subprocess.run(
                    ["pgrep", "-x", "fcitx5"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
                if proc_result.returncode == 0:
                    print(f"  ✓ fcitx5 进程正在运行 (PID: {proc_result.stdout.strip()})")
                else:
                    print("  ⚠ fcitx5 进程未运行")
            except Exception:
                pass
            
            # 检查 fcitx5-qt 插件
            qt_plugin_paths = [
                "/usr/lib/qt6/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so",
                "/usr/lib64/qt6/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so",
                "/usr/local/lib/qt6/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so",
            ]
            
            for path in qt_plugin_paths:
                if Path(path).exists():
                    fcitx5_qt_detected = True
                    print(f"  ✓ fcitx5-qt Qt6 插件已安装: {path}")
                    break
            
            if not fcitx5_qt_detected:
                print("  ✗ fcitx5-qt Qt6 插件未找到")
                print("    提示: 请安装 fcitx5-qt (Arch: fcitx5-qt6, Debian: fcitx5-module-qt6)")
        else:
            print("\n✗ fcitx5 未安装")
    except Exception as e:
        print(f"\n✗ 检测 fcitx5 时出错: {e}")
    
    # 检测 fcitx (旧版)
    fcitx_detected = False
    try:
        result = subprocess.run(
            ["which", "fcitx"],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            fcitx_detected = True
            print(f"\n✓ fcitx (旧版) 已安装: {result.stdout.strip()}")
    except Exception:
        pass
    
    # 检测 ibus
    ibus_detected = False
    ibus_qt_detected = False
    
    try:
        result = subprocess.run(
            ["which", "ibus-daemon"],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            ibus_detected = True
            print(f"\n✓ ibus 已安装: {result.stdout.strip()}")
            
            # 检查 ibus-qt 插件
            qt_plugin_paths = [
                "/usr/lib/qt6/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so",
                "/usr/lib64/qt6/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so",
            ]
            
            for path in qt_plugin_paths:
                if Path(path).exists():
                    ibus_qt_detected = True
                    print(f"  ✓ ibus-qt Qt6 插件已安装: {path}")
                    break
            
            if not ibus_qt_detected:
                print("  ⚠ ibus-qt Qt6 插件未找到")
    except Exception:
        pass
    
    return {
        "fcitx5": fcitx5_detected,
        "fcitx5_qt": fcitx5_qt_detected,
        "fcitx": fcitx_detected,
        "ibus": ibus_detected,
        "ibus_qt": ibus_qt_detected,
        "qt_im_module": qt_im,
    }

def check_wayland_env():
    """检查 Wayland 环境"""
    print("\n" + "=" * 60)
    print("3. 检查 Wayland 环境")
    print("=" * 60)
    
    xdg_session = os.environ.get("XDG_SESSION_TYPE", "未设置")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "未设置")
    display = os.environ.get("DISPLAY", "未设置")
    
    print(f"XDG_SESSION_TYPE={xdg_session}")
    print(f"WAYLAND_DISPLAY={wayland_display}")
    print(f"DISPLAY={display}")
    
    is_wayland = xdg_session == "wayland" or wayland_display
    
    if is_wayland:
        print("\n✓ 检测到 Wayland 环境")
    else:
        print("\n⚠ 未检测到 Wayland 环境（可能是 X11）")
    
    return is_wayland

def test_ime_simple():
    """简单的输入法测试"""
    print("\n" + "=" * 60)
    print("4. 启动简单输入法测试窗口")
    print("=" * 60)
    print("提示: 在输入框中尝试输入中文，看候选框是否正常显示")
    print("按 Ctrl+C 或关闭窗口退出")
    print("=" * 60)
    
    try:
        import os
        from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QTextEdit
        
        # 打印环境变量（用于调试）
        print("GTK_IM_MODULE =", os.environ.get("GTK_IM_MODULE"))
        print("QT_IM_MODULE  =", os.environ.get("QT_IM_MODULE"))
        print("XMODIFIERS    =", os.environ.get("XMODIFIERS"))
        
        app = QApplication(sys.argv)
        
        platform = app.platformName()
        print("Qt platform   =", platform)
        
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
        
    except KeyboardInterrupt:
        print("\n测试已取消")
    except Exception as e:
        print(f"\n✗ 启动测试窗口失败: {e}")
        import traceback
        traceback.print_exc()

def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("PyQt6 Wayland 输入法支持检测工具")
    print("=" * 60)
    
    # 检查系统状态
    platform = check_qt_platform()
    ime_info = check_ime_framework()
    is_wayland = check_wayland_env()
    
    # 总结
    print("\n" + "=" * 60)
    print("5. 总结和建议")
    print("=" * 60)
    
    if platform == "wayland":
        print("✓ 正在使用 Wayland 平台插件")
        
        if ime_info["fcitx5"] and ime_info["fcitx5_qt"]:
            print("✓ fcitx5 和 fcitx5-qt 插件都已安装")
            print("  → 输入法应该可以正常工作")
        elif ime_info["fcitx5"] and not ime_info["fcitx5_qt"]:
            print("⚠ fcitx5 已安装，但 fcitx5-qt Qt6 插件未找到")
            print("  → 请安装 fcitx5-qt6 (Arch) 或 fcitx5-module-qt6 (Debian)")
        elif ime_info["ibus"] and ime_info["ibus_qt"]:
            print("✓ ibus 和 ibus-qt 插件都已安装")
            print("  → 输入法应该可以正常工作")
        else:
            print("⚠ 未检测到完整的输入法支持")
            print("  → 建议安装 fcitx5 + fcitx5-qt6")
    
    elif platform == "xcb":
        print("⚠ 正在使用 X11/XWayland 插件")
        print("  → 输入法行为与 X11 相同")
        if is_wayland:
            print("  → 如果想使用 Wayland 原生支持，请:")
            print("    1. 安装 qt6-wayland")
            print("    2. 设置环境变量: export QT_QPA_PLATFORM=wayland")
    
    # 询问是否启动测试窗口
    print("\n" + "=" * 60)
    try:
        # 检查是否在交互式终端
        if sys.stdin.isatty():
            response = input("是否启动测试窗口来验证输入法? (y/n): ").strip().lower()
            if response == 'y' or response == 'yes':
                test_ime_simple()
        else:
            print("非交互式模式，跳过测试窗口")
            print("提示: 如需测试输入法，请运行: python config-page/test_ime_support.py")
    except (KeyboardInterrupt, EOFError):
        print("\n已取消")

if __name__ == "__main__":
    main()
