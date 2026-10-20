"""面试与问答记录模型"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.types import JSONType


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id = Column(Uuid, ForeignKey("resumes.id"), nullable=True)
    interview_type = Column(String(30), nullable=False, default="mixed")
    position_name = Column(String(200), nullable=False, default="")
    company_name = Column(String(200))
    industry = Column(String(50))
    difficulty_level = Column(String(20), default="medium")
    status = Column(String(20), default="ongoing", index=True)
    current_round = Column(Integer, default=1)
    total_rounds = Column(Integer, default=5)
    overall_score = Column(Float)
    content_score = Column(Float)
    expression_score = Column(Float)
    logic_score = Column(Float)
    technical_score = Column(Float)
    feedback_summary = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    duration_seconds = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="interviews")
    qa_pairs = relationship(
        "QAPair", back_populates="interview", cascade="all, delete-orphan", order_by="QAPair.question_number"
    )


class QAPair(Base):
    __tablename__ = "qa_pairs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    interview_id = Column(Uuid, ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False, index=True)
    question_number = Column(Integer, nullable=False, default=1)
    question_type = Column(String(30))
    question_content = Column(Text, nullable=False)
    question_context = Column(JSONType, default=dict)
    answer_content = Column(Text)
    answer_audio_url = Column(String(500))
    answer_duration_seconds = Column(Integer)
    score = Column(Float)
    strengths = Column(JSONType, default=list)
    weaknesses = Column(JSONType, default=list)
    suggestions = Column(JSONType, default=list)
    model_answer = Column(Text)
    asked_at = Column(DateTime, default=datetime.utcnow)
    answered_at = Column(DateTime)

    interview = relationship("Interview", back_populates="qa_pairs")
