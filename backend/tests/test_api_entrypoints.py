r"""接口层验证：REST / MCP 两个入口是否真的共用同一套编排。

跑法（在 backend 目录下）：
    python -m pytest -v

这一层验证的是「重构目标是否达成」：
- REST 端点（app/api/interview.py）与 MCP 工具（app/mcp/server.py）走同一份编排逻辑；
- 编排异常能被正确翻译成各自协议的语义（REST → HTTP 状态码，MCP → {"error": ...}）；
- 接口层不再残留任何编排代码（防回归）。

三个 Agent 全部替换为假实现，数据库用内存 SQLite。
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import interview as interview_api
from app.mcp import server as mcp_server
from app.orchestrator import service as service_mod

from test_orchestrator import (  # 复用同一套测试基建
    FakeAgents,
    FakeCache,
    _fresh_session,
    _make_user,
    _teardown,
)


def _patch(monkeypatch, agents: FakeAgents) -> FakeCache:
    """把编排层的默认 Agent 换成假实现，并接管缓存 / 题库副作用。"""
    monkeypatch.setattr(service_mod, "_default_interviewer", agents.interviewer)
    monkeypatch.setattr(service_mod, "_default_evaluator", agents.evaluator)
    monkeypatch.setattr(service_mod, "_default_skill_assessor", agents.skill)
    fake_cache = FakeCache()
    monkeypatch.setattr(service_mod, "cache", fake_cache)

    # 屏蔽「累计题库使用频次」：它会另开会话连真实开发库，测试中不需要且不卫生
    async def _noop_record_question_used(self, question: str) -> None:
        return None

    monkeypatch.setattr(
        service_mod.InterviewOrchestrator, "_record_question_used", _noop_record_question_used
    )
    return fake_cache


# --------------------------------------------------------------------------- #
# 1. REST 全流程：开面 → 作答 → 收尾 → 报告
# --------------------------------------------------------------------------- #
def test_rest_full_flow(monkeypatch):
    async def impl():
        agents = FakeAgents(scores=[80.0, 90.0])
        _patch(monkeypatch, agents)
        engine, db = await _fresh_session()
        user = await _make_user(db)

        started = await interview_api.start_interview(
            {"position_name": "后端开发工程师", "total_rounds": 2, "interview_type": "technical"}, user, db
        )
        iid = started["interview_id"]
        assert started["question"] == "第1题"
        assert started["question_type"] == "technical"
        assert started["total_rounds"] == 2

        r1 = await interview_api.submit_answer(iid, {"answer": "答1"}, user, db)
        assert r1["completed"] is False
        assert r1["next_question"] == "第2题"
        assert r1["evaluation"]["score"] == 80.0
        assert r1["evaluation"]["strengths"] == ["优点A"]

        r2 = await interview_api.submit_answer(iid, {"answer": "答2"}, user, db)
        assert r2["completed"] is True
        assert r2["next_question"] is None

        report = await interview_api.get_report(iid, user, db)
        assert report["status"] == "completed"
        assert report["overall_score"] == 85.0  # (80+90)/2
        assert len(report["details"]) == 2
        assert [d["score"] for d in report["details"]] == [80.0, 90.0]
        assert report["skill_scores"]["technical_skill"] == 88.0
        assert report["feedback_summary"] == "总体不错\n\n建议多练系统设计"
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 2. REST 错误映射：编排异常 → HTTP 状态码
# --------------------------------------------------------------------------- #
def test_rest_error_mapping(monkeypatch):
    async def impl():
        agents = FakeAgents(scores=[80.0, 90.0])
        _patch(monkeypatch, agents)
        engine, db = await _fresh_session()
        user = await _make_user(db)
        other = await _make_user(db)

        async def status_of(coro):
            with pytest.raises(HTTPException) as exc:
                await coro
            return exc.value.status_code, exc.value.detail

        assert await status_of(interview_api.submit_answer("bad-id", {"answer": "x"}, user, db)) == (
            400,
            "无效的 interview_id",
        )
        assert await status_of(interview_api.submit_answer(str(uuid4()), {"answer": "x"}, user, db)) == (
            404,
            "面试不存在",
        )

        started = await interview_api.start_interview(
            {"position_name": "后端", "total_rounds": 1}, user, db
        )
        iid = started["interview_id"]
        # 越权
        assert await status_of(interview_api.submit_answer(iid, {"answer": "x"}, other, db)) == (
            403,
            "无权访问该面试",
        )
        # 已作答（total_rounds=1，答完即收尾，再提交应被拒）
        await interview_api.submit_answer(iid, {"answer": "答1"}, user, db)
        assert await status_of(interview_api.submit_answer(iid, {"answer": "x"}, user, db)) == (
            400,
            "当前问题已作答",
        )

        # /start 入参校验
        code, detail = await status_of(
            interview_api.start_interview({"interview_type": "不存在的类型"}, user, db)
        )
        assert (code, detail) == (400, "无效的面试类型")
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 3. MCP 全流程：与 REST 共用同一套编排（此处不再复制一遍调度逻辑）
# --------------------------------------------------------------------------- #
def test_mcp_full_flow(monkeypatch):
    async def impl():
        agents = FakeAgents(scores=[70.0, 95.0])
        _patch(monkeypatch, agents)
        engine, db = await _fresh_session()
        # MCP 入口自带会话工厂：把它指向测试用的内存库
        monkeypatch.setattr(
            mcp_server,
            "AsyncSessionLocal",
            async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        )

        started = await mcp_server.start_interview(position_name="后端开发工程师", total_rounds=2)
        iid = started["interview_id"]
        assert started["question"] == "第1题"

        r1 = await mcp_server.submit_interview_answer(iid, "答1")
        assert r1["completed"] is False
        assert r1["next_question"] == "第2题"
        assert r1["evaluation"]["score"] == 70.0

        r2 = await mcp_server.submit_interview_answer(iid, "答2")
        assert r2["completed"] is True

        report = await mcp_server.get_interview_report(iid)
        assert report["status"] == "completed"
        assert report["overall_score"] == 82.5  # (70+95)/2
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 4. MCP 错误映射：编排异常 → {"error": ...}
# --------------------------------------------------------------------------- #
def test_mcp_error_mapping(monkeypatch):
    async def impl():
        agents = FakeAgents(scores=[80.0])
        _patch(monkeypatch, agents)
        engine, db = await _fresh_session()
        monkeypatch.setattr(
            mcp_server,
            "AsyncSessionLocal",
            async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        )

        assert await mcp_server.submit_interview_answer("bad-id", "x") == {"error": "无效的 interview_id"}
        assert await mcp_server.submit_interview_answer(str(uuid4()), "x") == {"error": "面试不存在"}
        assert await mcp_server.get_interview_report("bad-id") == {"error": "无效的 interview_id"}
        await _teardown(engine, db)

    asyncio.run(impl())


# --------------------------------------------------------------------------- #
# 5. 防回归：接口层不得再出现编排代码（编排只存在一份）
# --------------------------------------------------------------------------- #
def test_no_orchestration_left_in_entrypoints():
    forbidden = [
        "_update_overall",
        "_run_skill_assessment",
        'interview.status = "completed"',
        "SkillAssessment(",
        "qa.question_number >= interview.total_rounds",
        "interview.current_round = qa.question_number",
    ]
    for rel in ["app/api/interview.py", "app/api/stream.py", "app/mcp/server.py"]:
        src = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in src, f"{rel} 仍残留编排逻辑：{marker}"
