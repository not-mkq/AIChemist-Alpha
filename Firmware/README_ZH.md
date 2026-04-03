# MA - 多智能体系统

基于 OpenAI Function Calling 的多智能体系统，提供工具调用、审计和会话管理功能。

For English version, please see [README.md](README.md).

## 运行说明

### 1. 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate  # Windows
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 安装前端依赖

```bash
cd frontend
npm install
```

### 4. 启动服务

**启动所有智能体：**

```bash
./scripts/start_agents.sh
```

**启动后端和前端：**

```bash
./scripts/start_app.sh
```

### 5. 访问应用

- 后端 API：http://127.0.0.1:8000
- 前端界面：http://127.0.0.1:5173

## 技术栈

- **后端**: FastAPI, Python, OpenAI SDK
- **前端**: Svelte, Vite, TypeScript
- **数据库**: DuckDB
