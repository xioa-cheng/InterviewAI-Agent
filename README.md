# InterviewAI · AI 面试模拟 Agent

基于 **LLM + Agent + LangGraph + LangChain** 的 AI 面试模拟系统，由三个各司其职的 Agent 协同工作：**面试官 Agent** 根据岗位/简历/历史问答动态生成面试题，**评估官 Agent** 对每轮回答评分点评，**能力评估 Agent** 在面试结束后做多维度能力总结。三个 Agent 由统一编排层 `app/orchestrator/` 调度，系统同时提供 REST 与 SSE 两套接口，并支持通过 MCP 协议**对外暴露能力**与**接入外部工具**。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · LangGraph · LangChain · SQLAlchemy 2.0 |
| 数据库 | PostgreSQL 15+（本地开发可用 SQLite） |
| 缓存 | Redis 7+（面试历史缓存，优雅降级） |
| 实时通信 | WebSocket（面试事件推送） + SSE（流式出题/评估，逐 token 推送） |
| RAG / 向量库 | ChromaDB + 百炼 text-embedding-v3（混合检索：BM25 + 稠密向量 + RRF 融合） |
| 工具协议 | MCP（FastMCP，双向：消费外部工具 / 暴露自身能力） |
| 前端 | Vue 3 · TypeScript · Pinia · Arco Design Vue |
| 测试 | pytest（编排层全链路 / 三入口一致性 / LLM 超时重试） |
| 部署 | Docker Compose |

## 项目结构

```
面试模拟Agent/
├── backend/            # FastAPI 后端
│   ├── app/
│   │   ├── main.py           # 应用入口（挂载所有 router）
│   │   ├── config.py         # 配置（.env）
│   │   ├── database.py       # 异步 SQLAlchemy
│   │   ├── models/           # ORM 模型
│   │   ├── agent/
│   │   │   ├── interviewer/    # 面试官 Agent（出题，手写 ReAct）
│   │   │   ├── evaluator/      # 评估官 Agent（逐题评分，手写 ReAct）
│   │   │   ├── skill_assessor/ # 能力评估 Agent（多维度总结，LangGraph StateGraph）
│   │   │   ├── tools/          # 工具集：runner(ReAct 引擎)、question/resume/rubric/code 工具、sandbox_guard
│   │   │   └── mcp/            # MCP 适配器：client(消费外部工具) / server(暴露自身能力)
│   │   ├── llm/              # DeepSeek/OpenAI 客户端（function_calling 兼容、超时与重试）
│   │   ├── rag/              # ChromaDB 向量库 + 混合检索 + embedding 缓存
│   │   ├── orchestrator/     # 统一编排层：service(InterviewOrchestrator) / contracts / errors / report
│   │   ├── cache.py          # Redis 缓存封装（面试历史，优雅降级）
│   │   ├── models/types.py   # JSONB 类型（PG jsonb / SQLite json）
│   │   └── api/              # HTTP 适配层：auth / resume / interview / stream / questions / users / websocket
│   ├── mcp_server.py      # 本系统作为 MCP Server 的启动入口（FastMCP，stdio）
│   ├── tests/             # pytest 测试（编排层 / 入口一致性 / LLM 超时重试）
│   ├── pytest.ini
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           # Vue 3 前端（靛蓝浅色主题，含落地页 Landing）
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── .env.example        # 配置模板（提交，供他人复制）
└── .env                # 真实配置（勿提交，按模板自建）
```

## 三个 Agent 如何协作

系统由三个各司其职的 Agent 组成，由**统一编排层** `app/orchestrator/service.py` 中的 `InterviewOrchestrator` 按**确定性流程**调度（普通 Python 轮次循环，而非由一个"总 Agent"调度，也不依赖 LangGraph 编排）。REST（`api/interview.py`）、SSE（`api/stream.py`）、MCP（`mcp/server.py`）三个入口只做参数校验、协议适配与异常转换，不再各自实现一遍编排逻辑：

| Agent | 职责 | 调用时机 | 产出 | 内部实现 |
|---|---|---|---|---|
| 面试官 Agent（interviewer） | 根据岗位、简历、历史问答、题库动态生成下一道题，支持压力面试等模式；内置四重防重复机制（检索排除 + 候选轮换 + 语义去重 + 兜底） | 开始面试 + 每轮回答后 | 题目 + 题目类型 | **手写 ReAct**（LangChain `bind_tools` + `ToolMessage` 回填 + `function_calling` 抽取） |
| 评估官 Agent（evaluator） | 对单轮回答评分（0-100），给出优点/不足/建议/参考回答；评分前必先调 `get_rubric` 取客观依据，可选开代码沙箱 | 每轮提交回答后 | 分数 + 点评 | **手写 ReAct**（同上） |
| 能力评估 Agent（skill_assessor） | 综合整场问答做 7 维能力评分 + 总结 + 反馈 | 最后一轮结束后（一次性） | 7 维能力分 + 总结 + 建议 | **LangGraph `StateGraph`**（单节点 `assess → END`） |

