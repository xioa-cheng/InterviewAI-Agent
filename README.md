# InterviewAI · AI 面试模拟 Agent

基于 **LLM + Agent + LangGraph + LangChain** 的 AI 面试模拟系统，由三个各司其职的 Agent 协同工作：**面试官 Agent** 根据岗位/简历/历史问答动态生成面试题，**评估官 Agent** 对每轮回答评分点评，**能力评估 Agent** 在面试结束后做多维度能力总结。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · LangGraph · LangChain · SQLAlchemy 2.0 |
| 数据库 | PostgreSQL 15+（本地开发可用 SQLite） |
| 缓存 | Redis 7+（面试历史缓存，优雅降级） |
| 实时通信 | WebSocket（面试事件推送） |
| RAG / 向量库 | ChromaDB + 百炼 text-embedding-v3（题库语义检索） |
| 前端 | Vue 3 · TypeScript · Pinia · Arco Design Vue |
| 部署 | Docker Compose |

## 项目结构

```
面试模拟Agent/
├── backend/            # FastAPI 后端
│   ├── app/
│   │   ├── main.py           # 应用入口
│   │   ├── config.py         # 配置（.env）
│   │   ├── database.py       # 异步 SQLAlchemy
│   │   ├── models/           # ORM 模型
│   │   ├── agent/
│   │   │   ├── interviewer/    # 面试官 Agent（出题，LangGraph）
│   │   │   ├── evaluator/      # 评估官 Agent（逐题评分，LangGraph）
│   │   │   └── skill_assessor/ # 能力评估 Agent（多维度总结，LangGraph）
│   │   ├── llm/              # DeepSeek/OpenAI 客户端
│   │   ├── rag/              # ChromaDB 向量库（题库语义检索）
│   │   ├── cache.py          # Redis 缓存封装（面试历史，优雅降级）
│   │   ├── models/types.py   # JSONB 类型（PG jsonb / SQLite json）
│   │   └── api/              # auth / resume / interview / websocket 路由
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           # Vue 3 前端
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── .env.example        # 配置模板（提交，供他人复制）
└── .env                # 真实配置（勿提交，按模板自建）
```

## 三个 Agent 如何协作

系统由三个各司其职的 Agent 组成，由 API 层（`app/api/interview.py`）按流程编排调用：

| Agent | 职责 | 调用时机 | 产出 |
|---|---|---|---|
| 面试官 Agent（interviewer） | 根据岗位、简历、历史问答、题库动态生成下一道题，支持压力面试等模式 | 开始面试 + 每轮回答后 | 题目 + 题目类型 |
| 评估官 Agent（evaluator） | 对单轮回答评分（0-100），给出优点/不足/建议/参考回答 | 每轮提交回答后 | 分数 + 点评 |
| 能力评估 Agent（skill_assessor） | 综合整场问答做 7 维能力评分 + 总结 + 反馈 | 最后一轮结束后 | 7 维能力分 + 总结 |

7 个评估维度：技术能力、沟通表达、问题解决、领导力、团队协作、学习能力、抗压能力。

每轮流程：面试官出题 → 用户作答 → 评估官评分 →（未结束则）面试官带历史上下文出下一题；最后一轮结束后，能力评估 Agent 生成整场报告。三个 Agent 各自封装为独立的 LangGraph 图（StateGraph），Graph 对象全局复用、每次请求实例化独立状态，避免并发会话状态互相覆盖。

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

## 核心 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/interviews/start` | 开始面试，生成第一题 |
| POST | `/api/v1/interviews/{id}/answer` | 提交回答，返回评估 + 下一题 |
| GET | `/api/v1/interviews/{id}/report` | 获取完整面试报告 |
| WS | `/api/v1/ws/interviews/{id}?token=...` | WebSocket 实时事件推送（出题中/评分完成/面试结束） |
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录 |

> 注：首次使用需先注册账号（`POST /api/v1/auth/register`），登录后即可开始面试。
