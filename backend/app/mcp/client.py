"""外部 MCP 工具消费适配器：让 Agent 能加载并调用外部 MCP Server 提供的工具。

设计要点：
- 通过配置 MCP_SERVER_URLS（SSE 地址列表）开启；为空时直接返回 []，不依赖任何外部服务。
- 使用 langchain-mcp-adapters 的 MultiServerMCPClient 拉取工具并缓存（进程级单例）。
- 任何连接 / 导入失败都优雅降级为 []，不影响主流程。
- 此为「可选增强」：接入例如官方 fetch / 搜索类 MCP Server 后，面试官 / 评估官即可获得联网能力。
"""
import logging
from typing import List

from app.config import settings

logger = logging.getLogger(__name__)

_cache_tools: List = None
_cache_client = None


async def load_external_mcp_tools() -> List:
    """加载外部 MCP Server 暴露的工具；未配置或失败时返回空列表。"""
    global _cache_tools, _cache_client
    if _cache_tools is not None:
        return _cache_tools

    _cache_tools = []
    urls = settings.MCP_SERVER_URLS
    if not urls:
        return _cache_tools

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("langchain-mcp-adapters 未安装，跳过外部 MCP 工具加载")
        return _cache_tools

    try:
        servers = {f"srv{i}": {"url": u, "transport": "sse"} for i, u in enumerate(urls)}
        client = MultiServerMCPClient(servers)
        tools = await client.get_tools()
        _cache_tools = list(tools or [])
        _cache_client = client
        logger.info(f"已从外部 MCP 加载 {len(_cache_tools)} 个工具：{urls}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"加载外部 MCP 工具失败（已降级为空）：{e}")
        _cache_tools = []
    return _cache_tools
