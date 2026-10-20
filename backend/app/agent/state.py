"""Agent 状态定义（LangGraph TypedDict）"""
from typing import List, Optional, TypedDict


class InterviewerState(TypedDict, total=False):
    interview_id: str
    user_id: str
    interview_type: str
    position_name: str
    industry: str
    difficulty_level: str
    current_round: int
    total_rounds: int
    history: List[dict]
    context: str
    current_question: Optional[str]
    question_type: Optional[str]
    interview_complete: bool
    response: Optional[str]


class EvaluatorState(TypedDict, total=False):
    question: str
    question_type: str
    answer: str
    score: Optional[float]
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    model_answer: Optional[str]


class SkillAssessorState(TypedDict, total=False):
    interview_id: str
    position_name: str
    history: List[dict]
    scores: dict
    summary: str
    feedback: str
