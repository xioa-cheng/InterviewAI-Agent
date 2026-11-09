"""流式面试 API（SSE）：出题 / 评估均通过「真正的 ReAct Agent」流式产出。

设计要点（本轮统一）：
- 出题与评估都复用面试官 / 评估官 Agent（run_interviewer_agent_stream /
  run_evaluator_agent_stream），它们会自主调用工具（检索题库、查简历、取 rubric、
  验证代码），与 REST 路径（interview.py）共用同一套 Agent，彻底消除「双实现漂移」。
- 采用 Server-Sent Events（text/event-stream）做服务端 → 客户端单向文本流，逐 token 推送。
- 出题：Agent 流式输出题目正文，首行带 `【题型】xxx` 标记；前端做打字机展示，
  服务端解析首行得到 question_type 落库（不污染评分/题型数据）。
- 评估：Agent 流式输出评估叙述，带 `【得分】/【优点】/【不足】/【建议】/【参考回答】`
  标记；正文（非标记行）实时推送，完整后解析各标记得到结构化字段落库。
  若标记解析失败，用 agenerate_structured(EvaluationOutput) 兜底（仍结构化，不静默默认）。
  彻底失败则标记为 evaluation_failed、score 存 None（绝不伪造 70 分）。
- 关键节点通过 WebSocket ConnectionManager 广播事件（started / evaluating / done /
  completed），使 WebSocket 在 SSE 流程下也真实可用。
- **编排（写库 / flush / 轮次推进 / 收尾能力评估 / 缓存失效）统一由
  ``app.orchestrator.InterviewOrchestrator`` 负责**，与 REST、MCP 共用同一份逻辑；
  本模块只保留「必须写在生成器体内」的流式循环。
- 每个请求内部用独立的 AsyncSessionLocal 管理事务，避免依赖注入会话在流式期间被回收。
"""
import logging
import re
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.websocket import manager
from app.agent.evaluator.graph import run_evaluator_agent_stream
from app.agent.interviewer.graph import run_interviewer_agent_stream
from app.database import AsyncSessionLocal
from app.llm.client import agenerate_structured
from app.models.user import User
from app.orchestrator.contracts import (
    DEFAULT_QUESTION_TYPE,
    EvaluationOut,
    QuestionOut,
    validate_start_params,
)
from app.orchestrator.errors import OrchestrationError
from app.orchestrator.service import InterviewOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/stream", tags=["stream"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲，保证实时推送
}


def _sse(event: dict) -> str:
    import json

    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _orchestrator(db: AsyncSession) -> InterviewOrchestrator:
    return InterviewOrchestrator(db, broadcaster=manager.broadcast)


# ---------------------------------------------------------------------------
# 出题流式（走真正的面试官 ReAct Agent）
# ---------------------------------------------------------------------------

_QUESTION_TYPES = {"technical", "behavioral", "project", "algorithm", "system_design"}
_TYPE_RE = re.compile(r"【题型】\s*(\w+)")


def _strip_header(buffer: str) -> str:
    """去掉首行【题型】标记行，返回题目正文。"""
    if "\n" in buffer:
        header, rest = buffer.split("\n", 1)
        if _TYPE_RE.match(header):
            return rest
    return buffer


