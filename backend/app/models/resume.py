"""简历模型"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.types import JSONType


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text)
    parsed_data = Column(JSONType, default=dict)
    skills = Column(JSONType, default=list)
    projects = Column(JSONType, default=list)
    work_experience = Column(JSONType, default=list)
    education = Column(JSONType, default=list)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="resumes")
