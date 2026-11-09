"""面试报告组装（只读）。

从 api/interview.py 迁出：报告组装与"谁在调用"无关，REST 端点与 MCP Server 都要用，
放在接口层会让 MCP 反向依赖 API 模块。
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Interview, QAPair
from app.models.question_bank import SkillAssessment


async def build_report_data(db: AsyncSession, interview_id) -> dict:
    """组装面试报告数据（不含鉴权，供 REST 端点与 MCP Server 共用）。"""
    try:
        iid = uuid.UUID(str(interview_id))
    except (ValueError, AttributeError, TypeError):
        return {"error": "无效的 interview_id"}

    result_row = await db.execute(select(Interview).where(Interview.id == iid))
    interview = result_row.scalar_one_or_none()
    if interview is None:
        return {"error": "面试不存在"}

    qa_result = await db.execute(
        select(QAPair).where(QAPair.interview_id == iid).order_by(QAPair.question_number)
    )
    details = []
    for p in qa_result.scalars().all():
        details.append(
            {
                "question_number": p.question_number,
                "question_type": p.question_type,
                "question": p.question_content,
                "answer": p.answer_content,
                "score": p.score,
                "strengths": p.strengths or [],
                "weaknesses": p.weaknesses or [],
                "suggestions": p.suggestions or [],
                "model_answer": p.model_answer,
            }
        )

    skill_result = await db.execute(
        select(SkillAssessment)
        .where(SkillAssessment.interview_id == iid)
        .order_by(SkillAssessment.assessed_at.desc())
        .limit(1)
    )
    skill = skill_result.scalar_one_or_none()
    skill_scores = None
    if skill:
        skill_scores = {
            "technical_skill": skill.technical_skill,
            "communication": skill.communication,
            "problem_solving": skill.problem_solving,
            "leadership": skill.leadership,
            "teamwork": skill.teamwork,
            "learning_ability": skill.learning_ability,
            "stress_management": skill.stress_management,
        }

    return {
        "interview_id": str(interview.id),
        "position_name": interview.position_name,
        "interview_type": interview.interview_type,
        "status": interview.status,
        "overall_score": interview.overall_score,
        "feedback_summary": interview.feedback_summary,
        "skill_scores": skill_scores,
        "total_rounds": interview.total_rounds,
        "details": details,
    }
