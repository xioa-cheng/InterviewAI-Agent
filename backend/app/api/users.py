"""用户 API：个人资料 + 管理员用户管理（增删改查）。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import (
    _EMAIL_RE,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from app.database import get_db
from app.models import Interview, QAPair, Resume, User

router = APIRouter(prefix="/api/v1/users", tags=["users"])
admin_router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])


def _parse_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    target_position: str | None = None
    industry: str | None = None
    experience_level: str | None = None


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: str = Field(max_length=255)
    password: str = Field(min_length=6)
    role: str = "user"
    full_name: str | None = None
    target_position: str | None = None
    industry: str | None = None
    experience_level: str | None = None


class AdminUserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    full_name: str | None = None
    target_position: str | None = None
    industry: str | None = None
    experience_level: str | None = None


class AdminResetPassword(BaseModel):
    new_password: str = Field(min_length=6)


# ---------- 个人资料 ----------

@router.patch("/me")
async def update_me(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user.to_dict()


@router.post("/me/password")
async def change_password(
    data: ChangePassword,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    try:
        user.password_hash = hash_password(data.new_password)
    except ValueError:
        raise HTTPException(status_code=400, detail="密码过长（最多 72 字节）")
    await db.commit()
    return {"detail": "密码已更新"}


# ---------- 管理员用户管理 ----------

@admin_router.get("")
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return [u.to_dict() for u in result.scalars().all()]


@admin_router.post("", status_code=201)
async def create_user(
    data: AdminUserCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not _EMAIL_RE.match(data.email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    if data.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="角色只能是 user 或 admin")

    exists = await db.execute(
        select(User).where(or_(User.email == data.email, User.username == data.username))
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="邮箱或用户名已存在")

    try:
        password_hash = hash_password(data.password)
    except ValueError:
        raise HTTPException(status_code=400, detail="密码过长（最多 72 字节）")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=password_hash,
        role=data.role,
        full_name=data.full_name,
        target_position=data.target_position,
        industry=data.industry,
        experience_level=data.experience_level,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.to_dict()


@admin_router.patch("/{user_id}")
async def update_user(
    user_id: str,
    data: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    uid = _parse_user_id(user_id)
    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if data.role is not None and data.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="角色只能是 user 或 admin")

    # 自我保护：管理员不能把自己降级或禁用，避免把自己锁在门外
    if user.id == admin.id:
        if data.role is not None and data.role != "admin":
            raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
        if data.is_active is False:
            raise HTTPException(status_code=400, detail="不能禁用自己")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user.to_dict()


@admin_router.post("/{user_id}/password")
async def reset_password(
    user_id: str,
    data: AdminResetPassword,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    uid = _parse_user_id(user_id)
    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        user.password_hash = hash_password(data.new_password)
    except ValueError:
        raise HTTPException(status_code=400, detail="密码过长（最多 72 字节）")
    await db.commit()
    return {"detail": "密码已重置"}


@admin_router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    uid = _parse_user_id(user_id)
    if uid == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 按顺序清理关联数据（跨 SQLite/PostgreSQL 稳妥）：问答 -> 面试 -> 简历 -> 用户
    interview_ids = select(Interview.id).where(Interview.user_id == uid)
    await db.execute(delete(QAPair).where(QAPair.interview_id.in_(interview_ids)))
    await db.execute(delete(Interview).where(Interview.user_id == uid))
    await db.execute(delete(Resume).where(Resume.user_id == uid))
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()
    return {"detail": "用户已删除"}


@admin_router.post("/reindex", tags=["admin"])
async def reindex_question_bank(admin: User = Depends(require_admin)):
    """强制重建题库向量索引（新增/修改题目后手动触发）。"""
    from app.rag.indexing import reindex_all
    from app.rag.retrieval import clear_questions_cache as clear_retrieval_cache

    try:
        n = await reindex_all()
        # 同时刷新检索侧题目缓存，确保出题/评分立即使用新题库（reindex_all 内部也会清，这里双保险）
        clear_retrieval_cache()
        return {"indexed": n}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"重建索引失败: {e}")
