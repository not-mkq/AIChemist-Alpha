# DataProcessAgent

**[中文版](README_zh.md)** | English

A general-purpose data processing software designed to streamline complex workflows. Users can break down the data processing workflow into several sub-steps (e.g., data extraction, cleaning, plotting, and calculation) and combine them visually in the UI to form a complete pipeline. 

Each sub-step is implemented as a standalone Python script. The UI automatically parses these scripts and renders their parameters as user-friendly input fields, making it easy to configure without modifying code. It is currently tailored with built-in tools for electrochemical data analysis (LSV, CV, EIS, ECSA, XPS).

## Features

- **Visual Workflow Composition**: Combine Python-based sub-steps (extract, clean, plot, calculate) into complete data pipelines via a user-friendly UI.
- **Auto-Generated UI for Scripts**: Python script parameters are automatically converted into input fields in the frontend.
- **FastAPI Backend**: High-performance async web server
- **Electrochemical Data Processing**: Tools for LSV, CV, EIS, ECSA, and XPS data analysis
- **AI Reporting**: GPT-4o integration for automated quality analysis and reporting
- **Multi-language Support**: Chinese and English profile configurations
- **SQLite Database**: Lightweight data storage

## Installation

### Prerequisites

- Python 3.10 or higher
- Linux (tested on Ubuntu/Debian)

### Install Dependencies

```bash
pip install -r requirements.txt
```

## Running the Application

### Backend Server

```bash
python main.py
```

The backend will start on `http://127.0.0.1:8000` by default.

### Frontend Configuration Page

```bash
python config_page/main.py
```

The frontend is a PyQt6-based GUI for managing tool configurations.

## Project Structure

```
DP_Publish/
├── main.py                 # Backend entry point (FastAPI)
├── config_page/main.py     # Frontend entry point (PyQt6)
├── db.py                   # Database utilities
├── tool_registry.py        # Tool registration
├── tool_runtime.py         # Tool execution runtime
├── config/                 # Configuration files
│   ├── project_config.json
│   ├── label-config.json
│   └── frontend.json
├── tool-instances/         # Tool instance configurations
│   ├── mkq/               # Chinese profile
│   └── mkq_en/            # English profile
├── tools/                  # Tool implementations
│   ├── single/            # Single-purpose tools
│   ├── merge/             # Merge tools
│   └── meta/              # Meta tools
└── routers/                # FastAPI routers
```

## Configuration

### Profiles

The project supports multiple profiles:
- `mkq`: Chinese profile
- `mkq_en`: English profile

Current profile is configured in `config/project_config.json`.

### API Keys

For AI reporting tools (using GPT-4o), the API key is passed at runtime and not stored in configuration files.

## Testing

```bash
pytest
```

## License

GPL-3.0-or-later
