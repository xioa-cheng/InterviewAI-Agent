"""简历查阅工具：让面试官 Agent 主动读取候选人简历背景。"""
import logging
import uuid

from langchain_core.tools import tool
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.resume import Resume

logger = logging.getLogger(__name__)


@tool
async def lookup_resume(user_id: str) -> str:
    """查询候选人的简历内容（含标题、技能、项目经历等），用于出题时贴合其背景。

    Args:
        user_id: 候选人用户 ID（由系统在上下文中提供）。
    """
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return "无效的 user_id，无法查询简历。"

    try:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(Resume)
                .where(Resume.user_id == uid)
                .order_by(Resume.created_at.desc())
                .limit(1)
            )
            resume = row.scalar_one_or_none()
            if not resume:
                return "未找到该候选人的简历，请基于通用岗位要求出题。"
            parts = [f"简历标题：{resume.title}"]
            if resume.content:
                parts.append(f"简历正文：\n{resume.content}")
            if resume.skills:
                parts.append("技能标签：" + "、".join(str(s) for s in resume.skills))
            if resume.projects:
                parts.append("项目经历：" + "；".join(str(p) for p in resume.projects))
            return "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"简历查阅工具异常: {e}")
        return f"查询简历失败：{e}"
