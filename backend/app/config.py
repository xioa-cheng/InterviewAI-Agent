"""应用配置：从 .env / 环境变量读取"""
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "InterviewAI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    DATABASE_URL: str = "sqlite+aiosqlite:///./interviewai.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "CHANGE_ME_insecure_dev_only"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    ADMIN_EMAIL: Optional[str] = None

    LLM_PROVIDER: str = "deepseek"
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    OPENAI_API_KEY: Optional[str] = None
    EMBEDDING_MODEL: str = "text-embedding-v3"
    EMBEDDING_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_API_KEY: Optional[str] = None
    VECTOR_STORE_PATH: str = "./data/vectorstore"

    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:80"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# 弱密钥哨兵集合：命中则启动时告警，提示配置随机密钥
_INSECURE_KEYS = {
    "your-secret-key",
    "interviewai-secret",
    "interviewai-secret-change-me",
    "interviewai-dev-secret-change-me",
    "CHANGE_ME_insecure_dev_only",
}
if settings.SECRET_KEY in _INSECURE_KEYS:
    import logging

    logging.getLogger(__name__).warning(
        "SECRET_KEY 仍为不安全/默认值，请务必在 .env 中配置随机密钥"
    )
