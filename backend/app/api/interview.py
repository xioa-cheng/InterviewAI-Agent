"""面试核心 API：开始面试 / 提交回答 / 获取报告。

编排全部下沉到 ``app.orchestrator``：本模块只负责
「HTTP 入参校验 → 调用编排层 → 把契约对象转成响应 / 把编排异常转成 HTTP 状态码」。
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.websocket import manager
from app.cache import cache
from app.database import get_db
from app.models.interview import Interview, QAPair
from app.models.question_bank import SkillAssessment
from app.models.user import User
from app.orchestrator.contracts import validate_start_params
from app.orchestrator.errors import OrchestrationError
from app.orchestrator.report import build_report_data  # noqa: F401  保持旧导入路径可用
from app.orchestrator.service import InterviewOrchestrator

router = APIRouter(prefix="/api/v1/interviews", tags=["interviews"])


def _orchestrator(db: AsyncSession) -> InterviewOrchestrator:
    """REST 入口的编排器：走真实 Agent + WebSocket 广播。"""
    return InterviewOrchestrator(db, broadcaster=manager.broadcast)


@router.get("")
async def list_interviews(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """面试历史列表"""
    result = await db.execute(
        select(Interview).where(Interview.user_id == user.id).order_by(Interview.started_at.desc()).limit(50)
    )
    return [
        {
            "interview_id": str(i.id),
            "position_name": i.position_name,
            "interview_type": i.interview_type,
            "difficulty_level": i.difficulty_level,
            "status": i.status,
            "overall_score": i.overall_score,
            "current_round": i.current_round,
            "total_rounds": i.total_rounds,
            "started_at": i.started_at.isoformat() if i.started_at else None,
        }
        for i in result.scalars().all()
    ]


@router.post("/start")
async def start_interview(data: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    error, params = validate_start_params(data)
    if error:
        raise HTTPException(status_code=400, detail=error)

    orch = _orchestrator(db)
    # 解析简历上下文（用于定制出题）
    resume = await orch.resolve_resume(user.id, params.resume_id)
    context = resume.content if resume and resume.content else ""

    result = await orch.start(
        user_id=user.id,
        interview_type=params.interview_type,
        position_name=params.position_name,
        difficulty_level=params.difficulty_level,
        total_rounds=params.total_rounds,
        resume_id=resume.id if resume else None,
        context=context,
        broadcast=True,
    )
    return {
        "interview_id": str(result.interview.id),
        "question": result.question.question,
        "question_type": result.question.question_type,
        "current_round": 1,
        "total_rounds": params.total_rounds,
    }


@router.post("/{interview_id}/answer")
async def submit_answer(interview_id: str, data: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    orch = _orchestrator(db)
    try:
        result = await orch.answer_and_advance(
            interview_id,
            data.get("answer", ""),
            user_id=user.id,
            broadcast=True,
        )
    except OrchestrationError as e:
        raise HTTPException(status_code=e.http_status, detail=e.message)
    return result.to_api_dict()


@router.get("/{interview_id}/report")
async def get_report(interview_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        iid = uuid.UUID(interview_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 interview_id")
    result_row = await db.execute(select(Interview).where(Interview.id == iid))
    interview = result_row.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=404, detail="面试不存在")
    if interview.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该面试")
    return await build_report_data(db, interview_id)


@router.get("/{interview_id}")
async def get_interview(interview_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        iid = uuid.UUID(interview_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 interview_id")

    result_row = await db.execute(select(Interview).where(Interview.id == iid))
    interview = result_row.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=404, detail="面试不存在")
    if interview.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该面试")

    qa_result = await db.execute(
        select(QAPair)
        .where(QAPair.interview_id == iid)
        .order_by(QAPair.question_number.desc())
        .limit(1)
    )
    latest = qa_result.scalar_one_or_none()
    return {
        "interview_id": str(interview.id),
        "position_name": interview.position_name,
        "interview_type": interview.interview_type,
        "difficulty_level": interview.difficulty_level,
        "status": interview.status,
        "current_round": interview.current_round,
        "total_rounds": interview.total_rounds,
        "overall_score": interview.overall_score,
        "current_question": latest.question_content if latest else None,
    }


@router.delete("/{interview_id}")
async def delete_interview(interview_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        iid = uuid.UUID(interview_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的面试 ID")

    interview = (await db.execute(select(Interview).where(Interview.id == iid))).scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=404, detail="面试不存在")
    if interview.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该面试")

    # 先删子表记录（SkillAssessment 无级联、QAPair 需要显式删除），再删面试
    await db.execute(sa_delete(SkillAssessment).where(SkillAssessment.interview_id == iid))
    await db.execute(sa_delete(QAPair).where(QAPair.interview_id == iid))
    await db.execute(sa_delete(Interview).where(Interview.id == iid))
    await db.commit()
    await cache.delete(f"interview:{iid}:history")
    return {"deleted": True}