@router.post("/start")
async def stream_start(data: dict, user: User = Depends(get_current_user)):
    # —— 参数校验（与 REST /start 共用 validate_start_params）——
    error, params = validate_start_params(data)
    if error:
        raise HTTPException(status_code=400, detail=error)

    async def event_gen() -> AsyncGenerator[str, None]:
        question_type = DEFAULT_QUESTION_TYPE
        question_text = ""
        try:
            async with AsyncSessionLocal() as db:
                orch = _orchestrator(db)
                # 解析简历上下文（与 REST /start 一致）
                resume = await orch.resolve_resume(user.id, params.resume_id)
                context = resume.content if resume and resume.content else ""

                interview = await orch.create_interview(
                    user_id=user.id,
                    resume_id=resume.id if resume else None,
                    interview_type=params.interview_type,
                    position_name=params.position_name,
                    difficulty_level=params.difficulty_level,
                    total_rounds=params.total_rounds,
                )
                interview_id = str(interview.id)

                yield _sse(
                    {
                        "type": "meta",
                        "interview_id": interview_id,
                        "current_round": 1,
                        "total_rounds": params.total_rounds,
                    }
                )
                await orch.notify_started(interview.id, 1)

                # 走真正的面试官 ReAct Agent（检索题库 + 查简历），逐 token 流式输出。
                # 入参与非流式路径同源（orch.interviewer_params），保证两条路径不漂移。
                buffer = ""
                sent = 0
                header_done = False

                async for tok in run_interviewer_agent_stream(
                    **orch.interviewer_params(interview, round_no=1, history=[], context=context)
                ):
                    buffer += tok
                    if not header_done:
                        if "\n" in buffer:
                            header, _ = buffer.split("\n", 1)
                            m = _TYPE_RE.match(header)
                            if m:
                                question_type = m.group(1)
                            header_done = True
                        elif len(buffer) > 200:
                            header_done = True  # 模型未遵守首行格式，整段视为题目正文
                    displayable = _strip_header(buffer) if header_done else ""
                    if len(displayable) > sent:
                        yield _sse({"type": "token", "text": displayable[sent:]})
                        sent = len(displayable)

                question_text = _strip_header(buffer).strip()
                if not question_text:
                    question_text = f"请介绍一下你自己，以及你应聘{params.position_name}的核心优势。"
                    question_type = DEFAULT_QUESTION_TYPE

                await orch.persist_question(
                    interview, QuestionOut(question=question_text, question_type=question_type), 1
                )
                await db.commit()

            yield _sse({"type": "done", "question": question_text, "question_type": question_type})
        except Exception as e:  # noqa: BLE001
            logger.error(f"流式出题失败: {e}")
            yield _sse({"type": "error", "message": "出题失败，请重试"})

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ---------------------------------------------------------------------------
# 评估流式（走真正的评估官 ReAct Agent）
# ---------------------------------------------------------------------------

_EVAL_FIELD_RE = re.compile(r"【(得分|优点|不足|建议|参考回答)】\s*(.*)")


def _strip_eval_markers(buffer: str) -> str:
    """去掉所有以【得分/优点/不足/建议/参考回答】开头的标记行，返回评估正文。"""
    out_lines = []
    for line in buffer.split("\n"):
        if _EVAL_FIELD_RE.match(line.strip()):
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _parse_eval_fields(buffer: str):
    """从完整 buffer 解析各标记行，返回 (score, strengths, weaknesses, suggestions, model_answer)。"""
    score = None
    strengths: list[str] = []
    weaknesses: list[str] = []
    suggestions: list[str] = []
    model_answer = ""
    for line in buffer.split("\n"):
        m = _EVAL_FIELD_RE.match(line.strip())
        if not m:
            continue
        field, value = m.group(1), m.group(2).strip()
        if field == "得分":
            try:
                score = float(value)
            except (TypeError, ValueError):
                score = None
        elif field == "优点":
            strengths = [x.strip() for x in re.split(r"[；;]", value) if x.strip()]
        elif field == "不足":
            weaknesses = [x.strip() for x in re.split(r"[；;]", value) if x.strip()]
        elif field == "建议":
            suggestions = [x.strip() for x in re.split(r"[；;]", value) if x.strip()]
        elif field == "参考回答":
            model_answer = value
    return score, strengths, weaknesses, suggestions, model_answer


