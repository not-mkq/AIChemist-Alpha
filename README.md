# AIChemist-Alpha

**[中文版](#中文版)** | **[English](#english-version)**

![Architecture Diagram](architecture_diagram_placeholder.png)

---

## English Version

### Project Overview
AIChemist-Alpha is an autonomous campaign platform for scientific discovery, implementing a hierarchical architecture comprising three strictly separated tiers:
1. **Human Researcher**: Specifies objectives, constraints, and evaluation criteria, interacts via the Mission Director, and provides explicit approval when high-risk actions are escalated.
2. **Orchestration Layer**: Coordination and mandatory auditing (Mission Director & Auditor).
3. **Functional Execution Layer**: Specialized scientific agents and the AutoLab robotic platform, managing artifacts via the shared File Bus.

This design enforces strict separation between high-level coordination and functional execution, improving modularity, traceability, information quality, and structured oversight in autonomous campaigns.

### Architecture & Agent Details

#### Orchestration Layer: Coordination and Mandatory Auditing
- **Mission Director (MD)**: The central coordinator, primary conversational interface, and long-horizon campaign manager. It translates researcher-defined objectives into structured tasks, dispatches requests to the functional tier, and maintains campaign state. To support extended campaigns, it operates over a bounded, decision-relevant context and leaves detailed domain-specific inference to functional agents.
- **Auditor**: An independent mandatory safety gateway. It evaluates every request initiated by the MD against format constraints, user-defined rules, and risk criteria, rejecting unsafe cases and escalating high-consequence actions for explicit human approval before downstream actuation.

#### Data Management and Functional Execution
To prevent context saturation while preserving provenance, functional agents operate in strict isolation without direct inter-agent communication, connected by a File Bus.
- **File Agent**: Manages the shared File Bus for artifact persistence and traceable information exchange. It tags, summarizes, and caches file contents for proper routing of inputs and outputs while reducing context contamination.
- **Knowledge Explorer (Reading Agent / Protocol Converter Agent)**: Uses retrieval-augmented generation (RAG) to identify feasible synthesis routes and candidate metal elements from the literature.
- **AutoLab Designer (Synthesis Agent)**: Translates manual protocols into machine-executable instructions and resolves workstation-level dependencies, such as state tracking for consumables and labware.
- **Electrodata Processor (Data Process Agent)**: Addresses data-flooding by ingesting raw electrochemical measurements (LSV, CV, EIS, ECSA, XPS). It performs standardized preprocessing and anomaly detection, compressing high-dimensional signals into decision-grade abstractions (e.g., onset potential, current density, quality metrics).
- **Performance Predictor (Training Agent)**: Consumes validated descriptors within a Bayesian optimization loop to propose new candidate compositions for physical execution by the AutoLab robotic platform.

### Sub-Projects

#### 1. Firmware (MA - Multi-Agent System)
Based on OpenAI Function Calling, providing tool invocation, auditing, and session management capabilities for the Orchestration Layer.

**Quick Start**:
```bash
# 1. Environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Frontend Dependencies
cd frontend && npm install

# 3. Start Agents & App
./scripts/start_agents.sh
./scripts/start_app.sh
```

#### 2. DataProcessAgent (Electrodata Processor)
A data processing backend for electrochemical data analysis.
- **Features**: FastAPI backend, multi-language support, AI reporting via GPT-4o, and specialized tools for LSV, CV, EIS, ECSA, and XPS.

**Quick Start**:
```bash
# Start Backend Server
python main.py

# Start Config UI
python config_page/main.py
```

---

## 中文版

### 项目概述
AIChemist-Alpha 是一个用于科学发现的自主实验平台，采用严格分离的三层分级架构：
1. **人类研究员**：定义目标、约束和评估标准，通过任务主管（Mission Director）进行日常交互，并在审计员升级高风险操作时提供明确审批。
2. **编排层（Orchestration Layer）**：负责顶层协同和强制审计（任务主管与审计员）。
3. **功能执行层（Functional Execution Layer）**：由专业的科学智能体和 AutoLab 机器人平台组成，通过共享文件总线（File Bus）管理数据和伪影。

该设计在顶层协同与底层执行之间实现了严格分离，从而提高了自主实验的模块化程度、可追溯性、信息质量以及结构化监管能力。

### 架构与智能体详解

#### 编排层：协同与强制审计
- **任务主管（Mission Director, MD）**：主要的交互接口和长周期实验协调者。它将研究目标分解为结构化任务，向功能层分发请求并维护状态。MD 不进行具体领域的科学推理（如机制解释），仅在有限决策相关的上下文中负责闭环操作的协同和调度。
- **审计员（Auditor）**：独立的强制安全网关。负责评估 MD 发起的所有跨层请求，检查参数格式、用户规则和风险标准。它会拦截并拒绝不安全的请求，并将高后果操作提交给人类进行显式审批，防止未经检查的请求直接传播到下游。

#### 数据管理与功能执行
为防止上下文饱和同时保留完整的数据来源，功能智能体在严格隔离的环境中运行，不进行直接的节点间通信，仅通过文件总线进行交互。
- **文件智能体（File Agent）**：管理共享的文件总线（File Bus），实现数据的持久化和可追溯交换。它对文件内容进行标记、总结和缓存，支持正确路由智能体的输入输出，在长周期实验中减少上下文污染。
- **知识探索者（Knowledge Explorer）**：利用检索增强生成（RAG）从文献中识别可行的合成路线和候选金属元素。
- **AutoLab 设计师（AutoLab Designer）**：将手动协议转化为机器可执行指令，并解决工作站级别的依赖关系（如耗材和实验室器皿的状态跟踪）。
- **电化学数据处理器（Electrodata Processor / DataProcessAgent）**：为了应对“数据淹没”挑战，它摄入原始的电化学测量数据（如 LSV, CV, EIS 等），进行标准化的预处理和异常检测，并将高维信号压缩为决策级的特征抽象（如起始电位、电流密度及质量指标）。
- **性能预测器（Performance Predictor）**：在贝叶斯优化循环中消耗已验证的特征描述，以提出新的候选组合，并在通过审批后由 AutoLab 机器人平台进行物理执行。

### 子项目说明

#### 1. Firmware (多智能体系统)
基于 OpenAI Function Calling 的多智能体系统，为编排层提供工具调用、审计和会话管理功能。

**运行说明**:
```bash
# 1. 配置环境
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 安装前端依赖
cd frontend && npm install

# 3. 启动智能体和应用
./scripts/start_agents.sh
./scripts/start_app.sh
```

#### 2. DataProcessAgent (电化学数据处理器)
一个通用的数据处理软件。用户可将数据处理过程拆分为由 Python 脚本编写的若干子步骤（提取、清洗、绘图、计算等），在 UI 界面中自由组合以实现完整流程。UI 会将脚本参数自动渲染为输入框，提供友好的操作体验。
- **功能特性**: 可视化工作流组合、脚本参数 UI 自动化、FastAPI 后端、支持中英双语配置、基于 GPT-4o 的 AI 报告生成，以及内置专门针对 LSV、CV、EIS、ECSA 和 XPS 的分析工具。

**运行说明**:
```bash
# 启动后端服务
python main.py

# 启动配置页面
python config_page/main.py
```
