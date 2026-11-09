"""面试编排层：把三 Agent 的调度从接口层收归一处。

为什么要有这一层
----------------
重构前，「评分 → 写库 → flush → 轮次判断 → 出下一题 → 收尾能力评估」这套编排
在 REST（api/interview.py）、SSE（api/stream.py）、MCP（mcp/server.py）三个入口
各写了一遍，MCP 甚至需要 ``from app.api.interview import _run_skill_assessment``
import 接口层的私有函数才能复用收尾逻辑。改一处要同步三处。

现在三个入口统一调用 ``InterviewOrchestrator``：
- 编排逻辑只存在一份；
- Agent 之间改用 Pydantic 契约（``contracts.py``）传值，字段写错立即报错；
- 流程校验统一抛 ``errors.py`` 的异常，REST 转 HTTP 状态码、MCP 转 ``{"error": ...}``。

边界说明（不要越界）
--------------------
这里**不是**图编排，也不引入 checkpointer：面试每轮是一次独立 HTTP 请求，
跨请求状态必须以数据库为事实来源（Redis 只做历史缓存）。只有将来要支持
「回退上一轮 / 并行评估 / 人工介入 / 断点续跑」时才值得上 LangGraph + thread_id。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.models.interview import Interview, QAPair
from app.models.question_bank import SkillAssessment
from app.models.resume import Resume
from app.orchestrator.contracts import (
    DEFAULT_QUESTION_TYPE,
    EvaluationOut,
    QuestionOut,
    StepResult,
    Turn,
)
from app.orchestrator.errors import (
    AlreadyAnswered,
    InterviewNotFound,
    InvalidInterviewId,
    NoPendingQuestion,
    PermissionDenied,
)
from app.utils import clamp_score

logger = logging.getLogger(__name__)

# Agent 注入点类型：默认实现走真实 Agent（懒加载，避免本模块被重型依赖污染），
# 测试时可直接注入 fake 函数，无需启动 LLM。
InterviewAgentFn = Callable[[Dict[str, Any]], Awaitable[QuestionOut]]
EvaluateAgentFn = Callable[[str, str, str], Awaitable[EvaluationOut]]
SkillAgentFn = Callable[[str, List[dict]], Awaitable[Dict[str, Any]]]


# --------------------------------------------------------------------------- #
# 默认 Agent 适配器：把「Agent 返回的裸 dict」收敛成契约对象
# --------------------------------------------------------------------------- #
async def _default_interviewer(params: Dict[str, Any]) -> QuestionOut:
    from app.agent.interviewer.graph import run_interviewer_agent

    return QuestionOut.from_agent(await run_interviewer_agent(**params))


async def _default_evaluator(question: str, question_type: str, answer: str) -> EvaluationOut:
    from app.agent.evaluator.graph import run_evaluator_agent

    return EvaluationOut.from_agent(await run_evaluator_agent(question, question_type, answer))


async def _default_skill_assessor(position: str, history: List[dict]) -> Dict[str, Any]:
    from app.agent.skill_assessor.graph import run_skill_assessor

    return await run_skill_assessor(position, history)


# --------------------------------------------------------------------------- #
# 过程对象
# --------------------------------------------------------------------------- #
@dataclass
class PendingTurn:
    """已定位到的「待作答的那一轮」。"""

    interview: Interview
    qa: QAPair

    @property
    def round_no(self) -> int:
        return self.qa.question_number

    @property
    def is_last_round(self) -> bool:
        return self.qa.question_number >= self.interview.total_rounds


@dataclass
class AdvanceOutcome:
    """轮次推进结果：要么收尾，要么拿到下一题。"""

    completed: bool
    next_question: Optional[str] = None
    next_question_type: Optional[str] = None


@dataclass
class StartResult:
    interview: Interview
    question: QuestionOut


# --------------------------------------------------------------------------- #
# 编排器
# --------------------------------------------------------------------------- #
class InterviewOrchestrator:
    """一次请求 / 一个会话内的面试编排器（自身不持有跨请求状态）。

    :param db: 异步会话，事务边界由调用方（接口层）掌握。
    :param interview_agent: 面试官注入点，默认走真实 Agent。
    :param evaluator_agent: 评估官注入点。
    :param skill_agent: 能力评估注入点。
    :param broadcaster: WebSocket 广播函数；None 表示不广播（MCP 入口）。
    :param record_used: 出题后是否累计题库使用频次（供检索做软加权）。
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        interview_agent: Optional[InterviewAgentFn] = None,
        evaluator_agent: Optional[EvaluateAgentFn] = None,
        skill_agent: Optional[SkillAgentFn] = None,
        broadcaster: Optional[Callable[[str, dict], Awaitable[None]]] = None,
        record_used: bool = True,
    ) -> None:
        self.db = db
        self._interview_agent = interview_agent or _default_interviewer
        self._evaluator_agent = evaluator_agent or _default_evaluator
        self._skill_agent = skill_agent or _default_skill_assessor
        self._broadcaster = broadcaster
        self._record_used = record_used

    # ------------------------------------------------------------------ #
    # 启动一场面试
    # ------------------------------------------------------------------ #
    async def resolve_resume(self, user_id, resume_id=None) -> Optional[Resume]:
        """按 resume_id 取简历；未指定或不存在则回退该用户最新一份。"""
        resume = None
        if resume_id:
            try:
                rid = uuid.UUID(str(resume_id))
            except (ValueError, AttributeError, TypeError):
                rid = None
            if rid is not None:
                resume = (
                    await self.db.execute(select(Resume).where(Resume.id == rid, Resume.user_id == user_id))
                ).scalar_one_or_none()
        if resume is None:
            resume = (
                await self.db.execute(
                    select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc()).limit(1)
                )
            ).scalar_one_or_none()
        return resume

    async def create_interview(
        self,
        *,
        user_id,
        interview_type: str,
        position_name: str,
        difficulty_level: str,
        total_rounds: int,
        resume_id=None,
    ) -> Interview:
        # flush（非 commit）：先拿到 interview.id 供出题与落库使用，事务由接口层收口。
        interview = Interview(
            user_id=user_id,
            resume_id=resume_id,
            interview_type=interview_type,
            position_name=position_name,
            difficulty_level=difficulty_level,
            total_rounds=total_rounds,
            current_round=1,
            status="ongoing",
        )
        self.db.add(interview)
        await self.db.flush()
        return interview

    def interviewer_params(
        self,
        interview: Interview,
        *,
        round_no: int,
        history: Optional[List[Turn]] = None,
        context: str = "",
    ) -> Dict[str, Any]:
        """构造面试官 Agent 的入参（流式与非流式共用同一份参数，杜绝两条路径漂移）。"""
        return {
            "interview_id": str(interview.id),
            "user_id": str(interview.user_id),
            "interview_type": interview.interview_type,
            "position_name": interview.position_name,
            "difficulty_level": interview.difficulty_level,
            "current_round": round_no,
            "total_rounds": interview.total_rounds,
            "history": [t.to_agent_dict() for t in (history or [])],
            "context": context,
        }

    async def generate_question(
        self,
        interview: Interview,
        *,
        round_no: int,
        history: Optional[List[Turn]] = None,
        context: str = "",
    ) -> QuestionOut:
        """调用面试官 Agent 出题（非流式）。历史经契约转成 Agent 期望的结构。"""
        return await self._interview_agent(
            self.interviewer_params(interview, round_no=round_no, history=history, context=context)
        )

    async def persist_question(self, interview: Interview, question: QuestionOut, round_no: int) -> QAPair:
        qa = QAPair(
            interview_id=interview.id,
            question_number=round_no,
            question_type=question.question_type,
            question_content=question.question,
        )
        self.db.add(qa)
        if self._record_used:
            await self._record_question_used(question.question)
        await self.db.flush()
        return qa

    async def start(
        self,
        *,
        user_id,
        interview_type: str,
        position_name: str,
        difficulty_level: str,
        total_rounds: int,
        context: str = "",
        resume_id=None,
        broadcast: bool = False,
    ) -> StartResult:
        """REST / MCP 入口：建面试 + 出首题 + 落库 + 提交。"""
        interview = await self.create_interview(
            user_id=user_id,
            interview_type=interview_type,
            position_name=position_name,
            difficulty_level=difficulty_level,
            total_rounds=total_rounds,
            resume_id=resume_id,
        )
        question = await self.generate_question(interview, round_no=1, history=[], context=context)
        if not question.question:
            question = QuestionOut(
                question=f"请介绍一下你自己，以及你应聘{position_name}的核心优势。",
                question_type=DEFAULT_QUESTION_TYPE,
            )
        await self.persist_question(interview, question, 1)
        await self.db.commit()
        if broadcast:
            await self.notify_started(interview.id, 1)
        return StartResult(interview=interview, question=question)

    # ------------------------------------------------------------------ #
    # 历史 / 上下文
    # ------------------------------------------------------------------ #
    async def load_history(self, interview_id, *, use_cache: bool = True) -> List[Turn]:
        """读取已作答轮次（Redis 缓存优先，未命中回库并回写缓存）。"""
        cache_key = f"interview:{interview_id}:history"
        if use_cache:
            cached = await cache.get_json(cache_key)
            if cached is not None:
                return [Turn(**item) for item in cached]
        result = await self.db.execute(
            select(QAPair).where(QAPair.interview_id == interview_id).order_by(QAPair.question_number)
        )
        turns = [
            Turn(
                round=p.question_number,
                question=p.question_content or "",
                question_type=p.question_type or DEFAULT_QUESTION_TYPE,
                answer=p.answer_content or "",
                score=p.score,
            )
            for p in result.scalars().all()
            if p.answer_content
        ]
        if use_cache:
            await cache.set_json(cache_key, [t.to_agent_dict() for t in turns])
        return turns

    async def resume_context(self, interview: Interview) -> str:
        if interview.resume_id:
            row = await self.db.execute(select(Resume).where(Resume.id == interview.resume_id))
            resume = row.scalar_one_or_none()
            if resume and resume.content:
                return resume.content
        return ""

    # ------------------------------------------------------------------ #
    # 收尾：均分 + 能力评估
    # ------------------------------------------------------------------ #
    async def update_overall(self, interview: Interview) -> None:
        result = await self.db.execute(select(QAPair).where(QAPair.interview_id == interview.id))
        scores = [p.score for p in result.scalars().all() if p.score is not None]
        if scores:
            interview.overall_score = round(sum(scores) / len(scores), 1)

    async def run_skill_assessment(self, interview: Interview) -> None:
        """整场结束后用能力评估 Agent 输出 7 维画像并落库。"""
        history = await self.load_history(interview.id)
        result = await self._skill_agent(
            interview.position_name, [t.to_agent_dict() for t in history]
        )
        scores = (result or {}).get("scores") or {}
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
        self.db.add(assessment)
        summary = (result or {}).get("summary", "")
        feedback = (result or {}).get("feedback", "")
        interview.feedback_summary = f"{summary}\n\n{feedback}".strip() if (summary or feedback) else None

    # ------------------------------------------------------------------ #
    # 单轮：定位 → 评分落库 → 推进
    # ------------------------------------------------------------------ #
    async def load_pending_turn(self, interview_id, *, user_id=None) -> PendingTurn:
        """定位面试与当前待作答的一轮；流程校验统一在这里抛错。"""
        try:
            iid = uuid.UUID(str(interview_id))
        except (ValueError, AttributeError, TypeError):
            raise InvalidInterviewId()

        interview = (
            await self.db.execute(select(Interview).where(Interview.id == iid))
        ).scalar_one_or_none()
        if interview is None:
            raise InterviewNotFound()
        if user_id is not None and interview.user_id != user_id:
            raise PermissionDenied()

        qa = (
            await self.db.execute(
                select(QAPair)
                .where(QAPair.interview_id == iid)
                .order_by(QAPair.question_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if qa is None:
            raise NoPendingQuestion()
        if qa.answer_content:
            raise AlreadyAnswered()
        return PendingTurn(interview=interview, qa=qa)

    async def record_evaluation(
        self,
        pending: PendingTurn,
        answer: str,
        evaluation: EvaluationOut,
    ) -> None:
        """把评估官产出写回本轮，并 flush（不 commit）。

        用 flush 而非 commit 是关键：同一事务内，只有 flush 之后后续 SELECT
        才能读到刚写入的这一轮，否则追问上下文会漏掉最新回答、能力评估也会少算一轮。
        """
        qa = pending.qa
        qa.answer_content = answer
        qa.score = clamp_score(evaluation.score)
        qa.strengths = list(evaluation.strengths or [])
        qa.weaknesses = list(evaluation.weaknesses or [])
        qa.suggestions = list(evaluation.suggestions or [])
        qa.model_answer = evaluation.model_answer or ""
        qa.answered_at = datetime.utcnow()
        await self.db.flush()

    async def advance(self, pending: PendingTurn, *, context: Optional[str] = None) -> AdvanceOutcome:
        """推进轮次：末轮收尾，否则出下一题。"""
        interview, qa = pending.interview, pending.qa
        if pending.is_last_round:
            interview.status = "completed"
            interview.ended_at = datetime.utcnow()
            await self.update_overall(interview)
            await self.run_skill_assessment(interview)
            return AdvanceOutcome(completed=True)

        history = await self.load_history(interview.id)
        ctx = context if context is not None else await self.resume_context(interview)
        question = await self.generate_question(
            interview, round_no=qa.question_number + 1, history=history, context=ctx
        )
        if not question.question:
            question = QuestionOut(
                question=f"请继续介绍你在{interview.position_name}方向上的一个代表性项目。",
                question_type=DEFAULT_QUESTION_TYPE,
            )
        await self.persist_question(interview, question, qa.question_number + 1)
        interview.current_round = qa.question_number + 1
        return AdvanceOutcome(
            completed=False,
            next_question=question.question,
            next_question_type=question.question_type,
        )

    async def commit(self, interview_id=None) -> None:
        """提交事务并失效历史缓存。

        缓存是数据库的**副本**，写完必须失效——否则下一轮读到的是上一轮的历史
        （重构前 SSE 入口就漏了这一步）。
        """
        await self.db.commit()
        if interview_id is not None:
            await cache.delete(f"interview:{interview_id}:history")

    async def answer_and_advance(
        self,
        interview_id,
        answer: str,
        *,
        user_id=None,
        context: Optional[str] = None,
        broadcast: bool = False,
    ) -> StepResult:
        """REST / MCP 入口的一站式单轮流程（SSE 走下面的分步方法以支持流式）。"""
        pending = await self.load_pending_turn(interview_id, user_id=user_id)
        if broadcast:
            await self.notify_evaluating(pending.interview.id, pending.round_no)

        evaluation = await self._evaluator_agent(
            pending.qa.question_content or "", pending.qa.question_type or DEFAULT_QUESTION_TYPE, answer
        )
        await self.record_evaluation(pending, answer, evaluation)
        outcome = await self.advance(pending, context=context)
        await self.commit(str(pending.interview.id))

        interview = pending.interview
        if broadcast:
            await self.notify_evaluated(
                interview.id, pending.round_no, pending.qa.score, outcome.completed
            )
            if outcome.completed:
                await self.notify_completed(interview.id)

        return StepResult(
            evaluation=evaluation,
            completed=outcome.completed,
            current_round=interview.current_round,
            total_rounds=interview.total_rounds,
            next_question=outcome.next_question,
            next_question_type=outcome.next_question_type,
        )

    # ------------------------------------------------------------------ #
    # WebSocket 事件（统一在此，避免各入口各写一份）
    # ------------------------------------------------------------------ #
    async def _emit(self, interview_id, message: dict) -> None:
        if self._broadcaster is None:
            return
        try:
            await self._broadcaster(str(interview_id), message)
        except Exception as e:  # noqa: BLE001  广播失败不影响主流程
            logger.warning(f"WebSocket 广播失败: {e}")

    async def notify_started(self, interview_id, round_no: int) -> None:
        await self._emit(interview_id, {"type": "started", "round": round_no})

    async def notify_evaluating(self, interview_id, round_no: int) -> None:
        await self._emit(interview_id, {"type": "evaluating", "round": round_no})

    async def notify_evaluated(self, interview_id, round_no: int, score, completed: bool) -> None:
        await self._emit(
            interview_id,
            {"type": "evaluated", "round": round_no, "score": score, "completed": completed},
        )

    async def notify_completed(self, interview_id) -> None:
        await self._emit(interview_id, {"type": "completed"})

    # ------------------------------------------------------------------ #
    # 内部：题库使用频次（失败静默，不影响主流程）
    # ------------------------------------------------------------------ #
    async def _record_question_used(self, question: str) -> None:
        try:
            from app.rag.retrieval import record_question_used

            await record_question_used(question)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"记录题库使用频次失败（忽略）: {e}")
