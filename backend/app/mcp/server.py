"""InterviewAI 的 MCP Server（基于 FastMCP）。

把面试系统暴露为 MCP 工具，任何兼容 MCP 的客户端（Claude Desktop、WorkBuddy、
Cursor 等）都能直接驱动：检索题库、获取评分标准、评估回答、开始 / 提交面试、获取报告。

工具清单：
- search_interview_questions : 检索题库参考题
- get_question_rubric       : 获取某题参考答案与评分要点
- evaluate_answer           : 评估候选人回答（返回结构化评分）
- generate_next_question    : 生成下一道面试题（纯生成，不落库）
- start_interview           : 开始一场面试并返回首题（按 user_email 绑定用户）
- submit_interview_answer   : 提交某轮回答，返回评分与下一题
- get_interview_report      : 获取面试报告（逐题评分 + 能力雷达）

运行方式见 backend/mcp_server.py 与接入说明文档。
"""
import asyncio
import json
import logging
import uuid

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.agent.evaluator.graph import run_evaluator_agent
from app.agent.interviewer.graph import run_interviewer_agent
from app.agent.tools.question_tools import search_questions
from app.agent.tools.rubric_tools import get_rubric
from app.api.interview import _run_skill_assessment, _update_overall, build_report_data
from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.models.interview import Interview, QAPair
from app.models.user import User
from app.rag.indexing import ensure_question_index, seed_question_bank

logger = logging.getLogger(__name__)

mcp = FastMCP("InterviewAI")


async def ensure_ready() -> None:
    """MCP Server 独立进程启动时，确保数据库 / 题库 / 向量索引就绪（幂等）。"""
    await init_db()
    await seed_question_bank()
    await ensure_question_index()


async def _resolve_user(db, email: str) -> User:
    """按 email 查找用户；不存在则用占位信息自动创建一个服务账号。"""
    if not email:
        email = settings.MCP_DEFAULT_USER_EMAIL or "mcp-service@interviewai.local"
    row = await db.execute(select(User).where(User.email == email))
    user = row.scalar_one_or_none()
    if user is None:
        user = User(
            username=f"mcp_{uuid.uuid4().hex[:8]}",
            email=email,
            password_hash="mcp-disabled",
            full_name="MCP Service",
            role="user",
        )
        db.add(user)
        await db.flush()
        logger.info(f"为 MCP 调用自动创建服务用户：{email}")
    return user


@mcp.tool()
async def search_interview_questions(need: str, position: str = "", difficulty: str = "medium") -> str:
    """在面试题库中检索与面试需求相关的参考题目。

    Args:
        need: 想要考察的能力或主题描述，例如 "Redis 缓存击穿"、"分布式事务一致性"。
        position: 应聘岗位名，用于元数据过滤与术语命中。
        difficulty: 期望难度 easy / medium / hard。
    """
    return await search_questions.ainvoke({"need": need, "position": position, "difficulty": difficulty, "exclude": []})


@mcp.tool()
async def get_question_rubric(question: str) -> str:
    """获取某面试题的参考答案与评分要点（rubric）。

    Args:
        question: 面试题文本。
    """
    return await get_rubric.ainvoke({"question": question})


@mcp.tool()
async def evaluate_answer(question: str, question_type: str, answer: str) -> dict:
    """评估候选人回答，返回结构化评分（分数 / 优点 / 不足 / 建议 / 参考回答）。

    Args:
        question: 面试题文本。
        question_type: 问题类型（technical / behavioral / project / algorithm / system_design）。
        answer: 候选人的回答文本。
    """
    return await run_evaluator_agent(question, question_type, answer)


@mcp.tool()
async def generate_next_question(
    position_name: str,
    interview_type: str = "mixed",
    difficulty_level: str = "medium",
    current_round: int = 1,
    total_rounds: int = 5,
    history_json: str = "[]",
    context: str = "",
) -> dict:
    """生成下一道面试题（纯生成，不落库）。可直接用于自定义编排的面试流程。

    Args:
        position_name: 应聘岗位名。
        interview_type: 面试类型 mixed / technical / behavioral / project / algorithm / system_design / stress。
        difficulty_level: 难度 easy / medium / hard。
        current_round: 当前轮次。
        total_rounds: 总轮次。
        history_json: 历史问答 JSON 字符串，元素含 round/question/answer。
        context: 候选人背景文本。
    """
    try:
        history = json.loads(history_json) if history_json else []
    except (ValueError, TypeError):
        history = []
    return await run_interviewer_agent(
        position_name=position_name,
        interview_type=interview_type,
        difficulty_level=difficulty_level,
        current_round=current_round,
        total_rounds=total_rounds,
        history=history,
        context=context or "",
        user_id="",
    )


