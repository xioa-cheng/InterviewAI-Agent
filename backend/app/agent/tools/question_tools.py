"""题库检索工具：把 RAG 混合检索（hybrid_retrieve）封装成 Agent 可调用的工具。"""
import logging

from langchain_core.tools import tool

from app.rag.retrieval import hybrid_retrieve

logger = logging.getLogger(__name__)


@tool
async def search_questions(
    need: str,
    position: str = "",
    difficulty: str = "medium",
    exclude: list = None,
) -> str:
    """在面试题库中检索与面试需求相关的参考题目，用于出题时参考或直接选用。

    Args:
        need: 想要考察的能力或主题描述，例如 "Redis 缓存击穿与解决方案"、"分布式事务一致性"。
        position: 应聘岗位名，例如 "后端开发工程师"；用于元数据软过滤与术语命中。
        difficulty: 期望难度，取值 easy / medium / hard。
        exclude: 已经问过的题目文本列表，避免重复出题。
    """
    try:
        selected = await hybrid_retrieve(
            position_name=position,
            interview_type="mixed",
            difficulty=difficulty or "medium",
            industry="",
            k=3,
            context=need,
            exclude_questions=exclude or [],
        )
        if not selected:
            return "题库中没有找到相关参考题目。"
        lines = [
            f"{i}. [{r.get('difficulty', '')}|{r.get('question_type', '')}] {r.get('question_content', '')}"
            for i, r in enumerate(selected, 1)
        ]
        return "匹配到的参考题库（供参考或选用，避免与已问过的完全相同）：\n" + "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"题库检索工具异常: {e}")
        return f"题库检索失败：{e}"
