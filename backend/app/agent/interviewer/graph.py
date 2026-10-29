"""面试官 Agent：基于 ReAct 工具调用（检索题库 + 查阅简历）生成下一道面试题。

相比旧版「单次 structured 调用」，本版让 LLM 自主决定：
1. 调用 search_questions 检索相关题库参考题（hybrid_retrieve）；
2. 调用 lookup_resume 查阅候选人简历（若有背景可贴合）；
3. 最终再用 QuestionOutput 结构化抽取「题目 + 题型」，延续既有评分契约。
可选接入外部 MCP 工具（见 app.mcp.client）。
"""
import logging
from typing import List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools.runner import run_react, run_react_stream
from app.agent.tools.question_tools import search_questions
from app.agent.tools.resume_tools import lookup_resume
from app.mcp.client import load_external_mcp_tools
from app.llm.client import get_llm_client
from app.rag.retrieval import _jaccard, _tokenize, hybrid_retrieve, _is_similar

logger = logging.getLogger(__name__)

_QUESTION_TYPES = {"technical", "behavioral", "project", "algorithm", "system_design"}
_MAX_ITER = 3  # ReAct 工具循环上限：面试官通常 1 次检索即可，防止模型反复调用工具拖慢出题

# 流式出题时追加到 human 的指令：让模型最后直接以「【题型】xxx 换行 题目」形式输出，
# 便于前端实时解析题型并做打字机展示（与 REST 版共用同一套工具与推理）。
_INTERVIEWER_STREAM_SUFFIX = (
    "\n\n请直接输出面试题：先用一行写 `【题型】technical`（从 "
    "technical/behavioral/project/algorithm/system_design 中选最贴切的一个），"
    "然后另起一行开始写面试题本身。题目要具体、有区分度、贴合岗位，避免重复之前问过的问题。"
)


def _asked_questions(history) -> List[str]:
    """从本轮历史中抽出已经问过的问题文本，用于检索排除，避免重复出题。"""
    out = []
    for q in history or []:
        t = (q.get("question") or "").strip()
        if t:
            out.append(t)
    return out


def _make_scoped_search_tool(exclude_questions: List[str]):
    """构造一个「已自动排除本场已问题目」的检索工具，交给 ReAct 循环使用。

    原 search_questions 的 exclude 参数从不被模型主动传入，导致每轮都召回同一批参考题、
    进而反复挑同一题。这里把 exclude 固化进工具，从根本上杜绝重复召回。
    """
    ex = [q for q in (exclude_questions or []) if q]

    @tool
    async def search_questions_scoped(need: str, position: str = "", difficulty: str = "medium") -> str:
        """在面试题库中检索与面试需求相关的参考题目（已自动排除本场面试已问过的题目）。

        Args:
            need: 想要考察的能力或主题描述，例如 "Redis 缓存击穿与解决方案"、"分布式事务一致性"。
            position: 应聘岗位名，例如 "后端开发工程师"；用于元数据软过滤与术语命中。
            difficulty: 期望难度，取值 easy / medium / hard。
        """
        return await search_questions.ainvoke(
            {"need": need, "position": position, "difficulty": difficulty, "exclude": ex}
        )

    return search_questions_scoped


def _is_duplicate(new_q: str, asked: List[str], threshold: float = 0.6) -> bool:
    """基于 Jaccard 相似度判断新题是否与已问题高度重复。"""
    if not new_q or not asked:
        return False
    a = set(_tokenize(new_q))
    return any(_jaccard(a, set(_tokenize(old))) > threshold for old in asked)


class QuestionOutput(BaseModel):
    question: str = Field(..., description="你要问的面试问题，需具体、有区分度、贴合岗位")
    question_type: str = Field(
        ..., description="问题类型，取 technical / behavioral / project / algorithm / system_design 之一"
    )


INTERVIEWER_SYSTEM = """你是一位资深技术面试官。请通过调用工具完成出题任务：
1. 调用 search_questions 检索与岗位 / 主题相关的题库参考题（务必调用，避免凭空出题）；
2. 若该候选人有简历背景且需要贴合，调用 lookup_resume 查阅其简历；
3. 综合检索结果与历史问答，构思一道具体、有区分度、不重复的面试题。
你只需要调用工具并给出简短推理；最终的结构化问题由后续步骤抽取，无需在此输出 JSON。"""


def _format_history(history) -> str:
    if not history:
        return ""
    lines = [
        f"第{q.get('round', '?')}轮 问题：{q.get('question', '')}\n回答：{q.get('answer', '')}"
        for q in history
    ]
    return "之前的问答记录：\n" + "\n".join(lines) + "\n请基于以上内容追问或进入新话题，不要重复已经问过的问题。"


