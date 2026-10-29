"""LLM 客户端封装（DeepSeek / OpenAI，通过 LangChain ChatOpenAI）"""
import logging
from typing import Any, Optional, Type

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

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


async def agenerate_structured(prompt: str, schema: Type[BaseModel]) -> Optional[dict]:
    """异步调用 LLM 并返回结构化输出（基于 function calling）。

    用 LangChain 的 with_structured_output 替代「提示词里写 JSON + JsonOutputParser」，
    底层走工具调用而非字符串解析，可彻底消除「模型输出包裹 ```json 或被前缀污染 →
    JsonOutputParser 抛异常 → 被 except 静默兜底成默认值（分数70/能力60）」的数据污染问题。
    失败时返回 None，由调用方决定兜底策略。
    """
    llm = get_llm_client()
    try:
        # method="function_calling"：DeepSeek 等 OpenAI 兼容模型支持工具调用，但不支持
        # json_schema 类型的 response_format（会返回 400 This response_format type is unavailable now）。
        structured_llm = llm.with_structured_output(schema, method="function_calling")
        result = await structured_llm.ainvoke(prompt)
        if result is None:
            return None
        return result.model_dump() if hasattr(result, "model_dump") else dict(result)
    except Exception as e:  # noqa: BLE001
        logger.error(f"结构化输出失败: {e}")
        return None


async def astream_text(prompt: str):
    """异步生成器：逐块产出 LLM 文本（真实 astream），用于流式输出 / 打字机效果。

    与 agenerate_text（一次性返回完整文本）不同，本函数边生成边 yield，
    调用方可以按 token 实时推送给前端。纯文本 prompt 不会触发工具调用，chunk 的
    content 即文本片段；遇到 None（如 tool_calls 占位块）则跳过。
    """
    llm = get_llm_client()
    async for chunk in llm.astream(prompt):
        text = getattr(chunk, "content", None)
        if text:
            yield text
