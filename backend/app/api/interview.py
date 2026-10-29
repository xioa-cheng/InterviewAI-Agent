"""面试核心 API：开始面试 / 提交回答 / 获取报告"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.websocket import manager
from app.agent.evaluator.graph import run_evaluator_agent
from app.agent.interviewer.graph import run_interviewer_agent
from app.agent.skill_assessor.graph import run_skill_assessor
from app.cache import cache
from app.database import get_db
from app.models.interview import Interview, QAPair
from app.models.question_bank import SkillAssessment
from app.models.resume import Resume
from app.models.user import User

router = APIRouter(prefix="/api/v1/interviews", tags=["interviews"])

ALLOWED_INTERVIEW_TYPES = {"mixed", "technical", "behavioral", "project", "algorithm", "system_design", "stress"}
ALLOWED_DIFFICULTY = {"easy", "medium", "hard"}


async def _get_resume_context(db: AsyncSession, interview: Interview) -> str:
    """根据面试绑定的简历返回定制出题的上下文"""
    if interview.resume_id:
        row = await db.execute(select(Resume).where(Resume.id == interview.resume_id))
        resume = row.scalar_one_or_none()
        if resume and resume.content:
            return resume.content
    return ""


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


async def _build_history(db: AsyncSession, interview_id) -> list:
    cache_key = f"interview:{interview_id}:history"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(QAPair).where(QAPair.interview_id == interview_id).order_by(QAPair.question_number)
    )
    history = []
    for p in result.scalars().all():
        if p.answer_content:
            history.append(
                {
                    "round": p.question_number,
                    "question": p.question_content,
                    "answer": p.answer_content,
                    "question_type": p.question_type,
                    "score": p.score,
                }
            )
    await cache.set_json(cache_key, history)
    return history


async def _update_overall(db: AsyncSession, interview: Interview) -> None:
    result = await db.execute(select(QAPair).where(QAPair.interview_id == interview.id))
    scores = [p.score for p in result.scalars().all() if p.score is not None]
    if scores:
        interview.overall_score = round(sum(scores) / len(scores), 1)


async def _run_skill_assessment(db: AsyncSession, interview: Interview) -> None:
    """整场面试结束后，用 LLM 做多维度能力评估并落库"""
    history = await _build_history(db, interview.id)
    result = await run_skill_assessor(interview.position_name, history)
    scores = result.get("scores") or {}
    assessment = SkillAssessment(
        user_id=interview.user_id,
        interview_id=interview.id,
        technical_skill=scores.get("technical_skill"),
        communication=scores.get("communication"),
        problem_solving=scores.get("problem_solving"),
        leadership=scores.get("leadership"),
        teamwork=scores.get("teamwork"),
        learning_ability=scores.get("learning_ability"),
        stress_management=scores.get("stress_management"),
    )
    db.add(assessment)
    summary = result.get("summary", "")
    feedback = result.get("feedback", "")
    interview.feedback_summary = f"{summary}\n\n{feedback}".strip() if (summary or feedback) else None


@router.post("/start")
async def start_interview(data: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    interview_type = data.get("interview_type", "mixed")
    position_name = data.get("position_name", "后端开发工程师") or "后端开发工程师"
    difficulty_level = data.get("difficulty_level", "medium")
    if interview_type not in ALLOWED_INTERVIEW_TYPES:
        raise HTTPException(status_code=400, detail="无效的面试类型")
    if difficulty_level not in ALLOWED_DIFFICULTY:
        raise HTTPException(status_code=400, detail="无效的难度")
    if len(position_name) > 200:
        raise HTTPException(status_code=400, detail="岗位名称过长")
    try:
        total_rounds = int(data.get("total_rounds", 5))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="total_rounds 必须是整数")
    total_rounds = max(1, min(10, total_rounds))

    # 解析简历上下文（用于定制出题）
    resume_id = data.get("resume_id")
    resume = None
    if resume_id:
        try:
            rid = uuid.UUID(str(resume_id))
            resume = (
                await db.execute(select(Resume).where(Resume.id == rid, Resume.user_id == user.id))
            ).scalar_one_or_none()
        except ValueError:
            resume = None
    if resume is None:
        resume = (
            await db.execute(
                select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
    context = resume.content if resume and resume.content else ""

    interview = Interview(
        user_id=user.id,
        resume_id=resume.id if resume else None,
        interview_type=interview_type,
        position_name=position_name,
        difficulty_level=difficulty_level,
        total_rounds=total_rounds,
        current_round=1,
        status="ongoing",
    )
    db.add(interview)
    await db.flush()  # 拿到 interview.id

    result = await run_interviewer_agent(
        interview_id=str(interview.id),
        user_id=str(user.id),
        interview_type=interview_type,
        position_name=position_name,
        difficulty_level=difficulty_level,
        current_round=1,
        total_rounds=total_rounds,
        history=[],
        context=context,
    )

    qa = QAPair(
        interview_id=interview.id,
        question_number=1,
        question_type=result.get("question_type"),
        question_content=result.get("current_question", ""),
    )
    db.add(qa)
    await db.commit()
    await manager.broadcast(str(interview.id), {"type": "started", "round": 1})

    return {
        "interview_id": str(interview.id),
        "question": result.get("current_question"),
        "question_type": result.get("question_type"),
        "current_round": 1,
        "total_rounds": total_rounds,
    }


@router.post("/{interview_id}/answer")
async def submit_answer(interview_id: str, data: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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

    answer = data.get("answer", "")

    qa_result = await db.execute(
        select(QAPair)
        .where(QAPair.interview_id == iid)
        .order_by(QAPair.question_number.desc())
        .limit(1)
    )
    qa = qa_result.scalar_one_or_none()
    if qa is None:
        raise HTTPException(status_code=404, detail="当前没有待回答的问题")
    if qa.answer_content:
        raise HTTPException(status_code=400, detail="当前问题已作答")

    await manager.broadcast(str(iid), {"type": "evaluating", "round": qa.question_number})

    # 评估当前回答
    evaluation = await run_evaluator_agent(qa.question_content or "", qa.question_type or "behavioral", answer)

    qa.answer_content = answer
    qa.score = evaluation.get("score")
    qa.strengths = evaluation.get("strengths") or []
    qa.weaknesses = evaluation.get("weaknesses") or []
    qa.suggestions = evaluation.get("suggestions") or []
    qa.model_answer = evaluation.get("model_answer")
    qa.answered_at = datetime.utcnow()

    # 先把当前这轮答案 flush 进数据库（事务尚未提交），
    # 这样下面读历史 / 算总分 / 做能力评估时能查到刚答的这一轮，
    # 而不是等最后 commit 之后才落库、导致追问上下文漏掉最新回答。
    await db.flush()

    completed = False
    next_question = None

    if qa.question_number >= interview.total_rounds:
        interview.status = "completed"
        interview.ended_at = datetime.utcnow()
        completed = True
        await _update_overall(db, interview)
        await _run_skill_assessment(db, interview)
    else:
        history = await _build_history(db, iid)
        context = await _get_resume_context(db, interview)
        result = await run_interviewer_agent(
            interview_id=str(iid),
            user_id=str(interview.user_id),
            interview_type=interview.interview_type,
            position_name=interview.position_name,
            difficulty_level=interview.difficulty_level,
            current_round=qa.question_number + 1,
            total_rounds=interview.total_rounds,
            history=history,
            context=context,
        )
        next_q = QAPair(
            interview_id=iid,
            question_number=qa.question_number + 1,
            question_type=result.get("question_type"),
            question_content=result.get("current_question", ""),
        )
        db.add(next_q)
        interview.current_round = qa.question_number + 1
        next_question = result.get("current_question")

    await db.commit()
    await cache.delete(f"interview:{iid}:history")
    await manager.broadcast(
        str(iid),
        {"type": "evaluated", "round": qa.question_number, "score": qa.score, "completed": completed},
    )
    if completed:
        await manager.broadcast(str(iid), {"type": "completed"})

    return {
        "evaluation": evaluation,
        "completed": completed,
        "current_round": interview.current_round,
        "total_rounds": interview.total_rounds,
        "next_question": next_question,
    }


async def build_report_data(db: AsyncSession, interview_id) -> dict:
    """组装面试报告数据（不含鉴权，供 REST 端点与 MCP Server 共用）。"""
    try:
        iid = uuid.UUID(str(interview_id))
    except ValueError:
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
