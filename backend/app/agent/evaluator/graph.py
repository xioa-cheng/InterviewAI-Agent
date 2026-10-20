"""评估官 Agent（LangGraph）：对候选人回答进行评分与点评"""
import logging

from langgraph.graph import END, StateGraph

from app.agent.state import EvaluatorState
from app.llm.client import agenerate_text
from app.utils import clamp_score, parse_json

logger = logging.getLogger(__name__)

EVALUATION_PROMPT = """你是一位专业的面试评估官。请对下面的面试问答进行评估。

【问题】{question}
【问题类型】{question_type}
【候选人回答】{answer}

请从内容质量、表达逻辑、技术深度、可改进空间等维度分析，并只输出一个 JSON 对象（不要输出其它文字）：
{{
  "score": 0到100的分数（0=完全错误，40=不及格，60=及格，80=良好，100=优秀）,
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1", "不足2"],
  "suggestions": ["改进建议1", "改进建议2"],
  "model_answer": "一段参考性的优秀回答（300字以内）"
}}"""


def create_evaluator_graph():
    graph = StateGraph(EvaluatorState)

    async def evaluate(state):
        question = state.get("question", "")
        question_type = state.get("question_type", "behavioral")
        answer = state.get("answer", "")
        prompt = EVALUATION_PROMPT.format(question=question, question_type=question_type, answer=answer)

        try:
            content = await agenerate_text(prompt)
            data = parse_json(content)
            state["score"] = clamp_score(data.get("score"), default=70.0)
            state["strengths"] = data.get("strengths") or []
            state["weaknesses"] = data.get("weaknesses") or []
            state["suggestions"] = data.get("suggestions") or []
            state["model_answer"] = data.get("model_answer") or ""
        except Exception as e:  # noqa: BLE001
            logger.error(f"评估失败: {e}")
            state["score"] = 70.0
            state["strengths"] = []
            state["weaknesses"] = []
            state["suggestions"] = []
            state["model_answer"] = ""
        return state

    graph.add_node("evaluate", evaluate)
    graph.set_entry_point("evaluate")
    graph.add_edge("evaluate", END)
    return graph.compile()


_evaluator = None


def get_evaluator_agent():
    global _evaluator
    if _evaluator is None:
        _evaluator = create_evaluator_graph()
    return _evaluator


async def run_evaluator_agent(question, question_type, answer):
    agent = get_evaluator_agent()
    state = EvaluatorState(question=question, question_type=question_type, answer=answer)
    result = await agent.ainvoke(state)
    return {
        "score": result.get("score"),
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
        "suggestions": result.get("suggestions", []),
        "model_answer": result.get("model_answer"),
    }