@router.post("/answer")
async def stream_answer(data: dict, user: User = Depends(get_current_user)):
    interview_id = data.get("interview_id")
    answer = (data.get("answer") or "").strip()
    if not interview_id:
        raise HTTPException(status_code=400, detail="缺少 interview_id")
    if not answer:
        raise HTTPException(status_code=400, detail="回答不能为空")
    try:
        iid = uuid.UUID(str(interview_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 interview_id")

    async def event_gen() -> AsyncGenerator[str, None]:
        try:
            async with AsyncSessionLocal() as db:
                orch = _orchestrator(db)
                try:
                    pending = await orch.load_pending_turn(iid, user_id=user.id)
                except OrchestrationError as e:
                    yield _sse({"type": "error", "message": e.message})
                    return

                qa = pending.qa
                interview = pending.interview
                await orch.notify_evaluating(iid, pending.round_no)

                # 走真正的评估官 ReAct Agent（取 rubric + 可选验证代码），逐 token 流式输出评估
                buffer = ""
                sent = 0

                async def flush_tokens():
                    nonlocal buffer, sent
                    displayable = _strip_eval_markers(buffer)
                    if len(displayable) > sent:
                        chunk = displayable[sent:]
                        sent = len(displayable)
                        return chunk
                    return ""

                async for tok in run_evaluator_agent_stream(
                    qa.question_content or "", qa.question_type or DEFAULT_QUESTION_TYPE, answer
                ):
                    buffer += tok
                    chunk = await flush_tokens()
                    if chunk:
                        yield _sse({"type": "token", "text": chunk})

                # 完整后解析标记行得到结构化字段
                score, strengths, weaknesses, suggestions, model_answer = _parse_eval_fields(buffer)

                # 兜底：标记解析失败 → 用结构化输出重跑（不静默给默认值）
                if score is None:
                    try:
                        from app.agent.evaluator.graph import EvaluationOutput

                        sdata = await agenerate_structured(_eval_structured_prompt(qa, answer), EvaluationOutput)
                        if sdata:
                            score = sdata.get("score")
                            strengths = sdata.get("strengths") or []
                            weaknesses = sdata.get("weaknesses") or []
                            suggestions = sdata.get("suggestions") or []
                            model_answer = sdata.get("model_answer") or ""
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"评估兜底失败: {e}")

                # 解析与结构化兜底均失败：诚实地标记为「评分未完成」，绝不伪造 70 分污染数据
                evaluation = EvaluationOut(
                    score=score,
                    strengths=strengths,
                    weaknesses=weaknesses,
                    suggestions=suggestions,
                    model_answer=model_answer,
                    evaluation_failed=score is None,
                )

                # —— 以下为编排层职责：写库 + flush + 轮次推进 + 收尾 + 提交 + 缓存失效 ——
                await orch.record_evaluation(pending, answer, evaluation)
                outcome = await orch.advance(pending)
                await orch.commit(iid)

                completed = outcome.completed
                await orch.notify_evaluated(iid, pending.round_no, qa.score, completed)
                if completed:
                    await orch.notify_completed(iid)

                yield _sse(
                    {
                        "type": "done",
                        "score": evaluation.score,
                        "strengths": evaluation.strengths,
                        "weaknesses": evaluation.weaknesses,
                        "suggestions": evaluation.suggestions,
                        "model_answer": evaluation.model_answer,
                        "evaluation_failed": evaluation.evaluation_failed,
                        "completed": completed,
                        "current_round": interview.current_round,
                        "total_rounds": interview.total_rounds,
                        "next_question": outcome.next_question,
                    }
                )
        except Exception as e:  # noqa: BLE001
            logger.error(f"流式评估失败: {e}")
            yield _sse({"type": "error", "message": "评估失败，请重试"})

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


def _eval_structured_prompt(qa, answer: str) -> str:
    """标记解析失败时的结构化兜底 prompt（带 rubric 检索，保证评分有依据）。"""
    from app.rag.retrieval import retrieve_rubric_by_question

    rubric = ""
    try:
        rubric = retrieve_rubric_by_question(qa.question_content or "")
    except Exception:  # noqa: BLE001
        rubric = ""
    return (
        f"【问题】{qa.question_content}\n"
        f"【问题类型】{qa.question_type}\n"
        f"【候选人回答】{answer}\n"
        f"【评分依据】{rubric or '（无）'}\n"
        "请输出结构化评分（score 0-100，以及 strengths/weaknesses/suggestions/model_answer）。"
    )
