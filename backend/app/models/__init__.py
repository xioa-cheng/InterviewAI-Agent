"""模型聚合导出，便于 create_all 注册全部表"""
from app.models.user import User
from app.models.resume import Resume
from app.models.interview import Interview, QAPair
from app.models.question_bank import QuestionBank, PracticeRecord, SkillAssessment

__all__ = [
    "User",
    "Resume",
    "Interview",
    "QAPair",
    "QuestionBank",
    "PracticeRecord",
    "SkillAssessment",
]
