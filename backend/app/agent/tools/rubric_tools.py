"""评分依据工具：把题库该题的参考答案与评分要点（rubric）封装成 Agent 可调用工具。"""
import logging

from langchain_core.tools import tool

from app.rag.retrieval import retrieve_rubric_by_question

logger = logging.getLogger(__name__)


@tool
async def get_rubric(question: str) -> str:
    """根据被问到的问题，从题库语义召回最相近题目的参考答案与评分要点（rubric），用于客观、可解释地评分。

    Args:
        question: 当前被评估的面试题文本。
    """
    try:
        rubric = await retrieve_rubric_by_question(question)
        return rubric or "题库中没有该题的参考答案与评分要点，请基于专业知识评判。"
    except Exception as e:  # noqa: BLE001
        logger.warning(f"评分依据工具异常: {e}")
        return f"获取评分依据失败：{e}"
