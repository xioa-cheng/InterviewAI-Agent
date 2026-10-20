"""认证 API：注册 / 登录（JWT）"""
from datetime import datetime, timedelta
import re
import time
import uuid

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 进程内登录限流：同一邮箱 5 分钟内失败 5 次则暂时拒绝（防暴力破解）
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 300
_login_failures: dict[str, list[float]] = {}  # email(lower) -> 失败时间戳列表


def _too_many_failures(email: str) -> bool:
    ts = _login_failures.get(email.lower(), [])
    now = time.time()
    recent = [t for t in ts if now - t < _LOGIN_WINDOW_SECONDS]
    _login_failures[email.lower()] = recent
    return len(recent) >= _LOGIN_MAX_FAILURES


def _record_failure(email: str) -> None:
    _login_failures.setdefault(email.lower(), []).append(time.time())


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: str = Field(max_length=255)
    password: str = Field(min_length=6)
    full_name: str | None = Field(default=None, max_length=100)
    target_position: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=50)


class LoginRequest(BaseModel):
    email: str = Field(max_length=255)
    password: str


def hash_password(password: str) -> str:
    # bcrypt 只处理前 72 字节，超长需显式拒绝，避免静默截断
    if len(password.encode("utf-8")) > 72:
        raise ValueError("密码过长")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Bearer JWT 返回对应用户；无 token / token 无效一律 401，不再回退到任何默认用户。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub = payload.get("sub")
        user_id = uuid.UUID(sub)
    except (JWTError, ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在，请重新登录")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="账号已被禁用")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员权限校验：非 admin 一律 403。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if not _EMAIL_RE.match(data.email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    # 先查重再哈希，避免对重复注册做昂贵的 bcrypt 计算
    result = await db.execute(
        select(User).where(or_(User.email == data.email, User.username == data.username))
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="邮箱或用户名已存在")

    try:
        password_hash = hash_password(data.password)
    except ValueError:
        raise HTTPException(status_code=400, detail="密码过长（最多 72 字节）")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=password_hash,
        full_name=data.full_name,
        target_position=data.target_position,
        industry=data.industry,
        role="admin"
        if (settings.ADMIN_EMAIL and data.email.lower() == settings.ADMIN_EMAIL.lower())
        else "user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"token": create_access_token(str(user.id)), "user": user.to_dict()}


@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    if _too_many_failures(data.email):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        _record_failure(data.email)
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="账号已被禁用")

    _login_failures.pop(data.email.lower(), None)
    return {"token": create_access_token(str(user.id)), "user": user.to_dict()}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """校验当前 token 是否仍有效并返回用户信息（供前端启动时登录态自检）。"""
    return user.to_dict()
