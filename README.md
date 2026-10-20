# InterviewAI · AI 面试模拟 Agent

基于 **LLM + Agent + LangGraph + LangChain** 的 AI 面试模拟系统。面试官 Agent 根据岗位/简历/历史问答动态生成面试题，评估官 Agent 对回答进行评分与点评。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · LangGraph · LangChain · SQLAlchemy 2.0 |
| 数据库 | PostgreSQL 15+（本地开发可用 SQLite） |
| 缓存 | Redis 7+ |
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
│   │   │   ├── interviewer/  # 面试官 Agent（LangGraph）
│   │   │   └── evaluator/    # 评估官 Agent（LangGraph）
│   │   ├── llm/              # DeepSeek/OpenAI 客户端
│   │   ├── rag/              # ChromaDB 向量库
│   │   └── api/              # auth / resume / interview 路由
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           # Vue 3 前端
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
└── .env                # DeepSeek API Key（勿提交）
```

## 部署方式

### 方式一：Docker 一键部署（推荐）

```bash
# 1. 确保已安装 Docker Desktop 并启动
# 2. 在项目根目录配置 .env（已包含 DEEPSEEK_API_KEY）
docker compose up -d --build
```

启动后：
- 前端：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs

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

## 环境变量（backend/.env）

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
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录 |

> 注：首次使用需先注册账号（`POST /api/v1/auth/register`），登录后即可开始面试。