> **关于 LangGraph 的说明**：三个 Agent 之间并未用 LangGraph 编排，编排由普通控制流完成（集中在 `app/orchestrator/service.py`）；LangGraph 仅用于「能力评估 Agent」这一个 Agent 的内部（把它包成单节点状态图）。面试官/评估官借用了 LangChain 的 `bind_tools` 等原语，但工具循环是手写的（`agent/tools/runner.py`），不依赖 LangGraph 执行引擎——这样对结构化输出与失败兜底更可控。编排层刻意不引入图编排 / checkpointer：每轮是一次独立 HTTP 请求，跨请求状态必须以数据库为事实来源（Redis 只做历史缓存）。

7 个评估维度：技术能力、沟通表达、问题解决、领导力、团队协作、学习能力、抗压能力。

每轮流程：面试官出题 → 用户作答 → 评估官评分 →（未结束则）面试官带历史上下文出下一题；最后一轮结束后，能力评估 Agent 生成整场报告。编排器把「评分 → 写库 → flush → 轮次判断 → 出下一题 → 收尾能力评估」收敛为一条链路，并用 Pydantic 契约（`contracts.py`：`StartParams` / `Turn` / `QuestionOut` / `EvaluationOut` / `StepResult`）传值、统一异常（`errors.py` 的 `OrchestrationError` 子类）表达流程校验；REST 转成 HTTP 状态码，MCP 转成 `{"error": ...}`。能力评估 Agent 的 `SkillAssessorState` 等共享状态对象每次请求实例化独立状态，避免并发会话状态互相覆盖。

## 统一编排层与测试

重构前「评分 → 写库 → flush → 轮次判断 → 出下一题 → 收尾能力评估」这套编排在 REST、SSE、MCP 三个入口各写了一遍，MCP 甚至需要反向 `import` 接口层的私有函数才能复用收尾逻辑，改一处要同步三处。现在收归 `app/orchestrator/`：

| 文件 | 职责 |
|---|---|
| `service.py` | `InterviewOrchestrator`：`start` / `answer_and_advance` / `load_history` / `run_skill_assessment` / `commit` / 广播事件 |
| `contracts.py` | Pydantic 契约与开始参数校验，字段写错立即报错 |
| `errors.py` | 流程异常（无效 ID / 404 / 403 / 无待答题 / 已作答），三个入口共用同一套语义与提示语 |
| `report.py` | 报告数据组装（保留旧导入路径可用） |

接口层只保留 HTTP / MCP 协议适配：`api/interview.py`、`api/stream.py` 与 `mcp/server.py` 调用同一个编排器，因此 REST 与 SSE 共用同一套出题/评估逻辑，避免双份提示词漂移。

**测试**：`backend/tests/` 覆盖编排层全链路（开始、中途推进、终局能力评估、历史契约、评分失败不污染均分、分数夹值、缓存失效、广播事件顺序）、三个入口的一致性与错误映射、以及 LLM 超时与重试（重试成功 / 耗尽上抛 / ReAct 重试 / 结构化输出兜底）。运行方式：

```bash
cd backend
python -m pytest -q
```

## MCP 工具调用（双向）

本项目对 MCP 的支持是**双向**的：

1. **消费外部工具（Agent 调用外部 MCP Server）**
   - `app/mcp/client.py` 的 `load_external_mcp_tools()` 在面试官/评估官启动时，加载外部 MCP Server 暴露的工具并注入 Agent 的工具集。
   - 配置项 `MCP_SERVER_URLS`（SSE 地址列表，留空则不加载）；`MCP_DEFAULT_USER_EMAIL` 用于 MCP 连接时自动创建/绑定服务账号。
   - 失败时返回空列表并优雅降级，不影响主流程。

2. **暴露自身能力（本系统作为 MCP Server）**
   - `backend/mcp_server.py`（基于 FastMCP）把以下能力封装为标准 MCP 工具，供外部客户端（Claude Desktop / WorkBuddy / Cursor 等）以 stdio 方式调用：
     - `search_interview_questions` 检索题库参考题
     - `get_question_rubric` 获取参考答案与评分要点
     - `evaluate_answer` 评估回答并返回结构化评分
     - `generate_next_question` 生成下一道题（纯生成，不落库）
     - `start_interview` 开始一场面试并返回首题
   - 流程类工具（`start_interview` 等）同样调用 `InterviewOrchestrator`，不再反向依赖 API 层私有函数。
   - 启动方式（在 `backend` 目录下）：`python mcp_server.py`，首次启动会建表、预置题库并建立向量索引。

## 流式面试（SSE）

除 REST 接口外，系统提供 SSE 流式接口，实现"打字机"式出题与评估：

- `POST /api/v1/stream/start`：开始面试，逐 token 推送首题（首行带 `【题型】` 标记）。
- `POST /api/v1/stream/answer`：提交回答，逐 token 推送评估（带 `【得分】…【参考回答】` 等标记）。

