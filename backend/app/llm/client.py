"""LLM 客户端封装（DeepSeek / OpenAI，通过 LangChain ChatOpenAI）"""
import logging

from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_llm = None


def get_llm_client() -> ChatOpenAI:
    """返回全局单例 LLM 客户端"""
    global _llm
    if _llm is None:
        if settings.LLM_PROVIDER == "openai":
            _llm = ChatOpenAI(
                model="gpt-4o-mini",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.7,
            )
        else:  # deepseek
            _llm = ChatOpenAI(
                model=settings.DEEPSEEK_MODEL,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                temperature=0.7,
            )
    return _llm


async def agenerate_text(prompt: str) -> str:
    """异步调用 LLM，返回文本内容"""
    llm = get_llm_client()
    resp = await llm.ainvoke(prompt)
    return resp.content if hasattr(resp, "content") else str(resp)
