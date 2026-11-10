"""reindex_all() 回归测试：强制重建索引必须真的把向量写回。

背景（真实 bug）：原实现里 `upsert_embeddings` 那一行缩进落在 `return 0`
之后，是永不执行的死代码；调用重建端点会先 delete_collection 清空向量库，
却不写回任何向量，还返回题目条数谎报成功。另外只要嵌入接口失败，
被清空的集合同样无法恢复，稠密召回整条链路就此失效。

测试策略：真实 SQLAlchemy 模型 + 内存 SQLite；ChromaDB 用 FakeStore 承接
（但写库路径走的是真实的 app.rag.vectorstore.upsert_embeddings 实现）；
只有远程嵌入接口被替换成可控的假向量。
"""
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app import models  # noqa: F401  注册全部模型
from app.models.question_bank import QuestionBank
from app.rag import indexing, vectorstore


class FakeCollection:
    def __init__(self, ids=None):
        self._ids = list(ids or [])

    def upsert(self, ids, documents, embeddings, metadatas=None):
        self._ids = list(ids)

    def count(self):
        return len(self._ids)


class FakeStore:
    def __init__(self, existing_ids=None, collection_exists=True):
        self.collection = FakeCollection(existing_ids) if collection_exists else None
        self.deleted = []

    def delete_collection(self, name):
        # 与真实 ChromaDB 一致：集合不存在时会抛错
        if self.collection is None:
            raise ValueError(f"Collection [{name}] does not exist")
        self.deleted.append(name)
        self.collection = FakeCollection()

    def get_or_create_collection(self, name):
        if self.collection is None:
            self.collection = FakeCollection()
        return self.collection


async def _make_session(n_questions):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        for i in range(n_questions):
            db.add(
                QuestionBank(
                    question_content=f"第{i}题：Redis 缓存击穿如何处理？",
                    question_type="technical",
                    category="缓存",
                    position_tags=["后端开发工程师"],
                    model_answer="参考答案",
                    evaluation_criteria=["要点A", "要点B"],
                )
            )
        await db.commit()
    return engine, SessionLocal


def _patch(monkeypatch, SessionLocal, store, embed, calls):
    monkeypatch.setattr(indexing, "AsyncSessionLocal", SessionLocal)
    monkeypatch.setattr(indexing, "get_vector_store", lambda: store)
    monkeypatch.setattr(vectorstore, "get_vector_store", lambda: store)
    monkeypatch.setattr(indexing, "embed_texts", embed)
    monkeypatch.setattr(indexing, "_invalidate_retrieval_cache", lambda: calls.append("invalidate"))


def _vectors(texts):
    return [[0.1] * 8 for _ in texts]


def test_reindex_all_writes_vectors_and_returns_real_count(monkeypatch):
    """核心回归：重建后集合里必须真有向量，返回值必须等于实际写入条数。"""
    async def impl():
        engine, SessionLocal = await _make_session(3)
        store = FakeStore()
        calls = []
        _patch(monkeypatch, SessionLocal, store, _vectors, calls)

        n = await indexing.reindex_all()

        assert n == 3, "返回值应是实际写入的向量条数"
        assert store.collection.count() == 3, "向量必须真的写回集合"
        assert store.deleted == [indexing.COLLECTION], "应只清空一次集合"
        assert calls == ["invalidate"], "重建后必须刷新检索侧题库缓存"
        async with SessionLocal() as db:
            rows = (await db.execute(select(QuestionBank))).scalars().all()
            assert len(rows) == 3
            assert all(r.content_hash for r in rows), "content_hash 应回写"
        await engine.dispose()

    asyncio.run(impl())


def test_reindex_all_keeps_existing_index_when_embedding_fails(monkeypatch):
    """嵌入失败时不得清空现有索引（旧实现会先删集合再失败）。"""
    async def impl():
        engine, SessionLocal = await _make_session(3)
        store = FakeStore(existing_ids=["a", "b", "c"])
        calls = []
        _patch(monkeypatch, SessionLocal, store, lambda texts: None, calls)

        n = await indexing.reindex_all()

        assert n == 0
        assert store.deleted == [], "嵌入失败时绝不能删集合"
        assert store.collection.count() == 3, "现有索引必须保持可用"
        assert calls == [], "失败路径不应谎称刷新了缓存"
        async with SessionLocal() as db:
            rows = (await db.execute(select(QuestionBank))).scalars().all()
            assert all(r.content_hash is None for r in rows), "失败路径不应回写 hash"
        await engine.dispose()

    asyncio.run(impl())


def test_reindex_all_rejects_partial_embedding(monkeypatch):
    """向量条数与题目数不符时中止，不能把半份索引写进去。"""
    async def impl():
        engine, SessionLocal = await _make_session(3)
        store = FakeStore(existing_ids=["a", "b", "c"])
        _patch(monkeypatch, SessionLocal, store, lambda texts: [[0.1] * 8], [])

        n = await indexing.reindex_all()

        assert n == 0
        assert store.deleted == []
        assert store.collection.count() == 3
        await engine.dispose()

    asyncio.run(impl())


def test_reindex_all_empty_bank_is_noop(monkeypatch):
    """空题库直接返回，不触碰已有索引。"""
    async def impl():
        engine, SessionLocal = await _make_session(0)
        store = FakeStore(existing_ids=["a"])
        _patch(monkeypatch, SessionLocal, store, _vectors, [])

        n = await indexing.reindex_all()

        assert n == 0
        assert store.deleted == []
        assert store.collection.count() == 1
        await engine.dispose()

    asyncio.run(impl())


def test_reindex_all_works_when_collection_missing(monkeypatch):
    """真实路径回归：向量集合不存在时重建仍要成功。

    容器内验证发现：全新部署或集合被手动删除后，Chroma 的
    delete_collection 会抛 not exist，旧实现会让重建端点返回 0。
    """
    async def impl():
        engine, SessionLocal = await _make_session(3)
        store = FakeStore(collection_exists=False)
        calls = []
        _patch(monkeypatch, SessionLocal, store, _vectors, calls)

        n = await indexing.reindex_all()

        assert n == 3
        assert store.collection.count() == 3, "空库下也必须写入向量"
        assert store.deleted == [indexing.COLLECTION]
        assert calls == ["invalidate"]
        await engine.dispose()

    asyncio.run(impl())