async def run_interviewer_agent(**kwargs):
    position = kwargs.get("position_name", "")
    interview_type = kwargs.get("interview_type", "mixed")
    difficulty = kwargs.get("difficulty_level", "medium")
    current_round = kwargs.get("current_round", 1)
    total_rounds = kwargs.get("total_rounds", 5)
    history = kwargs.get("history", []) or []
    context = kwargs.get("context", "") or ""
    user_id = kwargs.get("user_id", "")

    history_text = _format_history(history)
    ctx_text = f"候选人背景：{context}" if context else ""
    human = (
        f"请为「{position}」岗位进行{interview_type}面试（难度：{difficulty}），这是第 {current_round}/{total_rounds} 轮。\n"
        f"{history_text}\n{ctx_text}\n"
        f"候选人 user_id={user_id}（如需贴合背景可调用 lookup_resume）。\n"
        f"请调用 search_questions 检索参考题，并构思下一道面试题。"
    )

    asked = _asked_questions(history)

    # 从题库确定性地挑出「与历史不相似」的候选参考题，用于强制轮换出题主题，
    # 从根本上避免 LLM 反复挑选/复述同一道题（之前的"求 LLM 自觉换题"几乎无效）。
    candidate_pairs: List[tuple] = []
    try:
        candidates = await hybrid_retrieve(
            position_name=position,
            interview_type=interview_type,
            difficulty=difficulty,
            k=8,
            context=context,
            exclude_questions=asked,
        )
        candidate_pairs = [
            (c.get("question_content", ""), c.get("question_type") or "technical")
            for c in candidates
            if c.get("question_content")
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"题库候选检索失败（将自由出题）: {e}")

    tools = [_make_scoped_search_tool(asked), lookup_resume]
    ext = await load_external_mcp_tools()
    if ext:
        tools = tools + ext

    question = None
    qtype = "behavioral"
    # 每轮强制基于一个不同的题库候选改编；该候选与历史不相似，天然保证换题。
    attempts = max(1, min(3, len(candidate_pairs) + 1))
    for attempt in range(attempts):
        seed, seed_type = candidate_pairs[attempt] if attempt < len(candidate_pairs) else ("", "behavioral")
        extra = ""
        if seed:
            extra = (
                f"\n\n【强制要求】你必须基于下面这道题库参考题来改编本场面试的下一题"
                f"（可结合候选人背景改写措辞，但考察主题必须不同、且不得与历史问题重复）：\n"
                f"参考题：{seed}"
            )
        try:
            data = await run_react(
                get_llm_client(), tools, INTERVIEWER_SYSTEM,
                human + extra, QuestionOutput, max_iterations=_MAX_ITER,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"生成问题失败(attempt {attempt}): {e}")
            data = None
        if not data:
            continue
        q = (data.get("question") or "").strip()
        qt = (data.get("question_type") or seed_type or "behavioral").strip()
        if not q:
            continue
        if qt not in _QUESTION_TYPES:
            qt = "behavioral"
        # 语义/字面去重：与历史任一题高度相似则换下一个候选重试
        if asked and await _is_similar(q, asked):
            logger.info(f"出题与历史重复(attempt {attempt})，换题重试")
            continue
        question, qtype = q, qt
        break

    # 兜底：多次尝试仍重复/失败，直接取一个确定「不相似」的题库题（保证不重复）；
    # 若题库也无可用题，再用安全兜底题。
    if not question:
        for c, ct in candidate_pairs:
            if not await _is_similar(c, asked):
                question, qtype = c, ct if ct in _QUESTION_TYPES else "behavioral"
                break
    if not question:
        question = (
            f"请结合你最近的项目经历，谈谈你在{position}岗位上遇到的最大技术挑战，"
            f"以及你是如何分析并解决它的。"
        )
        qtype = "behavioral"

    return {"current_question": question, "question_type": qtype}


async def run_interviewer_agent_stream(**kwargs):
    """流式版面试官：与 run_interviewer_agent 共用工具与推理，但逐 token 输出最终题目文本。

    调用方负责从流中解析首行 `【题型】` 标记得到题型、并以打字机形式展示题目正文。
    这样前端 SSE 路径也真正走「检索题库 + 查简历」的 ReAct 面试官，而非另一套手写 prompt。
    """
    position = kwargs.get("position_name", "")
    interview_type = kwargs.get("interview_type", "mixed")
    difficulty = kwargs.get("difficulty_level", "medium")
    current_round = kwargs.get("current_round", 1)
    total_rounds = kwargs.get("total_rounds", 5)
    history = kwargs.get("history", []) or []
    context = kwargs.get("context", "") or ""
    user_id = kwargs.get("user_id", "")

    history_text = _format_history(history)
    ctx_text = f"候选人背景：{context}" if context else ""
    human = (
        f"请为「{position}」岗位进行{interview_type}面试（难度：{difficulty}），这是第 {current_round}/{total_rounds} 轮。\n"
        f"{history_text}\n{ctx_text}\n"
        f"候选人 user_id={user_id}（如需贴合背景可调用 lookup_resume）。\n"
        f"请调用 search_questions 检索参考题，并构思下一道面试题。"
    ) + _INTERVIEWER_STREAM_SUFFIX

    asked = _asked_questions(history)
    tools = [_make_scoped_search_tool(asked), lookup_resume]
    ext = await load_external_mcp_tools()
    if ext:
        tools = tools + ext

    async for tok in run_react_stream(get_llm_client(), tools, INTERVIEWER_SYSTEM, human, max_iterations=_MAX_ITER):
        yield tok
