r"""LLM 超时与降级链路的单元测试（不依赖真实 API key / 数据库 / 向量库）。

跑法（在 backend 目录下）：
    python -m pytest -v

覆盖 6 个用例：
1. ChatOpenAI 构造确实带 timeout / max_retries；
2. 单次调用超时后重试成功；
3. 重试耗尽后异常上抛（交由 agent 兜底）；
4. run_react 工具循环超时后重试仍能出题；
5. run_react 全部超时：异常传播（调用方兜底的前提）；
6. 结构化抽取超时：诚实返回 None，不编造分数。

说明：runner.py 用 importlib 直接按文件加载，是为了绕开
app.agent.tools.__init__ 间接引入的 sqlalchemy / chromadb 等重依赖——
本用例只 mock LLM，不需要真实 DB。若已安装完整依赖，可改为
`from app.agent.tools.runner import run_react`。
"""
import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import openai
from langchain_core.messages import AIMessage

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.llm.client as client_mod
from app.llm.client import _ainvoke_with_timeout_retry, get_llm_client


def _load_runner():
    """按文件路径加载 runner.py，避免触发 app.agent.tools.__init__ 的重依赖。"""
    spec = importlib.util.spec_from_file_location(
        "app.agent.tools.runner",
        BACKEND_ROOT / "app" / "agent" / "tools" / "runner.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner_mod = _load_runner()


# ---------- 1. ChatOpenAI 构造确实带 timeout / max_retries ----------
def test_get_llm_client_passes_timeout_and_max_retries(monkeypatch):
    captured = {}

    def fake_chatopenai(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(client_mod, "ChatOpenAI", fake_chatopenai)
    client_mod._llm = None  # 清单例缓存，强制重新构造
    get_llm_client()
    assert "timeout" in captured, captured
    assert "max_retries" in captured, captured
    assert captured["timeout"] == client_mod.settings.LLM_TIMEOUT
    assert captured["max_retries"] == client_mod.settings.LLM_MAX_RETRIES


# ---------- 辅助：会按次数抛 APITimeoutError 的伪 LLM ----------
class FakeBound:
    def __init__(self, fail_times):
        self.calls = 0
        self.fail_times = fail_times

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise openai.APITimeoutError("timed out")
        return AIMessage(content=f"ok after {self.calls}")


# ---------- 2. 单次调用：超时后第 2 次成功 ----------
def test_retry_succeeds_after_transient_timeout():
    async def impl():
        # retries=1 -> attempts = 2
        bound = FakeBound(fail_times=1)
        res = await _ainvoke_with_timeout_retry(bound, ["msg"], retries=1)
        assert bound.calls == 2
        assert "ok after 2" in res.content

    asyncio.run(impl())


# ---------- 3. 重试耗尽：异常上抛（由 agent 兜底接住） ----------
def test_retry_exhausted_raises():
    async def impl():
        bound = FakeBound(fail_times=99)
        try:
            await _ainvoke_with_timeout_retry(bound, ["msg"], retries=1)
            raise AssertionError("should have raised")
        except openai.APITimeoutError:
            assert bound.calls == 2  # attempts = retries + 1 = 2

    asyncio.run(impl())


# ---------- 4. run_react 工具循环：超时后重试仍能出题 ----------
class FakeModel:
    def __init__(self, fail_times=1):
        self.calls = 0
        self.fail_times = fail_times

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise openai.APITimeoutError("timeout")
        return AIMessage(content="generated question")

    def with_structured_output(self, schema, method=None):
        return FakeStructured(self.fail_times)


class FakeStructured:
    def __init__(self, fail_times):
        self.calls = 0
        self.fail_times = fail_times

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise openai.APITimeoutError("timeout")
        obj = MagicMock()
        obj.model_dump.return_value = {"score": 80}
        return obj


def test_run_react_retries_then_returns():
    async def impl():
        model = FakeModel(fail_times=1)
        out = await runner_mod.run_react(
            model=model, tools=[], system="s", human="h", max_iterations=3
        )
        assert out == "generated question"
        assert model.calls == 2  # 第一次超时，重试第二次成功

    asyncio.run(impl())


# ---------- 5. run_react 全超时：异常传播（调用方兜底前提） ----------
def test_run_react_all_timeouts_propagates():
    async def impl():
        model = FakeModel(fail_times=99)
        try:
            await runner_mod.run_react(
                model=model, tools=[], system="s", human="h", max_iterations=3
            )
            raise AssertionError("should raise")
        except openai.APITimeoutError:
            pass

    asyncio.run(impl())


# ---------- 6. 结构化抽取超时：诚实返回 None（不编造分数） ----------
def test_agenerate_structured_timeout_fallback_none(monkeypatch):
    async def impl():
        fake = FakeModel(fail_times=99)  # 始终超时
        monkeypatch.setattr(client_mod, "get_llm_client", lambda: fake)
        result = await client_mod.agenerate_structured("prompt", MagicMock())
        assert result is None  # 诚实兜底，不污染成默认分

    asyncio.run(impl())
