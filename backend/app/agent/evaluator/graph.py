"""评估官 Agent：基于 ReAct 工具调用（获取 rubric + 验证代码）进行评分（接入题库 rubric）。

相比旧版「直接凭空评分」，本版让 LLM 自主决定：
1. 调用 get_rubric 获取该题的参考答案与评分要点（作为评分依据，稳定且可解释）；
2. 若回答含代码（algorithm / technical 类）且已开启代码执行，调用 run_python_code 验证正确性；
3. 最终用 EvaluationOutput 结构化抽取分数与点评。
可选接入外部 MCP 工具（见 app.mcp.client）。
"""
import logging
from typing import List

from pydantic import BaseModel, Field

from app.agent.tools.runner import run_react, run_react_stream
from app.agent.tools.rubric_tools import get_rubric
from app.agent.tools.code_tools import run_python_code
from app.mcp.client import load_external_mcp_tools
from app.config import settings
from app.llm.client import get_llm_client
from app.utils import clamp_score

logger = logging.getLogger(__name__)

_MAX_ITER = 3  # 评估官工具循环上限：通常取 rubric + 可选验证代码，防止工具循环失控拖慢评估

# 流式评估时追加到 human 的指令：让模型最终以五行标记格式输出，便于前端实时解析与打字机展示。
_EVAL_STREAM_SUFFIX = (
    "\n\n【输出格式】请严格按照以下五行标记格式输出，标记行之后不要额外说明：\n"
    "【得分】一个数字(0-100)\n"
    "【优点】分号分隔的若干条优点\n"
    "【不足】分号分隔的若干条不足\n"
    "【建议】分号分隔的若干条建议\n"
    "【参考回答】一段参考性的优秀回答（300字以内）"
)


class EvaluationOutput(BaseModel):
    score: float = Field(
        ..., description="0到100的分数（0=完全错误，40=不及格，60=及格，80=良好，100=优秀）"
    )
    strengths: List[str] = Field(default_factory=list, description="候选人的优点列表")
    weaknesses: List[str] = Field(default_factory=list, description="候选人的不足列表")
    suggestions: List[str] = Field(default_factory=list, description="改进建议列表")
    model_answer: str = Field(default="", description="一段参考性的优秀回答（300字以内）")


EVALUATOR_SYSTEM = """你是一位专业的面试评估官。请通过工具完成评分：
1. 调用 get_rubric 获取该问题的参考答案与评分要点（务必调用，作为客观评分依据）；
2. 若候选人的回答包含代码（如 algorithm / technical 类型），可调用 run_python_code 验证其正确性；
3. 结合 rubric 与验证结果，给出客观、可解释的分数与点评。
你只需要调用工具并给出简短推理；最终的结构化评分由后续步骤抽取，无需在此输出 JSON。"""


async def run_evaluator_agent(question, question_type, answer):
    human = (
        f"【问题】{question}\n"
        f"【问题类型】{question_type}\n"
        f"【候选人回答】{answer}\n"
        f"请先调用 get_rubric 获取评分依据，再给出结构化评分。"
    )

    tools = [get_rubric]
    if settings.ENABLE_CODE_TOOLS:
        tools.append(run_python_code)
    ext = await load_external_mcp_tools()
    if ext:
        tools = tools + ext

    try:
        data = await run_react(get_llm_client(), tools, EVALUATOR_SYSTEM, human, EvaluationOutput, max_iterations=_MAX_ITER)
        if not data:
            raise ValueError("结构化输出为空")
        return {
            "score": clamp_score(data.get("score")),
            "strengths": data.get("strengths") or [],
            "weaknesses": data.get("weaknesses") or [],
            "suggestions": data.get("suggestions") or [],
            "model_answer": data.get("model_answer") or "",
            "evaluation_failed": False,
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"评估失败: {e}")
        # 诚实地标记评分未完成：score 为 None，绝不伪造 70 分污染报告与总分
        return {
            "score": None,
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
            "model_answer": "",
            "evaluation_failed": True,
        }


async def run_evaluator_agent_stream(question, question_type, answer):
    """流式版评估官：与 run_evaluator_agent 共用工具与推理（get_rubric + 可选 run_python_code），
    但逐 token 输出最终评估文本（含五行标记），供前端做打字机与实时解析。

    前端解析标记得到结构化字段；解析失败时回退到结构化输出（run_evaluator_agent 同款），
    不会再出现「静默给 70 分」污染数据的问题。
    """
    human = (
        f"【问题】{question}\n"
        f"【问题类型】{question_type}\n"
        f"【候选人回答】{answer}\n"
        f"请先调用 get_rubric 获取评分依据，再给出结构化评分。"
    ) + _EVAL_STREAM_SUFFIX

    tools = [get_rubric]
    if settings.ENABLE_CODE_TOOLS:
        tools.append(run_python_code)
    ext = await load_external_mcp_tools()
    if ext:
        tools = tools + ext

    async for tok in run_react_stream(get_llm_client(), tools, EVALUATOR_SYSTEM, human, max_iterations=_MAX_ITER):
        yield tok
