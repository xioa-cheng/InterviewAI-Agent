"""RAG 向量库封装（ChromaDB 持久化，显式传入向量，优雅降级）"""
import logging
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_vector_store = None


def get_vector_store():
    """懒加载 ChromaDB 持久化客户端；失败时返回 None（RAG 禁用）"""
    global _vector_store
    if _vector_store is None:
        try:
            import chromadb

            _vector_store = chromadb.PersistentClient(path=settings.VECTOR_STORE_PATH)
            logger.info(f"ChromaDB 向量库已初始化: {settings.VECTOR_STORE_PATH}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ChromaDB 初始化失败，RAG 已禁用: {e}")
            _vector_store = False
    return _vector_store if _vector_store is not False else None


def upsert_embeddings(
    collection_name: str,
    ids: List[str],
    documents: List[str],
    embeddings: List[List[float]],
    metadatas: Optional[List[dict]] = None,
) -> None:
    """写入（存在则更新）文档与预计算向量；失败仅告警"""
    store = get_vector_store()
    if not store or not documents:
        return
    try:
        collection = store.get_or_create_collection(collection_name)
        collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"写入向量库失败: {e}")


def query_embeddings(
    collection_name: str,
    query_embedding: List[float],
    k: int = 3,
    where: Optional[dict] = None,
) -> List[dict]:
    """用查询向量检索 top-k，返回 [{id, document, metadata}]；失败返回空列表"""
    store = get_vector_store()
    if not store:
        return []
    try:
        collection = store.get_or_create_collection(collection_name)
        kwargs: dict = {"query_embeddings": [query_embedding], "n_results": k}
        if where:
            kwargs["where"] = where
        results = collection.query(**kwargs)
        ids = (results.get("ids") or [[]])[0]
        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        out = []
        for i, doc in enumerate(docs):
            out.append(
                {
                    "id": ids[i] if i < len(ids) else None,
                    "document": doc,
                    "metadata": (metas[i] if i < len(metas) and metas[i] else {}),
                }
            )
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning(f"向量检索失败: {e}")
        return []
