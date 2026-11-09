"""三个 Agent 之间的结构化消息契约。

设计动机
--------
重构前 Agent 之间传的是「裸 dict」（``{"round":..., "question":..., "answer":...}``），
字段名靠口头约定：任一侧改名，另一侧会静默拿到 None 而不报错。

这里把跨 Agent 传递的每一份数据都用 Pydantic 建模：
- ``Turn``          —— 一轮问答（面试官产出题目 → 评估官回填评分 → 能力评估汇总读取）
- ``InterviewContext`` —— 一次调用喂给 Agent 的完整上下文
- ``QuestionOut`` / ``EvaluationOut`` —— Agent 的产出

好处：字段缺失/类型错误在契约层立即报错；``to_agent_dict()`` 统一负责
「契约 → Agent 期望的 dict」，Agent 侧不需要知道契约的存在。

本模块**不导入任何 SQLAlchemy / 框架依赖**，可独立测试。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# 面试官可以产出的题型（超出范围一律收敛为 behavioral，避免脏数据落库）
QUESTION_TYPES = {"technical", "behavioral", "project", "algorithm", "system_design"}
DEFAULT_QUESTION_TYPE = "behavioral"

# /start 入参白名单（REST 与 SSE 共用，避免两处校验规则漂移）
ALLOWED_INTERVIEW_TYPES = {
    "mixed",
    "technical",
    "behavioral",
    "project",
    "algorithm",
    "system_design",
    "stress",
}
ALLOWED_DIFFICULTY = {"easy", "medium", "hard"}


class StartParams(BaseModel):
    """新建面试的规范化入参。"""

    interview_type: str = "mixed"
    position_name: str = "后端开发工程师"
    difficulty_level: str = "medium"
    total_rounds: int = 5
    resume_id: Optional[str] = None


def validate_start_params(data: dict) -> "tuple[Optional[str], Optional[StartParams]]":
    """校验 /start 入参，返回 ``(错误提示, 规范化参数)``；错误提示为 None 表示通过。

    错误文案保持与重构前一致，前端无需改动。
    """
    data = data or {}
    interview_type = data.get("interview_type", "mixed")
    position_name = data.get("position_name") or "后端开发工程师"
    difficulty_level = data.get("difficulty_level", "medium")
    if interview_type not in ALLOWED_INTERVIEW_TYPES:
        return "无效的面试类型", None
    if difficulty_level not in ALLOWED_DIFFICULTY:
        return "无效的难度", None
    if len(position_name) > 200:
        return "岗位名称过长", None
    try:
        total_rounds = int(data.get("total_rounds", 5))
    except (TypeError, ValueError):
        return "total_rounds 必须是整数", None
    total_rounds = max(1, min(10, total_rounds))
    return None, StartParams(
        interview_type=interview_type,
        position_name=position_name,
        difficulty_level=difficulty_level,
        total_rounds=total_rounds,
        resume_id=data.get("resume_id"),
    )


class Turn(BaseModel):
    """一轮问答：三 Agent 共享的最小数据单元。

    ``score`` 为 ``None`` 表示"这一轮没评出来"（评估失败时诚实标注），
    调用方不得把它当作 0 分参与均分计算。
    """

    round: int
    question: str = ""
    question_type: str = DEFAULT_QUESTION_TYPE
    answer: str = ""
    score: Optional[float] = None
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    model_answer: str = ""
    evaluation_failed: bool = False

    def to_agent_dict(self) -> Dict[str, Any]:
        """转成面试官 / 能力评估 Agent 期望的历史 dict。"""
        return {
            "round": self.round,
            "question": self.question,
            "answer": self.answer,
            "question_type": self.question_type,
            "score": self.score,
        }


class InterviewContext(BaseModel):
    """喂给单个 Agent 的完整上下文（一次调用内的输入，不是跨请求状态）。"""

    interview_id: str = ""
    user_id: str = ""
    position: str = ""
    difficulty: str = "medium"
    interview_type: str = "mixed"
    resume: str = ""
    history: List[Turn] = Field(default_factory=list)


class QuestionOut(BaseModel):
    """面试官 Agent 的产出。"""

    question: str = ""
    question_type: str = DEFAULT_QUESTION_TYPE

    @classmethod
    def from_agent(cls, data: Optional[dict]) -> "QuestionOut":
        data = data or {}
        qtype = data.get("question_type") or DEFAULT_QUESTION_TYPE
        if qtype not in QUESTION_TYPES:
            qtype = DEFAULT_QUESTION_TYPE
        return cls(question=data.get("current_question") or "", question_type=qtype)


class EvaluationOut(BaseModel):
    """评估官 Agent 的产出。

    ``evaluation_failed=True`` 且 ``score=None`` 表示诚实失败——绝不伪造默认分。
    """

    score: Optional[float] = None
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    model_answer: str = ""
    evaluation_failed: bool = False

    @classmethod
    def from_agent(cls, data: Optional[dict]) -> "EvaluationOut":
        data = data or {}
        score = data.get("score")
        failed = bool(data.get("evaluation_failed", False)) or score is None
        return cls(
            score=score,
            strengths=list(data.get("strengths") or []),
            weaknesses=list(data.get("weaknesses") or []),
            suggestions=list(data.get("suggestions") or []),
            model_answer=data.get("model_answer") or "",
            evaluation_failed=failed,
        )

    def to_api_dict(self) -> Dict[str, Any]:
        """还原成对外接口（REST / MCP）返回的评估 dict。"""
        return {
            "score": self.score,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
            "model_answer": self.model_answer,
            "evaluation_failed": self.evaluation_failed,
        }


class StepResult(BaseModel):
    """提交一轮回答后的完整结果（REST / MCP / SSE 三入口共用）。"""

    evaluation: EvaluationOut
    completed: bool = False
    current_round: int = 1
    total_rounds: int = 1
    next_question: Optional[str] = None
    next_question_type: Optional[str] = None

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "evaluation": self.evaluation.to_api_dict(),
            "completed": self.completed,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "next_question": self.next_question,
        }
