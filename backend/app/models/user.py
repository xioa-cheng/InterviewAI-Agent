"""用户模型"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, JSON, String, Uuid
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100))
    target_position = Column(String(200))
    industry = Column(String(50))
    experience_level = Column(String(20))
    preferences = Column(JSON, default=dict)
    role = Column(String(20), nullable=False, default="user", index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resumes = relationship("Resume", back_populates="user")
    interviews = relationship("Interview", back_populates="user")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "target_position": self.target_position,
            "industry": self.industry,
            "experience_level": self.experience_level,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
