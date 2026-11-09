"""面试编排层：三 Agent 的调度中枢（REST / SSE / MCP 三个入口共用）。

- ``contracts`` : Agent 之间传递的结构化消息契约（Pydantic）
- ``errors``    : 流程校验异常，REST 转 HTTP 状态码、MCP 转 {"error": ...}
- ``service``   : ``InterviewOrchestrator`` 编排器本体
- ``report``    : 报告组装（只读，供 REST 与 MCP 共用）
"""
from app.orchestrator.contracts import (
    ALLOWED_DIFFICULTY,
    ALLOWED_INTERVIEW_TYPES,
    DEFAULT_QUESTION_TYPE,
    QUESTION_TYPES,
    EvaluationOut,
    InterviewContext,
    QuestionOut,
    StartParams,
    StepResult,
    Turn,
    validate_start_params,
)
from app.orchestrator.errors import (
    AlreadyAnswered,
    InterviewNotFound,
    InvalidInterviewId,
    NoPendingQuestion,
    OrchestrationError,
    PermissionDenied,
)
from app.orchestrator.service import (
    AdvanceOutcome,
    InterviewOrchestrator,
    PendingTurn,
    StartResult,
)

__all__ = [
    "ALLOWED_DIFFICULTY",
    "ALLOWED_INTERVIEW_TYPES",
    "DEFAULT_QUESTION_TYPE",
    "QUESTION_TYPES",
    "AdvanceOutcome",
    "AlreadyAnswered",
    "EvaluationOut",
    "InterviewContext",
    "InterviewNotFound",
    "InterviewOrchestrator",
    "InvalidInterviewId",
    "NoPendingQuestion",
    "OrchestrationError",
    "PendingTurn",
    "PermissionDenied",
    "QuestionOut",
    "StartParams",
    "StartResult",
    "StepResult",
    "Turn",
    "validate_start_params",
]
