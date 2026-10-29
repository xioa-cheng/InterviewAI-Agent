"""题库建库 + 向量入库（幂等，启动时调用，优雅降级）

改进点（相对旧版）：
  - 向量索引改为「增量」：仅在向量库中缺失的题目才被嵌入写入，
    解决旧版「只在首次启动建一次索引，之后新增题目不会进向量库」的问题。
  - 嵌入文本从纯题干扩展为「题干 + 分类 + 标签」，提升语义召回质量。
  - 元数据补充逗号拼接的 tags，便于排查与未来扩展。
"""
import asyncio
import hashlib
import json
import logging
import os
import uuid

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.question_bank import QuestionBank
from app.rag.embedding import embed_texts
from app.rag.vectorstore import get_vector_store, upsert_embeddings

logger = logging.getLogger(__name__)

_SEED_PATH = os.path.join(os.path.dirname(__file__), "data", "seed_questions.json")
COLLECTION = "interview_questions"


def _build_doc(content: str, category: str, tags) -> str:
    """拼接更丰富的嵌入文本：题干 + 分类 + 标签。"""
    parts = [content]
    if category:
        parts.append(f"分类：{category}")
    if tags:
        parts.append("标签：" + "，".join(tags))
    return "\n".join(parts)


def _doc_text(r: "QuestionBank") -> str:
    """单题的嵌入文本（与 _build_doc 同源），用于生成变更指纹。"""
    return _build_doc(r.question_content or "", r.category or "", r.position_tags or [])


def _content_hash(r: "QuestionBank") -> str:
    """基于嵌入文本计算 SHA256，用于检测题目内容是否变更。"""
    return hashlib.sha256(_doc_text(r).encode("utf-8")).hexdigest()


def _meta(r: "QuestionBank") -> dict:
    return {
        "question_id": str(r.id),
        "question_type": r.question_type or "",
        "difficulty": r.difficulty or "",
        "category": r.category or "",
        "industry": r.industry or "",
        "tags": ", ".join(r.position_tags or []),
    }


def clear_questions_cache():
    """清空向量库内存缓存（供 reindex 端点调用，使下次访问重新加载）。"""
    from app.rag.vectorstore import clear_vector_store_cache

    clear_vector_store_cache()


def _invalidate_retrieval_cache() -> None:
    """刷新检索侧题目缓存（retrieval 模块的内存题库快照）。

    题库经由 API 增删改后，retrieval.hybrid_retrieve / retrieve_rubric_by_question
    依赖的内存快照必须失效，否则新增题目不会被出题召回、已删除题目仍可能被 BM25 召回。
    与 indexing.clear_questions_cache（清向量库单例）是两个不同的缓存，此处专指检索快照。
    """
    try:
        from app.rag.retrieval import clear_questions_cache as clear_retrieval_cache

        clear_retrieval_cache()
    except Exception:  # noqa: BLE001
        pass


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
    """增量地把题库题目向量化后写入 ChromaDB。

    采用「ID 缺失 + content_hash 变更」双重判定：
      - 新题目（Chroma 中无该 id）会被索引；
      - 已存在但题目内容/分类/标签变更（hash 不一致）会被重嵌，
        修复旧版「编辑旧题不更新向量」的静默错误。
    返回本轮新增/更新索引条数（0 表示已是最新或失败/禁用）。
    """
    store = get_vector_store()
    if not store:
        return 0
    try:
        collection = store.get_or_create_collection(COLLECTION)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"检查向量索引失败: {e}")
        return 0

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(QuestionBank))).scalars().all()
        if not rows:
            return 0
        by_id = {str(r.id): r for r in rows}

        # 已索引的题目 id 集合
        existing: set = set()
        try:
            existing = set(collection.get(ids=list(by_id.keys()), include=[])["ids"])
        except Exception:  # noqa: BLE001
            existing = set()

        # (id_str, 当前hash) —— 缺失或内容变更都需要重嵌
        to_index = []
        for rid, r in by_id.items():
            cur_hash = _content_hash(r)
            if (rid not in existing) or (r.content_hash != cur_hash):
                to_index.append((rid, cur_hash))

        if not to_index:
            logger.info("向量索引已是最新，跳过")
            return 0

        ids = [rid for rid, _ in to_index]
        documents = [_doc_text(by_id[rid]) for rid in ids]
        metadatas = [_meta(by_id[rid]) for rid in ids]

    embeddings = await asyncio.to_thread(embed_texts, documents)
    if not embeddings:
        logger.warning("题目向量化失败，跳过索引")
        return 0
    await asyncio.to_thread(upsert_embeddings, COLLECTION, ids, documents, embeddings, metadatas)

    # 回写 content_hash，供下次变更检测
    async with AsyncSessionLocal() as db:
        for rid, h in to_index:
            obj = await db.get(QuestionBank, uuid.UUID(rid))
            if obj:
                obj.content_hash = h
        await db.commit()

    logger.info(f"向量索引新增/更新 {len(documents)} 条（累计 {collection.count()} 条）")
    return len(documents)


