# DataProcess Backend

**[中文版](README_zh.md)** | English

A data processing backend for electrochemical data analysis (LSV, CV, EIS, ECSA, XPS).

## Features

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
