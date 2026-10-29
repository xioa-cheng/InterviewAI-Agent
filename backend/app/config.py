"""应用配置：从 .env / 环境变量读取"""
import logging
import secrets
from functools import lru_cache
from typing import List, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "InterviewAI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENV: str = "development"  # development / production

    DATABASE_URL: str = "sqlite+aiosqlite:///./interviewai.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # 密钥：不再内置弱默认值。未设置时：开发环境自动生成随机密钥（重启失效），
    # 生产环境（ENV=production）则直接启动失败，强制配置，杜绝令牌被伪造。
    SECRET_KEY: Optional[str] = None
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

    # 工具 / MCP 相关
    ENABLE_CODE_TOOLS: bool = False  # 是否开启「代码执行」工具（默认关闭，需隔离环境）
    MCP_SERVER_URLS: List[str] = []  # 外部 MCP Server（SSE）地址列表，留空则不加载外部工具
    MCP_DEFAULT_USER_EMAIL: Optional[str] = None  # MCP Server 自动创建服务账号时使用的邮箱

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def _resolve_secret(self) -> "Settings":
        if not self.SECRET_KEY:
            if self.ENV == "production":
                raise ValueError(
                    "生产环境必须设置 SECRET_KEY（请配置一个随机强密钥，例如 openssl rand -hex 32）"
                )
            self.SECRET_KEY = secrets.token_urlsafe(48)
            logging.getLogger(__name__).warning(
                "SECRET_KEY 未设置：开发环境下已生成临时随机密钥（进程重启后失效，仅用于本地开发）"
            )
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
