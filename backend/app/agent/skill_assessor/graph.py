"""能力评估 Agent（LangGraph）：对整场面试做多维度能力评分 + 总结"""
import logging

from langchain_core.output_parsers import JsonOutputParser
from langgraph.graph import END, StateGraph

from app.agent.state import SkillAssessorState
from app.llm.client import agenerate_text
from app.utils import clamp_score

logger = logging.getLogger(__name__)

_json_parser = JsonOutputParser()

SKILL_PROMPT = """你是一位资深的面试评估专家。以下是候选人在「{position}」岗位面试中的完整问答记录与逐题得分：

{history}

请综合评估候选人的能力。打分采用 0 到 100 分制（60 分为及格线，80 分以上为优秀）。只输出一个 JSON 对象（不要输出其它文字）：
{{
  "scores": {{
    "technical_skill": 0到100的技术能力得分,
    "communication": 0到100的沟通表达得分,
    "problem_solving": 0到100的问题解决得分,
    "leadership": 0到100的领导力得分,
    "teamwork": 0到100的团队协作得分,
    "learning_ability": 0到100的学习能力得分,
    "stress_management": 0到100的抗压能力得分
  }},
  "summary": "一段整体评价（100字以内）",
  "feedback": "一段改进建议（150字以内）"
}}"""

SKILL_KEYS = [
    "technical_skill",
    "communication",
    "problem_solving",
    "leadership",
    "teamwork",
    "learning_ability",
    "stress_management",
]


def create_skill_assessor_graph():
    graph = StateGraph(SkillAssessorState)

    async def assess(state):
        position = state.get("position_name", "")
        history = state.get("history", [])
        lines = []
        for h in history:
            lines.append(
                f"第{h.get('round', '?')}轮（{h.get('question_type', '')}）：问题：{h.get('question', '')}"
                f"；回答：{h.get('answer', '')}；得分：{h.get('score', '-')}"
            )
        history_text = "\n".join(lines) if lines else "（无记录）"
        prompt = SKILL_PROMPT.format(position=position, history=history_text)

        try:
            content = await agenerate_text(prompt)
            data = _json_parser.parse(content)
            raw_scores = data.get("scores") or {}
            state["scores"] = {k: clamp_score(raw_scores.get(k), 60.0) for k in SKILL_KEYS}
            state["summary"] = data.get("summary") or ""
            state["feedback"] = data.get("feedback") or ""
        except Exception as e:  # noqa: BLE001
            logger.error(f"能力评估失败: {e}")
            state["scores"] = {k: 60.0 for k in SKILL_KEYS}
            state["summary"] = ""
            state["feedback"] = ""
        return state

    graph.add_node("assess", assess)
    graph.set_entry_point("assess")
    graph.add_edge("assess", END)
    return graph.compile()


_assessor = None


def get_skill_assessor_agent():
    global _assessor
    if _assessor is None:
        _assessor = create_skill_assessor_graph()
    return _assessor


async def run_skill_assessor(position_name, history):
    agent = get_skill_assessor_agent()
    state = SkillAssessorState(position_name=position_name, history=history)
    result = await agent.ainvoke(state)
    return result