async def reindex_all() -> int:
    """强制重建索引：清空集合后全量写入（供运行时加题/修正后手动调用）。"""
    store = get_vector_store()
    if not store:
        return 0
    try:
        store.delete_collection(COLLECTION)
        collection = store.get_or_create_collection(COLLECTION)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"重建向量索引失败: {e}")
        return 0

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(QuestionBank))).scalars().all()
        if not rows:
            return 0
        by_id = {str(r.id): r for r in rows}
        ids = list(by_id.keys())
        documents = [_doc_text(r) for r in by_id.values()]
        metadatas = [_meta(r) for r in by_id.values()]

    embeddings = await asyncio.to_thread(embed_texts, documents)
    if not embeddings:
        logger.warning("题目向量化失败，跳过重建")
        return 0
        await asyncio.to_thread(upsert_embeddings, COLLECTION, ids, documents, embeddings, metadatas)

    # 同步回写所有题目的 content_hash
    async with AsyncSessionLocal() as db:
        for rid, r in by_id.items():
            obj = await db.get(QuestionBank, uuid.UUID(rid))
            if obj:
                obj.content_hash = _content_hash(r)
        await db.commit()

    # 题库整体已变：刷新检索侧题目缓存，确保出题/评分依据立即反映新内容
    _invalidate_retrieval_cache()
    logger.info(f"向量索引已重建 {len(documents)} 条")
    return len(documents)


async def index_single_question(qid: uuid.UUID) -> bool:
    """索引（或重嵌）单道题，供 CRUD 写操作后自动调用。返回是否成功。"""
    store = get_vector_store()
    if not store:
        return False
    async with AsyncSessionLocal() as db:
        r = await db.get(QuestionBank, qid)
        if not r:
            return False
        rid = str(r.id)
        doc = _doc_text(r)
        meta = _meta(r)
        h = _content_hash(r)

    try:
        embeddings = await asyncio.to_thread(embed_texts, [doc])
        if not embeddings:
            logger.warning(f"单题向量化失败 {qid}")
            return False
        await asyncio.to_thread(upsert_embeddings, COLLECTION, [rid], [doc], embeddings, [meta])
        async with AsyncSessionLocal() as db:
            obj = await db.get(QuestionBank, qid)
            if obj:
                obj.content_hash = h
            await db.commit()
        # 单题新增/更新：刷新检索侧缓存，使该题立即可被出题/评分召回
        _invalidate_retrieval_cache()
        logger.info(f"单题索引完成 {qid}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"单题索引失败 {qid}: {e}")
        return False


async def delete_question_vector(qid: uuid.UUID) -> bool:
    """从向量库删除单题向量，供题目删除时同步调用，避免孤儿向量。"""
    store = get_vector_store()
    if not store:
        return False
    try:
        def _do():
            collection = store.get_or_create_collection(COLLECTION)
            collection.delete(ids=[str(qid)])

        await asyncio.to_thread(_do)
        # 单题删除：刷新检索侧缓存，避免已删题目仍被 BM25 稀疏召回
        _invalidate_retrieval_cache()
        logger.info(f"单题向量已删除 {qid}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"删除向量失败 {qid}: {e}")
        return False


async def prune_orphan_vectors() -> int:
    """删除向量库中存在、但数据库已无对应题目的孤儿向量；返回删除条数。

    用于一致性校验：例如曾手动删库未清向量、或删题时向量删除失败的补救。
    """
    store = get_vector_store()
    if not store:
        return 0
    try:
        collection = store.get_or_create_collection(COLLECTION)
    except Exception:  # noqa: BLE001
        return 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(QuestionBank.id))).scalars().all()
        db_ids = {str(r) for r in rows}
    try:
        all_ids = set(collection.get(include=[])["ids"])
    except Exception:  # noqa: BLE001
        return 0
    orphans = [i for i in all_ids if i not in db_ids]
    if not orphans:
        return 0
    try:
        collection.delete(ids=orphans)
        logger.info(f"清理孤儿向量 {len(orphans)} 条")
        return len(orphans)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"清理孤儿向量失败: {e}")
        return 0
