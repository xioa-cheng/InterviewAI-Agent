"""题库管理 API：增删改查 + 分页筛选 + 批量导入，写操作自动维护向量索引。

所有接口均需管理员权限（require_admin）。每次新增/修改会即时增量索引单题，
删除会同步删除向量库中的对应向量，避免孤儿向量污染召回。
"""
import csv
import io
import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_admin
from app.database import get_db
from app.llm.client import agenerate_structured
from app.models.question_bank import QuestionBank
from app.models.user import User
from app.rag.indexing import (
    delete_question_vector,
    ensure_question_index,
    index_single_question,
    prune_orphan_vectors,
)

router = APIRouter(prefix="/api/v1/questions", tags=["questions"])

_QTYPES = {"technical", "behavioral", "hr", "mixed"}


def _parse_qid(question_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(question_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="题目不存在")


# ----------------------------- 请求/响应模型 -----------------------------
class QuestionCreate(BaseModel):
    question_content: str = Field(min_length=1)
    question_type: str = "technical"
    category: Optional[str] = None
    difficulty: Optional[str] = None
    industry: Optional[str] = None
    position_tags: List[str] = []
    model_answer: Optional[str] = None
    evaluation_criteria: dict = {}


class QuestionUpdate(BaseModel):
    question_content: Optional[str] = None
    question_type: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    industry: Optional[str] = None
    position_tags: Optional[List[str]] = None
    model_answer: Optional[str] = None
    evaluation_criteria: Optional[dict] = None


class QuestionOut(BaseModel):
    id: str
    question_content: str
    question_type: str
    category: Optional[str] = None
    difficulty: Optional[str] = None
    industry: Optional[str] = None
    position_tags: list = []
    model_answer: Optional[str] = None
    evaluation_criteria: dict = {}
    frequency: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class QuestionList(BaseModel):
    total: int
    items: List[QuestionOut]


class ImportResult(BaseModel):
    created: int
    skipped: int
    indexed: int


class ImportItem(BaseModel):
    question_content: str = Field(min_length=1)
    question_type: str = "technical"
    category: Optional[str] = None
    difficulty: Optional[str] = None
    industry: Optional[str] = None
    position_tags: List[str] = []
    model_answer: Optional[str] = None
    evaluation_criteria: dict = {}


class GeneratedQuestions(BaseModel):
    """LLM 生成题目的结构化输出容器。"""
    items: List[ImportItem]


class GenerateRequest(BaseModel):
    position: str = Field(min_length=1)
    industry: Optional[str] = None
    count: int = Field(default=5, ge=1, le=20)
    question_types: List[str] = ["technical"]
    difficulty: Optional[str] = None


async def _bulk_insert(db: AsyncSession, items: List[ImportItem]) -> ImportResult:
    """去重插入题目并增量索引；供 JSON / CSV / LLM 生成共用。"""
    existing = (await db.execute(select(QuestionBank.question_content))).scalars().all()
    existing_set = set(existing)
    created = 0
    skipped = 0
    for item in items:
        if item.question_content in existing_set:
            skipped += 1
            continue
        qtype = item.question_type if item.question_type in _QTYPES else "technical"
        db.add(
            QuestionBank(
                question_content=item.question_content,
                question_type=qtype,
                category=item.category,
                difficulty=item.difficulty,
                industry=item.industry,
                position_tags=item.position_tags,
                model_answer=item.model_answer,
                evaluation_criteria=item.evaluation_criteria,
            )
        )
        existing_set.add(item.question_content)
        created += 1
    await db.commit()
    indexed = await ensure_question_index()
    return ImportResult(created=created, skipped=skipped, indexed=indexed)


# ----------------------------- 端点 -----------------------------
@router.get("", response_model=QuestionList)
async def list_questions(
    question_type: Optional[str] = None,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    industry: Optional[str] = None,
    tag: Optional[str] = None,
    keyword: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """分页 + 多维筛选列出题库题目。"""
    if limit > 200:
        limit = 200
    stmt = select(QuestionBank)
    if question_type:
        stmt = stmt.where(QuestionBank.question_type == question_type)
    if category:
        stmt = stmt.where(QuestionBank.category == category)
    if difficulty:
        stmt = stmt.where(QuestionBank.difficulty == difficulty)
    if industry:
        stmt = stmt.where(QuestionBank.industry == industry)
    if keyword:
        stmt = stmt.where(QuestionBank.question_content.contains(keyword))
    rows = (await db.execute(stmt.order_by(QuestionBank.created_at.desc()))).scalars().all()
    if tag:
        rows = [r for r in rows if tag in (r.position_tags or [])]
    total = len(rows)
    page = rows[skip : skip + limit]
    items = [QuestionOut.model_validate(r, from_attributes=True) for r in page]
    return QuestionList(total=total, items=items)


@router.get("/{question_id}", response_model=QuestionOut)
async def get_question(question_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    q = await db.get(QuestionBank, _parse_qid(question_id))
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    return QuestionOut.model_validate(q, from_attributes=True)


@router.post("", response_model=QuestionOut, status_code=201)
async def create_question(
    payload: QuestionCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
):
    qtype = payload.question_type if payload.question_type in _QTYPES else "technical"
    q = QuestionBank(
        question_content=payload.question_content,
        question_type=qtype,
        category=payload.category,
        difficulty=payload.difficulty,
        industry=payload.industry,
        position_tags=payload.position_tags,
        model_answer=payload.model_answer,
        evaluation_criteria=payload.evaluation_criteria,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    await index_single_question(q.id)  # 写即索引
    return QuestionOut.model_validate(q, from_attributes=True)


@router.put("/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: str, payload: QuestionUpdate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
):
    qid = _parse_qid(question_id)
    q = await db.get(QuestionBank, qid)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(q, key, value)
    await db.commit()
    await db.refresh(q)
    await index_single_question(q.id)  # 编辑即重嵌
    return QuestionOut.model_validate(q, from_attributes=True)


@router.delete("/{question_id}")
async def delete_question(
    question_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
):
    qid = _parse_qid(question_id)
    q = await db.get(QuestionBank, qid)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    await db.delete(q)
    await db.commit()
    await delete_question_vector(qid)  # 删即删向量
    return {"detail": "已删除", "id": str(qid)}


@router.post("/import", response_model=ImportResult)
async def import_questions_json(
    payload: List[ImportItem], db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
):
    """批量导入（JSON 数组），自动去重（题干已存在则跳过）并增量索引。"""
    return await _bulk_insert(db, list(payload))


@router.post("/import-csv", response_model=ImportResult)
async def import_questions_csv(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
):
    """批量导入（CSV，UTF-8，首行为表头）。

    表头：question_content,question_type,category,difficulty,industry,
    position_tags(逗号分隔),model_answer,evaluation_criteria(JSON 字符串，可选)
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码须为 UTF-8")

    reader = csv.DictReader(io.StringIO(text))
    items: List[ImportItem] = []
    for row in reader:
        content = (row.get("question_content") or "").strip()
        if not content:
            continue
        tags_raw = (row.get("position_tags") or "").strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        ev_raw = (row.get("evaluation_criteria") or "").strip()
        ev = {}
        if ev_raw:
            try:
                ev = json.loads(ev_raw)
            except json.JSONDecodeError:
                ev = {}
        items.append(
            ImportItem(
                question_content=content,
                question_type=(row.get("question_type") or "technical").strip() or "technical",
                category=(row.get("category") or "").strip() or None,
                difficulty=(row.get("difficulty") or "").strip() or None,
                industry=(row.get("industry") or "").strip() or None,
                position_tags=tags,
                model_answer=(row.get("model_answer") or "").strip() or None,
                evaluation_criteria=ev,
            )
        )
    return await _bulk_insert(db, items)


@router.post("/generate", response_model=ImportResult)
async def generate_questions(
    req: GenerateRequest, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
):
    """用 LLM 按岗位批量生成题目并入库（自动去重 + 索引）。用于扩充语料。"""
    types_str = ", ".join(t for t in req.question_types if t in _QTYPES) or "technical"
    prompt = (
        f"你是一位资深技术面试官。请为「{req.position}」岗位"
        + (f"（行业：{req.industry}）" if req.industry else "")
        + f"生成 {req.count} 道高质量面试题。\n"
        f"题型限定为：{types_str}。"
        + (f"难度：{req.difficulty}。" if req.difficulty else "")
        + "\n每道题必须包含字段：question_content（题干）、question_type、category（技术分类）、"
          "difficulty、industry、position_tags（相关技术标签数组）、model_answer（参考答案）、"
          "evaluation_criteria（评分要点对象，例如 {维度: 要点}）。\n"
          "要求：题目不重复、贴合岗位实际、有区分度。"
    )
    result = await agenerate_structured(prompt, GeneratedQuestions)
    if not result or not result.get("items"):
        raise HTTPException(status_code=502, detail="LLM 生成题目失败，请稍后重试")
    items = [ImportItem(**it) for it in result["items"]]
    return await _bulk_insert(db, items)


@router.post("/prune", response_model=dict)
async def prune_vectors(_: User = Depends(require_admin)):
    """一致性校验：清理向量库中已无对应题目的孤儿向量。"""
    removed = await prune_orphan_vectors()
    return {"removed": removed}
