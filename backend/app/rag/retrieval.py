"""出题时按岗位/难度语义检索题库参考题（优雅降级）"""
import asyncio
import logging

from app.rag.embedding import embed_query
from app.rag.vectorstore import query_embeddings

logger = logging.getLogger(__name__)

COLLECTION = "interview_questions"


async def retrieve_question_references(
    position_name: str,
    interview_type: str,
    difficulty: str,
    industry: str = "",
    k: int = 3,
) -> str:
    """返回格式化参考题库文本；任何失败/空结果返回空字符串"""
    try:
        query_text = " ".join(x for x in [position_name, industry, interview_type] if x)
        if not query_text.strip():
            return ""
        query_vec = await asyncio.to_thread(embed_query, query_text)
        if not query_vec:
            return ""

        # 先按难度过滤检索，结果不足 k 再去掉过滤重试
        hits = await asyncio.to_thread(
            query_embeddings, COLLECTION, query_vec, k, {"difficulty": difficulty}
        )
        if len(hits) < k:
            hits = await asyncio.to_thread(query_embeddings, COLLECTION, query_vec, k)

        if not hits:
            return ""

        lines = ["匹配到的参考题库（供参考或直接选用，避免与之前问过的完全相同）："]
        for i, h in enumerate(hits, 1):
            meta = h.get("metadata") or {}
            lines.append(
                f"{i}. [{meta.get('difficulty', '')}|{meta.get('question_type', '')}] {h.get('document', '')}"
            )
        logger.info(f"题库检索命中 {len(hits)} 条（query={query_text!r}）")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"题库检索失败: {e}")
        return ""
