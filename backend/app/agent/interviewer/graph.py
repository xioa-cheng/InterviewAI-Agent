"""面试官 Agent（LangGraph）：根据岗位/简历/历史问答生成下一道面试题"""
import logging

from langgraph.graph import END, StateGraph

from app.agent.state import InterviewerState
from app.llm.client import agenerate_text
from app.rag.retrieval import retrieve_question_references
from app.utils import parse_json

logger = logging.getLogger(__name__)

QUESTION_PROMPT = """你是一位资深技术面试官，正在为「{position}」岗位进行{interview_type}面试（难度：{difficulty}）。
当前是第 {round} 轮（共 {total} 轮）。

{history}
{context}
{question_bank}

请只输出一个 JSON 对象（不要输出任何其它文字），格式如下：
{{"question": "你要问的面试问题", "question_type": "问题类型，取 technical / behavioral / project / algorithm / system_design 之一"}}

要求：问题具体、有区分度、贴合岗位；避免重复之前问过的问题。"""


def create_interviewer_graph():
    graph = StateGraph(InterviewerState)

    async def generate_question(state):
        position = state.get("position_name", "")
        interview_type = state.get("interview_type", "mixed")
        difficulty = state.get("difficulty_level", "medium")
        current_round = state.get("current_round", 1)
        total_rounds = state.get("total_rounds", 5)
        history = state.get("history", [])
        context = state.get("context", "")

        history_text = ""
        if history:
            lines = [
                f"第{q.get('round', '?')}轮 问题：{q.get('question', '')}\n回答：{q.get('answer', '')}"
                for q in history
            ]
            history_text = "之前的问答记录：\n" + "\n".join(lines) + "\n请基于以上内容追问或进入新话题。"

        context_text = f"候选人背景 / 简历参考：\n{context}" if context else ""

        # 语义检索与岗位/难度匹配的题库参考题（失败返回空，不影响出题）
        question_bank_text = ""
        try:
            question_bank_text = await retrieve_question_references(
                position_name=position,
                interview_type=interview_type,
                difficulty=difficulty,
                industry=state.get("industry", ""),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"题库检索异常: {e}")

        prompt = QUESTION_PROMPT.format(
            position=position,
            interview_type=interview_type,
            difficulty=difficulty,
            round=current_round,
            total=total_rounds,
            history=history_text,
            context=context_text,
            question_bank=question_bank_text,
        )

        try:
            content = await agenerate_text(prompt)
            data = parse_json(content)
            state["current_question"] = data.get("question") or f"请介绍一下你应聘{position}的核心优势。"
            state["question_type"] = data.get("question_type") or "behavioral"
        except Exception as e:  # noqa: BLE001
            logger.error(f"生成问题失败: {e}")
            state["current_question"] = f"请介绍一下你自己，以及你应聘{position}的核心优势。"
            state["question_type"] = "behavioral"
        return state

    async def check_complete(state):
        if state.get("current_round", 1) >= state.get("total_rounds", 5):
            state["interview_complete"] = True
        return state

    async def generate_response(state):
        if state.get("interview_complete"):
            state["response"] = "面试已结束，感谢你的参与！"
        else:
            state["response"] = state.get("current_question", "")
        return state

    graph.add_node("generate_question", generate_question)
    graph.add_node("check_complete", check_complete)
    graph.add_node("generate_response", generate_response)
    graph.set_entry_point("generate_question")
    graph.add_edge("generate_question", "check_complete")
    graph.add_edge("check_complete", "generate_response")
    graph.add_edge("generate_response", END)
    return graph.compile()


_interviewer = None


def get_interviewer_agent():
    global _interviewer
    if _interviewer is None:
        _interviewer = create_interviewer_graph()
    return _interviewer


async def run_interviewer_agent(**kwargs):
    agent = get_interviewer_agent()
    state = InterviewerState(
        interview_id=kwargs.get("interview_id", ""),
        user_id=kwargs.get("user_id", ""),
        interview_type=kwargs.get("interview_type", "mixed"),
        position_name=kwargs.get("position_name", ""),
        industry=kwargs.get("industry", ""),
        difficulty_level=kwargs.get("difficulty_level", "medium"),
        current_round=kwargs.get("current_round", 1),
        total_rounds=kwargs.get("total_rounds", 5),
        history=kwargs.get("history", []),
        context=kwargs.get("context", ""),
        interview_complete=False,
    )
    result = await agent.ainvoke(state)
    return result
