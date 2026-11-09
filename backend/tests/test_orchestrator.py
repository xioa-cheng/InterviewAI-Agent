r"""面试编排层（InterviewOrchestrator）集成测试。

跑法（在 backend 目录下）：
    python -m pytest -v

为什么用真实 SQLite + 假 Agent
------------------------------
编排层的价值在于「三入口共用同一份调度逻辑」，所以测试要真跑一遍
出题 → 作答 → 评分落库 → 轮次推进 → 收尾能力评估的完整链路：
- 数据库用**内存 SQLite**（真实 SQLAlchemy 模型，能抓到字段写错、外键、flush 语义问题）；
- 三个 Agent 全部替换为假实现（可断言入参契约、可控失败），不依赖 LLM / 向量库。

覆盖用例：
1. start 建面试并落首题；
2. 非末轮：评分落库 + 出下一题 + 推进轮次；
3. 末轮：收尾并跑能力评估（均分 + 7 维落库）；
4. 历史契约：只含已作答轮次，字段与 Agent 期望一致；
5. 评估失败：score 置 None 且不参与均分（不伪造分数）；
6. 分数越界被 clamp 到 0~100；
7. 流程校验异常：无效 ID / 不存在 / 越权 / 已作答 / 无待答题；
8. 提交后失效历史缓存（读到的必须是最新一轮）；
9. WebSocket 事件序列（evaluating → evaluated → completed）；
10. 契约本身：字段类型错误立即报错，杜绝「改字段名静默传 None」。
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app import models  # noqa: F401  注册全部模型
from app.models.interview import Interview, QAPair
from app.models.question_bank import SkillAssessment
from app.models.user import User
from app.orchestrator import service as service_mod
from app.orchestrator.contracts import EvaluationOut, QuestionOut, Turn
from app.orchestrator.errors import (
    AlreadyAnswered,
    InterviewNotFound,
    InvalidInterviewId,
    NoPendingQuestion,
    PermissionDenied,
)
from app.orchestrator.service import InterviewOrchestrator

SKILL_KEYS = [
    "technical_skill",
    "communication",
    "problem_solving",
    "leadership",
    "teamwork",
    "learning_ability",
    "stress_management",
]


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #
class FakeCache:
    """内存版 Redis：记录调用，用于断言缓存写入与失效。"""

    def __init__(self):
        self.store = {}
        self.deleted = []

    async def get_json(self, key):
        return self.store.get(key)

    async def set_json(self, key, value, ttl=None):
        self.store[key] = value

    async def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)


class FakeAgents:
    """三个 Agent 的假实现：记录入参、可控产出。"""

    def __init__(self, scores=None, fail_score_rounds=()):
        self.scores = scores or []
        self.fail_score_rounds = set(fail_score_rounds)
        self.interviewer_calls = []
        self.evaluator_calls = []
        self.skill_calls = []

    async def interviewer(self, params):
        self.interviewer_calls.append(params)
        return QuestionOut(
            question=f"第{params['current_round']}题", question_type="technical"
        )

    async def evaluator(self, question, question_type, answer):
        idx = len(self.evaluator_calls)
        self.evaluator_calls.append((question, question_type, answer))
        if idx in self.fail_score_rounds:
            return EvaluationOut(score=None, evaluation_failed=True)
        score = self.scores[idx] if idx < len(self.scores) else 80.0
        return EvaluationOut(
            score=score,
            strengths=["优点A"],
            weaknesses=["不足A"],
            suggestions=["建议A"],
            model_answer="参考回答",
        )

    async def skill(self, position, history):
        self.skill_calls.append((position, history))
        return {
            "scores": {k: 88.0 for k in SKILL_KEYS},
            "summary": "总体不错",
            "feedback": "建议多练系统设计",
        }


def _patch_cache(monkeypatch) -> FakeCache:
    fake = FakeCache()
    monkeypatch.setattr(service_mod, "cache", fake)
    return fake


async def _fresh_session():
    """每个用例一份干净的内存库 + 会话。"""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()
    return engine, session


async def _teardown(engine, session) -> None:
    """先关会话再释放引擎，避免 SQLAlchemy 报「连接未归还连接池」告警。"""
    await session.close()
    await engine.dispose()


async def _make_user(db: AsyncSession) -> User:
    user = User(
        username=f"u_{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@test.local",
        password_hash="x",
        full_name="测试用户",
        role="user",
    )
    db.add(user)
    await db.flush()
    return user


def _orch(db, agents, *, broadcaster=None):
    return InterviewOrchestrator(
        db,
        interview_agent=agents.interviewer,
        evaluator_agent=agents.evaluator,
        skill_agent=agents.skill,
        broadcaster=broadcaster,
        record_used=False,  # 题库使用频次走独立会话，测试中不启用
    )


# --------------------------------------------------------------------------- #
# 1. start 建面试并落首题
# --------------------------------------------------------------------------- #
def test_start_creates_interview_and_first_question(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        agents = FakeAgents()
        orch = _orch(db, agents)

        result = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端开发工程师",
            difficulty_level="medium",
            total_rounds=3,
            context="简历内容",
        )
        await db.commit()

        assert result.question.question == "第1题"
        assert result.question.question_type == "technical"
        assert result.interview.total_rounds == 3
        assert result.interview.status == "ongoing"

        qa = (
            await db.execute(select(QAPair).where(QAPair.interview_id == result.interview.id))
        ).scalars().all()
        assert len(qa) == 1
        assert qa[0].question_number == 1
        assert qa[0].question_content == "第1题"
        # 出题入参必须带齐契约字段（首轮 history 为空、带简历上下文）
        params = agents.interviewer_calls[0]
        assert params["history"] == []
        assert params["context"] == "简历内容"
        assert params["current_round"] == 1
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 2. 非末轮：评分落库 + 出下一题 + 推进轮次
# --------------------------------------------------------------------------- #
def test_answer_mid_round_advances_to_next_question(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        agents = FakeAgents(scores=[80.0])
        orch = _orch(db, agents)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端开发工程师",
            difficulty_level="medium",
            total_rounds=3,
        )
        iid = str(started.interview.id)

        result = await orch.answer_and_advance(iid, "我的回答", user_id=user.id)

        assert result.completed is False
        assert result.next_question == "第2题"
        assert result.current_round == 2
        assert result.evaluation.score == 80.0

        pairs = (
            await db.execute(
                select(QAPair).where(QAPair.interview_id == started.interview.id).order_by(QAPair.question_number)
            )
        ).scalars().all()
        assert len(pairs) == 2
        assert pairs[0].score == 80.0
        assert pairs[0].answer_content == "我的回答"
        assert pairs[0].strengths == ["优点A"]
        assert pairs[1].answer_content is None  # 新题尚未作答

        # 关键：追问时面试官必须拿到「已作答的上一轮」，否则会重复出题
        history_param = agents.interviewer_calls[-1]["history"]
        assert history_param == [
            {
                "round": 1,
                "question": "第1题",
                "answer": "我的回答",
                "question_type": "technical",
                "score": 80.0,
            }
        ]
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 3. 末轮：收尾 + 能力评估
# --------------------------------------------------------------------------- #
def test_last_round_completes_and_runs_skill_assessment(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        agents = FakeAgents(scores=[80.0, 90.0, 70.0])
        orch = _orch(db, agents)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端开发工程师",
            difficulty_level="medium",
            total_rounds=3,
        )
        iid = str(started.interview.id)

        r1 = await orch.answer_and_advance(iid, "答1", user_id=user.id)
        r2 = await orch.answer_and_advance(iid, "答2", user_id=user.id)
        r3 = await orch.answer_and_advance(iid, "答3", user_id=user.id)
        assert (r1.completed, r2.completed) == (False, False)
        assert r3.completed is True
        assert r3.next_question is None

        interview = (
            await db.execute(select(Interview).where(Interview.id == started.interview.id))
        ).scalar_one()
        assert interview.status == "completed"
        assert interview.ended_at is not None
        assert interview.overall_score == 80.0  # (80+90+70)/3
        assert interview.feedback_summary == "总体不错\n\n建议多练系统设计"

        skill = (
            await db.execute(select(SkillAssessment).where(SkillAssessment.interview_id == interview.id))
        ).scalar_one()
        assert skill.technical_skill == 88.0
        assert skill.stress_management == 88.0

        # 能力评估 Agent 必须拿到含分数的完整历史（否则 7 维画像没有依据）
        position, history = agents.skill_calls[0]
        assert position == "后端开发工程师"
        assert len(history) == 3
        assert [h["score"] for h in history] == [80.0, 90.0, 70.0]
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 4. 历史契约：只含已作答轮次，字段与 Agent 期望一致
# --------------------------------------------------------------------------- #
def test_history_contract_only_answered_turns(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        agents = FakeAgents(scores=[75.0])
        orch = _orch(db, agents)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端",
            difficulty_level="medium",
            total_rounds=3,
        )
        await orch.answer_and_advance(str(started.interview.id), "答1", user_id=user.id)

        history = await orch.load_history(started.interview.id, use_cache=False)
        assert len(history) == 1  # 第 2 题已生成但未作答，不应进历史
        turn = history[0]
        assert isinstance(turn, Turn)
        assert turn.round == 1
        assert turn.score == 75.0
        assert set(turn.to_agent_dict()) == {"round", "question", "answer", "question_type", "score"}
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 5. 评估失败：score=None，且不参与均分
# --------------------------------------------------------------------------- #
def test_evaluation_failure_keeps_score_none_and_excluded_from_average(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        # 第 1 轮评估失败（score=None），第 2 轮正常
        agents = FakeAgents(scores=[None, 100.0, 60.0], fail_score_rounds={0})
        orch = _orch(db, agents)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端",
            difficulty_level="medium",
            total_rounds=3,
        )
        iid = str(started.interview.id)

        r1 = await orch.answer_and_advance(iid, "答1", user_id=user.id)
        assert r1.evaluation.score is None
        assert r1.evaluation.evaluation_failed is True

        await orch.answer_and_advance(iid, "答2", user_id=user.id)
        await orch.answer_and_advance(iid, "答3", user_id=user.id)

        interview = (
            await db.execute(select(Interview).where(Interview.id == started.interview.id))
        ).scalar_one()
        # 失败轮不参与均分（也不会被当成 0 分）：(100+60)/2 = 80
        assert interview.overall_score == 80.0

        pairs = (
            await db.execute(
                select(QAPair).where(QAPair.interview_id == started.interview.id).order_by(QAPair.question_number)
            )
        ).scalars().all()
        assert pairs[0].score is None  # 诚实标注，绝不伪造分数
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 6. 分数越界被 clamp 到 0~100
# --------------------------------------------------------------------------- #
def test_score_is_clamped(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        agents = FakeAgents(scores=[150.0, -20.0])
        orch = _orch(db, agents)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端",
            difficulty_level="medium",
            total_rounds=2,
        )
        iid = str(started.interview.id)
        await orch.answer_and_advance(iid, "答1", user_id=user.id)
        await orch.answer_and_advance(iid, "答2", user_id=user.id)

        pairs = (
            await db.execute(
                select(QAPair).where(QAPair.interview_id == started.interview.id).order_by(QAPair.question_number)
            )
        ).scalars().all()
        assert pairs[0].score == 100.0
        assert pairs[1].score == 0.0
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 7. 流程校验异常（REST 转状态码、MCP 转 {"error"}，同一套语义）
# --------------------------------------------------------------------------- #
def test_pending_turn_validation_errors(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        other = await _make_user(db)
        agents = FakeAgents(scores=[80.0, 85.0])
        orch = _orch(db, agents)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端",
            difficulty_level="medium",
            total_rounds=2,
        )
        iid = str(started.interview.id)

        # 无效 ID
        with pytest.raises(InvalidInterviewId):
            await orch.load_pending_turn("not-a-uuid")
        # 不存在
        with pytest.raises(InterviewNotFound):
            await orch.load_pending_turn(str(uuid4()))
        # 越权（别人的面试）
        with pytest.raises(PermissionDenied):
            await orch.load_pending_turn(iid, user_id=other.id)
        # 已作答：答满全部轮次后，最后一轮已是「已作答」状态，再提交应被拒
        await orch.answer_and_advance(iid, "答1", user_id=user.id)
        await orch.answer_and_advance(iid, "答2", user_id=user.id)
        with pytest.raises(AlreadyAnswered):
            await orch.load_pending_turn(iid, user_id=user.id)

        # 没有待答题（面试存在但无任何 QAPair）
        empty = Interview(
            user_id=user.id,
            interview_type="technical",
            position_name="后端",
            difficulty_level="medium",
            total_rounds=2,
            current_round=1,
            status="ongoing",
        )
        db.add(empty)
        await db.flush()
        with pytest.raises(NoPendingQuestion):
            await orch.load_pending_turn(str(empty.id), user_id=user.id)

        # 异常自带 HTTP 语义，供 REST 直接转换
        assert InterviewNotFound().http_status == 404
        assert PermissionDenied().http_status == 403
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 8. 提交后失效历史缓存（否则下一轮读到的是上一轮的历史）
# --------------------------------------------------------------------------- #
def test_history_cache_invalidated_after_commit(monkeypatch):
    async def impl():
        fake_cache = _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        agents = FakeAgents(scores=[80.0, 90.0])
        orch = _orch(db, agents)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端",
            difficulty_level="medium",
            total_rounds=3,
        )
        iid = str(started.interview.id)

        await orch.load_history(started.interview.id)  # 写入缓存
        assert fake_cache.store  # 缓存已建立
        await orch.answer_and_advance(iid, "答1", user_id=user.id)

        key = f"interview:{started.interview.id}:history"
        assert key in fake_cache.deleted, fake_cache.deleted
        assert key not in fake_cache.store
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 9. WebSocket 事件序列
# --------------------------------------------------------------------------- #
def test_broadcast_event_sequence(monkeypatch):
    async def impl():
        _patch_cache(monkeypatch)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        events = []

        async def broadcaster(interview_id, message):
            events.append((interview_id, message))

        agents = FakeAgents(scores=[80.0, 90.0])
        orch = _orch(db, agents, broadcaster=broadcaster)
        started = await orch.start(
            user_id=user.id,
            interview_type="technical",
            position_name="后端",
            difficulty_level="medium",
            total_rounds=2,
            broadcast=True,
        )
        iid = str(started.interview.id)
        await orch.answer_and_advance(iid, "答1", user_id=user.id, broadcast=True)
        await orch.answer_and_advance(iid, "答2", user_id=user.id, broadcast=True)

        types = [(m["type"], m.get("round")) for _, m in events]
        assert types == [
            ("started", 1),
            ("evaluating", 1),
            ("evaluated", 1),
            ("evaluating", 2),
            ("evaluated", 2),
            ("completed", None),
        ]
        assert events[2][1]["completed"] is False
        assert events[4][1]["completed"] is True
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 10. 契约本身：字段类型错误立即报错（杜绝改字段名静默传 None）
# --------------------------------------------------------------------------- #
def test_turn_contract_rejects_bad_payload():
    turn = Turn(round=1, question="Q", score=80.0)
    assert turn.to_agent_dict()["score"] == 80.0

    with pytest.raises(ValidationError):
        Turn(round="one")  # round 必须是整数

    # 历史里混入缺字段的脏数据（模拟旧 dict 契约写错 key）应立刻暴露
    with pytest.raises(ValidationError):
        Turn(**{"round": 1, "question": "Q", "score": "not-a-number"})
