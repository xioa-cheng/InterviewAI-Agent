"""百炼(DashScope) OpenAI 兼容向量接口封装（优雅降级）"""
import logging
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_embedder = None

# 百炼 text-embedding-v3 单次请求最多接受 10 条文本，超限会返回 400
_BATCH_SIZE = 10


def get_embedder():
    """懒加载 OpenAIEmbeddings（指向百炼兼容接口）；key 缺失/初始化失败返回 None"""
    global _embedder
    if _embedder is None:
        if not settings.EMBEDDING_API_KEY:
            logger.warning("未配置 EMBEDDING_API_KEY，向量检索已禁用")
            _embedder = False
            return None
        try:
            from langchain_openai import OpenAIEmbeddings

            _embedder = OpenAIEmbeddings(
                model=settings.EMBEDDING_MODEL,
                base_url=settings.EMBEDDING_BASE_URL,
                api_key=settings.EMBEDDING_API_KEY,
                # 百炼兼容接口不做 token 长度预检，必须关闭，否则报 InvalidParameter
                check_embedding_ctx_length=False,
            )
            logger.info(f"向量模型已就绪: {settings.EMBEDDING_MODEL}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"初始化向量模型失败，向量检索已禁用: {e}")
            _embedder = False
    return _embedder if _embedder is not False else None


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """批量文本 -> 向量；失败返回 None"""
    embedder = get_embedder()
    if not embedder or not texts:
        return None
    try:
        vectors: List[List[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            vectors.extend(embedder.embed_documents(batch))
        return vectors
    except Exception as e:  # noqa: BLE001
        logger.warning(f"文本向量化失败: {e}")
        return None


def embed_query(text: str) -> Optional[List[float]]:
    """单条查询 -> 向量；失败返回 None"""
    embedder = get_embedder()
    if not embedder or not text:
        return None
    try:
        return embedder.embed_query(text)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"查询向量化失败: {e}")
        return None
