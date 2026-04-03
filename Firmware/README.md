# MA - Multi-Agent System

A multi-agent system based on OpenAI Function Calling, providing tool invocation, auditing, and session management capabilities.

For Chinese version, please see [README_ZH.md](README_ZH.md).

## Getting Started

### 1. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Frontend Dependencies

```bash
cd frontend
npm install
```

### 4. Start Services

**Start All Agents:**

```bash
./scripts/start_agents.sh
```

**Start Backend and Frontend:**

```bash
./scripts/start_app.sh
```

### 5. Access the Application

- Backend API: http://127.0.0.1:8000
- Frontend UI: http://127.0.0.1:5173

## Tech Stack

- **Backend**: FastAPI, Python, OpenAI SDK
- **Frontend**: Svelte, Vite, TypeScript
- **Database**: DuckDB
