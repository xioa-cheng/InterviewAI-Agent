"""题库建库 + 向量入库（幂等，启动时调用，优雅降级）"""
import asyncio
import json
import logging
import os

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.question_bank import QuestionBank
from app.rag.embedding import embed_texts
from app.rag.vectorstore import get_vector_store, upsert_embeddings

logger = logging.getLogger(__name__)

_SEED_PATH = os.path.join(os.path.dirname(__file__), "data", "seed_questions.json")
COLLECTION = "interview_questions"


async def seed_question_bank() -> int:
    """若题库为空，把预置题目写入 question_bank 表；返回写入数量"""
    try:
        with open(_SEED_PATH, "r", encoding="utf-8") as f:
            seed = json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"读取预置题库失败: {e}")
        return 0
    if not seed:
        return 0

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(QuestionBank))).scalar_one()
        if count:
            logger.info(f"题库已有 {count} 题，跳过建库")
            return 0
        for item in seed:
            db.add(
                QuestionBank(
                    question_content=item.get("question_content", ""),
                    question_type=item.get("question_type", "technical"),
                    category=item.get("category"),
                    difficulty=item.get("difficulty"),
                    industry=item.get("industry"),
                    position_tags=item.get("position_tags", []),
                    model_answer=item.get("model_answer"),
                    evaluation_criteria=item.get("evaluation_criteria", {}),
                )
            )
        await db.commit()
        logger.info(f"题库已入库 {len(seed)} 题")
        return len(seed)


async def ensure_question_index() -> int:
    """把题库全部题目向量化后写入 ChromaDB；返回索引条数（0 表示跳过或失败）"""
    store = get_vector_store()
    if not store:
        return 0
    try:
        collection = store.get_or_create_collection(COLLECTION)
        if collection.count() > 0:
            logger.info("向量索引已存在，跳过")
            return 0
    except Exception as e:  # noqa: BLE001
        logger.warning(f"检查向量索引失败: {e}")
        return 0

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(QuestionBank))).scalars().all()
        if not rows:
            return 0
        ids = [str(r.id) for r in rows]
        documents = [r.question_content or "" for r in rows]
        metadatas = [
            {
                "question_id": str(r.id),
                "question_type": r.question_type or "",
                "difficulty": r.difficulty or "",
                "category": r.category or "",
                "industry": r.industry or "",
            }
            for r in rows
        ]

    embeddings = await asyncio.to_thread(embed_texts, documents)
    if not embeddings:
        logger.warning("题目向量化失败，跳过索引")
        return 0
    await asyncio.to_thread(upsert_embeddings, COLLECTION, ids, documents, embeddings, metadatas)
    logger.info(f"向量索引已建立 {len(documents)} 条")
    return len(documents)
