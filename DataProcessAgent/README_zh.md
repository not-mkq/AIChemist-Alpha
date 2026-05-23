# DataProcessAgent

**[English](README.md)** | [中文版]

一个通用的数据处理软件，旨在简化复杂的数据流。用户可以将数据处理的过程拆分成若干子步骤（例如：提取数据、清洗数据、绘图、计算等），并在软件 UI 界面中将各个工具组合起来，实现完整的数据处理流程。

每个子步骤均由 Python 脚本编写。软件 UI 会自动解析脚本参数，并将其转化为待填写的输入框，提供用户友好的操作体验。系统内置了针对电化学数据分析（LSV、CV、EIS、ECSA、XPS）的丰富工具集。

## 功能特性

- **可视化工作流组合**: 在 UI 中将基于 Python 的子步骤组合成完整的数据处理管道。
- **脚本参数 UI 自动化**: Python 脚本的参数自动渲染为前端表单输入框，无需改动代码即可配置。
- **FastAPI 后端**: 高性能异步 Web 服务器
- **电化学数据处理**: 支持 LSV、CV、EIS、ECSA 和 XPS 数据分析工具
- **AI 报告生成**: 集成 GPT-4o 进行自动化质量分析和报告生成
- **多语言支持**: 中英文配置文件支持
- **SQLite 数据库**: 轻量级数据存储

## 安装

### 环境要求

- Python 3.10 或更高版本
- Linux（已在 Ubuntu/Debian 上测试）

### 安装依赖

```bash
pip install -r requirements.txt
```

## 运行应用

### 后端服务器

```bash
python main.py
```

后端默认在 `http://127.0.0.1:8000` 启动。

### 前端配置页面

```bash
python config_page/main.py
```

前端是一个基于 PyQt6 的 GUI，用于管理工具配置。

## 项目结构

```
DP_Publish/
├── main.py                 # 后端入口（FastAPI）
├── config_page/main.py     # 前端入口（PyQt6）
├── db.py                   # 数据库工具
├── tool_registry.py        # 工具注册
├── tool_runtime.py         # 工具运行环境
├── config/                 # 配置文件
│   ├── project_config.json
│   ├── label-config.json
│   └── frontend.json
├── tool-instances/         # 工具实例配置
│   ├── mkq/               # 中文配置
│   └── mkq_en/            # 英文配置
├── tools/                  # 工具实现
│   ├── single/            # 独立工具
│   ├── merge/             # 合并工具
│   └── meta/              # 元工具
└── routers/                # FastAPI 路由
```

## 配置

### 配置文件（Profiles）

项目支持多个配置文件：
- `mkq`: 中文配置
- `mkq_en`: 英文配置

当前配置文件在 `config/project_config.json` 中设置。

### API Key

AI 报告工具（使用 GPT-4o）的 API Key 在运行时传入，不存储在配置文件中。

## 测试

```bash
pytest
```

## 许可证

GPL-3.0-or-later
