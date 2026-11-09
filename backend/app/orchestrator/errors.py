"""编排层异常：同一套语义，REST 转 HTTP 状态码、MCP 转 {"error": ...}。

把"面试不存在 / 无权访问 / 当前没有待回答的问题"这类流程校验从接口层收归一处，
三个入口共用，避免各自写一遍判断（重构前 MCP 与 REST 的提示语就不一致）。
"""
from typing import Optional


class OrchestrationError(Exception):
    """编排层基类异常。"""

    message = "面试流程异常"
    http_status = 400

    def __init__(self, message: Optional[str] = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)


class InvalidInterviewId(OrchestrationError):
    message = "无效的 interview_id"
    http_status = 400


class InterviewNotFound(OrchestrationError):
    message = "面试不存在"
    http_status = 404


class PermissionDenied(OrchestrationError):
    message = "无权访问该面试"
    http_status = 403


class NoPendingQuestion(OrchestrationError):
    message = "当前没有待回答的问题"
    http_status = 404


class AlreadyAnswered(OrchestrationError):
    message = "当前问题已作答"
    http_status = 400
