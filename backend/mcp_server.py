"""InterviewAI MCP Server 启动入口。

用法（在 backend 目录下）：
    python mcp_server.py

随后在 MCP 客户端（Claude Desktop / WorkBuddy / Cursor）中配置本进程为 stdio MCP Server，例如：
{
  "mcpServers": {
    "interviewai": {
      "command": "/绝对路径/backend/.venv/Scripts/python.exe",  # 或 python3
      "args": ["/绝对路径/backend/mcp_server.py"],
      "env": { "OPENAI_API_KEY": "...", "DEEPSEEK_API_KEY": "...", "EMBEDDING_API_KEY": "..." }
    }
  }
}

说明：
- 运行前请确保已安装依赖（含新增的 mcp / langchain-mcp-adapters）：
      pip install -r requirements.txt
- 首次启动会自动建表、预置题库并建立向量索引（与 FastAPI 服务一致）。
- 本进程独立于 FastAPI 服务运行，二者共享同一个数据库文件 / 连接。
"""
import asyncio

from app.mcp.server import ensure_ready, mcp


def main() -> None:
    # 先确保数据库 / 题库 / 索引就绪，再启动 MCP stdio 服务
    asyncio.run(ensure_ready())
    mcp.run()


if __name__ == "__main__":
    main()