@mcp.tool()
async def start_interview(
    position_name: str,
    interview_type: str = "mixed",
    difficulty_level: str = "medium",
    total_rounds: int = 5,
    user_email: str = "",
) -> dict:
    """开始一场面试并返回首个问题。按 user_email 绑定 / 创建用户（缺省使用服务账号）。

    Args:
        position_name: 应聘岗位名。
        interview_type: 面试类型。
        difficulty_level: 难度。
        total_rounds: 总轮次（1~10）。
        user_email: 候选人邮箱（用于绑定用户；不存在则自动创建）。
    """
    total_rounds = max(1, min(10, int(total_rounds)))
    async with AsyncSessionLocal() as db:
        user = await _resolve_user(db, user_email)
        interview = Interview(
            user_id=user.id,
            interview_type=interview_type,
            position_name=position_name,
            difficulty_level=difficulty_level,
            total_rounds=total_rounds,
            current_round=1,
            status="ongoing",
        )
        db.add(interview)
        await db.flush()
        result = await run_interviewer_agent(
            interview_id=str(interview.id),
            user_id=str(user.id),
            interview_type=interview_type,
            position_name=position_name,
            difficulty_level=difficulty_level,
            current_round=1,
            total_rounds=total_rounds,
            history=[],
            context="",
        )
        qa = QAPair(
            interview_id=interview.id,
            question_number=1,
            question_type=result.get("question_type"),
            question_content=result.get("current_question", ""),
        )
        db.add(qa)
        await db.commit()
        return {
            "interview_id": str(interview.id),
            "question": result.get("current_question"),
            "question_type": result.get("question_type"),
            "current_round": 1,
            "total_rounds": total_rounds,
        }


@mcp.tool()
async def submit_interview_answer(interview_id: str, answer: str, user_email: str = "") -> dict:
    """提交某轮回答，返回评分与下一题（末轮则返回 completed=true 与报告入口）。

    Args:
        interview_id: 面试 ID（由 start_interview 返回）。
        answer: 候选人对当前问题的回答。
        user_email: 候选人邮箱（用于校验归属，可选）。
    """
    try:
        iid = uuid.UUID(interview_id)
    except ValueError:
        return {"error": "无效的 interview_id"}

    async with AsyncSessionLocal() as db:
        interview = (await db.execute(select(Interview).where(Interview.id == iid))).scalar_one_or_none()
        if interview is None:
            return {"error": "面试不存在"}

        qa_result = await db.execute(
            select(QAPair).where(QAPair.interview_id == iid).order_by(QAPair.question_number.desc()).limit(1)
        )
        qa = qa_result.scalar_one_or_none()
        if qa is None or qa.answer_content:
            return {"error": "当前没有待回答的问题"}

        evaluation = await run_evaluator_agent(qa.question_content or "", qa.question_type or "behavioral", answer)
        qa.answer_content = answer
        qa.score = evaluation.get("score")
        qa.strengths = evaluation.get("strengths") or []
        qa.weaknesses = evaluation.get("weaknesses") or []
        qa.suggestions = evaluation.get("suggestions") or []
        qa.model_answer = evaluation.get("model_answer")
        await db.flush()

        completed = False
        next_question = None
        if qa.question_number >= interview.total_rounds:
            interview.status = "completed"
            completed = True
            await _update_overall(db, interview)
            await _run_skill_assessment(db, interview)
        else:
            hist_res = await db.execute(
                select(QAPair).where(QAPair.interview_id == iid).order_by(QAPair.question_number)
            )
            history = [
                {
                    "round": p.question_number,
                    "question": p.question_content,
                    "answer": p.answer_content,
                    "question_type": p.question_type,
                    "score": p.score,
                }
                for p in hist_res.scalars().all()
                if p.answer_content
            ]
            result = await run_interviewer_agent(
                interview_id=str(iid),
                user_id=str(interview.user_id),
                interview_type=interview.interview_type,
                position_name=interview.position_name,
                difficulty_level=interview.difficulty_level,
                current_round=qa.question_number + 1,
                total_rounds=interview.total_rounds,
                history=history,
                context="",
            )
            nq = QAPair(
                interview_id=iid,
                question_number=qa.question_number + 1,
                question_type=result.get("question_type"),
                question_content=result.get("current_question", ""),
            )
            db.add(nq)
            interview.current_round = qa.question_number + 1
            next_question = result.get("current_question")

        await db.commit()
        return {
            "evaluation": evaluation,
            "completed": completed,
            "current_round": interview.current_round,
            "total_rounds": interview.total_rounds,
            "next_question": next_question,
        }


@mcp.tool()
async def get_interview_report(interview_id: str, user_email: str = "") -> dict:
    """获取面试报告：逐题评分、优缺点与多维度能力雷达。

    Args:
        interview_id: 面试 ID。
        user_email: 候选人邮箱（可选，仅用于日志）。
    """
    async with AsyncSessionLocal() as db:
        return await build_report_data(db, interview_id)


def run() -> None:
    """供 mcp_server.py 调用的启动入口。"""
    asyncio.run(ensure_ready())
    mcp.run()


if __name__ == "__main__":
    run()