REST、SSE 与 MCP 三个入口**共用同一个 `InterviewOrchestrator` 与同一批 Agent 实现**，避免提示词漂移。SSE 模式下 WebSocket 仍真实可用，关键节点会广播 `started / evaluating / evaluated / completed` 事件。

## 部署方式

### 方式一：Docker 一键部署（推荐）

```bash
# 1. 确保已安装 Docker Desktop 并启动
# 2. 复制配置模板（Windows 用 copy 命令）
cp .env.example .env
# 3. 编辑 .env，至少填入 DEEPSEEK_API_KEY 和 SECRET_KEY
#    （SECRET_KEY 随便填一串足够长的随机字符串即可）
# 4. 启动
docker compose up -d --build
```

启动后：
- 前端：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs

> 首次使用需先注册账号；若在 `.env` 里配置了 `ADMIN_EMAIL`，用该邮箱注册会自动成为管理员。

### 方式二：本地开发

```bash
# 后端
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

> 如需把本系统作为 MCP Server 对外提供能力，另开终端在 `backend` 目录运行 `python mcp_server.py`，再在 MCP 客户端中按 `.env` 中的密钥配置 stdio 启动项。

## 环境变量说明

本项目有两份环境变量文件，用途不同：

- **根目录 `.env`**：Docker Compose 部署时读取（模板见根目录 `.env.example`）。
- **`backend/.env`**：本地开发（非 Docker）时后端直接读取（模板见 `backend/.env.example`）。

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 必填，DeepSeek API 密钥 |
| `DEEPSEEK_MODEL` | 默认 `deepseek-chat` |
| `EMBEDDING_API_KEY` | 百炼(DashScope) 向量密钥，用于 RAG 题库检索 |
| `EMBEDDING_MODEL` | 默认 `text-embedding-v3` |
| `EMBEDDING_BASE_URL` | 百炼 OpenAI 兼容端点 |
| `DATABASE_URL` | 本地 SQLite；Docker 用 PostgreSQL |
| `REDIS_URL` | Redis 连接串 |
| `SECRET_KEY` | JWT 密钥 |
| `MCP_SERVER_URLS` | 外部 MCP Server（SSE）地址列表，留空则不加载外部工具 |
| `MCP_DEFAULT_USER_EMAIL` | MCP Server 自动创建服务账号时使用的邮箱（可选） |
| `ENABLE_CODE_TOOLS` | 是否开启「代码执行」工具（评估官沙箱），默认 `False`，需隔离环境才建议开启 |
| `LLM_TIMEOUT` | 单次 LLM 请求超时（秒），默认 `60`，防止 `ainvoke` 无限挂起卡住整场面试 |
| `LLM_MAX_RETRIES` | SDK 层对连接错误 / 429 / 5xx 的自动重试次数，默认 `2` |
| `LLM_CALL_RETRIES` | 调用层对「超时 / 不可达」的额外重试次数，默认 `1`；耗尽后异常上抛，由 Agent 兜底逻辑处理（题库原题 / `score=None`），不静默返回错误结果 |

## 核心 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/interviews/start` | 开始面试（REST），生成第一题 |
| POST | `/api/v1/interviews/{id}/answer` | 提交回答（REST），返回评估 + 下一题 |
| GET | `/api/v1/interviews/{id}/report` | 获取完整面试报告（逐题明细 + 总分 + 七维能力） |
| POST | `/api/v1/stream/start` | 开始面试（SSE 流式出题） |
| POST | `/api/v1/stream/answer` | 提交回答（SSE 流式评估） |
| GET | `/api/v1/questions` | 题库列表（管理） |
| POST | `/api/v1/questions` | 新增题目 |
| POST | `/api/v1/questions/import` | 批量导入题目 |
| POST | `/api/v1/questions/generate` | 用 LLM 生成题目 |
| POST | `/api/v1/questions/prune` | 清理低质量/重复题目 |
| GET / POST / PUT / DELETE | `/api/v1/questions/{id}` | 单题查询 / 更新 / 删除 |
| WS | `/api/v1/ws/interviews/{id}?token=...` | WebSocket 实时事件推送（出题中/评分完成/面试结束） |
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录 |
| GET | `/api/v1/admin/users` | 管理员：用户管理（需管理员权限） |

> 注：首次使用需先注册账号（`POST /api/v1/auth/register`），登录后即可开始面试；题库管理与用户管理接口需要管理员权限。

## 前端界面

- 采用**靛蓝浅色主题**（无衬线中文字体），包含：登录页（`Login.vue`）、落地页（`Landing.vue`，项目介绍与能力展示）、面试页（`Interview.vue`，实时问答 + 打字机流式展示）、报告页（`Report.vue`，逐题明细 + 总分 + 七维能力雷达）、用户管理页（`UserAdmin.vue`，管理员）。
- 流式展示依赖 SSE：`frontend/src/api/stream.ts` 解析 `【题型】` / `【得分】` 等标记行，将"展示正文"与"结构化数据"分离。
