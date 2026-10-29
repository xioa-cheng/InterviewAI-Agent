"""题库 / 练习记录 / 技能评估模型"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, Uuid

from app.database import Base
from app.models.types import JSONType


class QuestionBank(Base):
    __tablename__ = "question_bank"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    question_content = Column(Text, nullable=False)
    question_type = Column(String(30), nullable=False, index=True)
    category = Column(String(50), index=True)
    difficulty = Column(String(20))
    industry = Column(String(50))
    position_tags = Column(JSONType, default=list)
    model_answer = Column(Text)
    evaluation_criteria = Column(JSONType, default=dict)
    frequency = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    content_hash = Column(String(64), index=True)


class PracticeRecord(Base):
    __tablename__ = "practice_records"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Uuid, ForeignKey("question_bank.id"), nullable=True)
    practice_type = Column(String(30))
    answer_content = Column(Text)
    score = Column(Float)
    duration_seconds = Column(Integer)
    practiced_at = Column(DateTime, default=datetime.utcnow)


class SkillAssessment(Base):
    __tablename__ = "skill_assessments"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    interview_id = Column(Uuid, ForeignKey("interviews.id"), nullable=True)
    technical_skill = Column(Float)
    communication = Column(Float)
    problem_solving = Column(Float)
    leadership = Column(Float)
    teamwork = Column(Float)
    learning_ability = Column(Float)
    stress_management = Column(Float)
    assessed_at = Column(DateTime, default=datetime.utcnow)
