"""出题时混合检索题库参考题：结构化元数据软过滤 + 稠密向量 + BM25 关键词 → RRF 融合 → 多样性去重。

相比旧版的「纯向量 + 单字段 difficulty 过滤」，新增：
  - 关键词层（纯 Python BM25，对中文/英文技术术语精确命中，不依赖外部依赖，SQLite/PG 通用）
  - RRF（Reciprocal Rank Fusion）融合稠密与稀疏两种召回
  - 与应聘岗位/行业匹配的元数据软加分（替代原先生硬的 difficulty 硬过滤）
  - 基于 Jaccard 相似度的多样性去重，避免重复出题、排除历史已问题目
  - 富化查询（拼接简历关键词，提升语义召回相关性）
所有步骤均优雅降级：任一环节失败都不影响出题，最坏退回空参考。
"""
import asyncio
import logging
import math
import re
from typing import Dict, List, Optional, Set

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.question_bank import QuestionBank
from app.rag.embedding import embed_query
from app.rag.vectorstore import query_embeddings

logger = logging.getLogger(__name__)

COLLECTION = "interview_questions"
_RRF_K = 60
_CANDIDATE_N = 20
_SIMILARITY_JACCARD = 0.6

# 内存缓存的题目列表（题库基本稳定）。运行时题目变更后必须调用 clear_questions_cache()
# 显式刷新；_CACHE_TTL 作为兜底，防止任何写路径遗漏刷新导致缓存永久陈旧。
_questions_cache: Optional[List[dict]] = None
_cache_ts: float = 0.0
_CACHE_TTL = 120.0  # 秒


def _tokenize(text: str) -> List[str]:
    """中英文混合分词：拉丁/数字连续串(>=2)作为一个 token，CJK 按单字切。

    这样既能精确命中 Redis / GIL / MySQL 这类英文术语，也能对中文做字符级重叠匹配。
    """
    if not text:
        return []
    tokens: List[str] = []
    for m in re.finditer(r"[A-Za-z0-9]{2,}", text):
        tokens.append(m.group(0).lower())
    for ch in re.findall(r"[一-鿿]", text):
        tokens.append(ch)
    return tokens


async def _load_questions(force: bool = False) -> List[dict]:
    """从题库表加载全部题目（含关键词检索与元数据过滤所需字段），带内存缓存。

    命中缓存条件：缓存非空、非强制刷新、且距上次加载未超过 _CACHE_TTL。
    加载失败时返回空列表且不更新缓存（保留旧缓存或下次重试）。
    """
    global _questions_cache, _cache_ts
    import time

    now = time.time()
    if _questions_cache is not None and not force and (now - _cache_ts) < _CACHE_TTL:
        return _questions_cache
    rows: List[dict] = []
    try:
        async with AsyncSessionLocal() as db:
            result = (await db.execute(select(QuestionBank))).scalars().all()
            for r in result:
                rows.append(
                    {
                        "id": str(r.id),
                        "question_content": r.question_content or "",
                        "question_type": r.question_type or "",
                        "difficulty": r.difficulty or "",
                        "category": r.category or "",
                        "industry": r.industry or "",
                        "position_tags": r.position_tags or [],
                        "model_answer": r.model_answer or "",
                        "evaluation_criteria": r.evaluation_criteria or [],
                        "frequency": r.frequency or 0,
                    }
                )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"加载题库失败: {e}")
        return []
    _questions_cache = rows
    _cache_ts = now
    return rows


def clear_questions_cache() -> None:
    """运行时题目变更后清空缓存，下次检索重新加载。"""
    global _questions_cache
    _questions_cache = None


def _bm25_search(rows: List[dict], query_text: str, top_n: int) -> Dict[str, float]:
    """对 (题干 + 分类 + 标签) 做 BM25 关键词召回，返回 {id: 归一化分数}。"""
    if not rows or not query_text:
        return {}
    docs: List[tuple] = []
    for r in rows:
        text = " ".join([r["question_content"], r["category"], " ".join(r["position_tags"])])
        docs.append((r["id"], _tokenize(text)))

    n = len(docs)
    df: Dict[str, int] = {}
    tf_list: List[Dict[str, int]] = []
    doc_len: List[int] = []
    total_len = 0
    for _, toks in docs:
        tf: Dict[str, int] = {}
        doc_len.append(len(toks))
        total_len += len(toks)
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        tf_list.append(tf)
    avg_dl = total_len / n if n else 1.0

    k1, b = 1.5, 0.75
    q_tokens = set(_tokenize(query_text))
    if not q_tokens:
        return {}
    scores: Dict[str, float] = {}
    for (doc_id, _), tfs, dl in zip(docs, tf_list, doc_len):
        score = 0.0
        for qt in q_tokens:
            if qt not in df:
                continue
            idf = math.log((n - df[qt] + 0.5) / (df[qt] + 0.5) + 1.0)
            f = tfs.get(qt, 0)
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (dl / avg_dl)))
        if score > 0:
            scores[doc_id] = score
    if scores:
        max_s = max(scores.values())
        if max_s > 0:
            scores = {k: v / max_s for k, v in scores.items()}
    return scores


def _rrf(rank_lists: List[List[str]], k: int = _RRF_K) -> Dict[str, float]:
    """Reciprocal Rank Fusion：把多个召回列表按排名融合为统一分数。"""
    fused: Dict[str, float] = {}
    for ranks in rank_lists:
        for i, doc_id in enumerate(ranks):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + i + 1)
    return fused


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cosine(a, b) -> float:
    """两向量的余弦相似度（纯 Python，避免引入 numpy 依赖）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _is_similar(content: str, asked: List[str], sem_threshold: float = 0.82, jac_threshold: float = 0.6) -> bool:
    """判断 content 是否与已问题目「语义或字面」重复。

    优先用语义向量（余弦相似度）捕获中文改写复述；当嵌入接口不可用（额度/网络）
    时自动降级为字符级 Jaccard，保证去重能力不丢失。
    """
    if not content or not asked:
        return False
    try:
        c_vec = await asyncio.to_thread(embed_query, content)
    except Exception:  # noqa: BLE001
        c_vec = None
    if c_vec:
        for old in asked:
            try:
                o_vec = await asyncio.to_thread(embed_query, old)
            except Exception:  # noqa: BLE001
                o_vec = None
            if o_vec and _cosine(c_vec, o_vec) > sem_threshold:
                return True
        return False
    # 降级：字符级 Jaccard
    a = set(_tokenize(content))
    return any(_jaccard(a, set(_tokenize(old))) > jac_threshold for old in asked)


def _metadata_bonus(row: dict, position_name: str, industry: str) -> float:
    """与应聘岗位/行业的匹配度加分（软过滤，无匹配时也不致召回为空）。"""
    bonus = 0.0
    pos = (position_name or "").lower()
    ind = (industry or "").lower()
    if pos:
        tags = [t.lower() for t in row["position_tags"]]
        if pos in tags or any(pos in t for t in tags):
            bonus += 1.0
        if pos in (row["category"] or "").lower():
            bonus += 0.5
    if ind and ind in (row["industry"] or "").lower():
        bonus += 0.5
    return bonus


async def hybrid_retrieve(
    position_name: str,
    interview_type: str,
    difficulty: str,
    industry: str = "",
    k: int = 3,
    context: str = "",
    exclude_questions: Optional[List[str]] = None,
) -> List[dict]:
    """混合召回核心：元数据软过滤 + 稠密向量 + BM25 → RRF 融合 → 多样性去重。

    返回选中的题目 dict 列表（已按推荐度排序）。任何关键步骤失败都优雅降级。
    """
    rows = await _load_questions()
    if not rows:
        return []

    exclude: Set[str] = {q.strip() for q in (exclude_questions or []) if q}

    # 1) 富化查询：岗位 + 行业 + 类型 + 简历关键词（截断，避免过长）
    query_parts = [x for x in [position_name, industry, interview_type] if x]
    if context:
        query_parts.append(context[:500])
    query_text = " ".join(query_parts)
    if not query_text.strip():
        return []

    # 2) 稠密召回（向量 top-N 候选）
    dense_ranks: List[str] = []
    try:
        q_vec = await asyncio.to_thread(embed_query, query_text)
        if q_vec:
            hits = await asyncio.to_thread(query_embeddings, COLLECTION, q_vec, _CANDIDATE_N)
            dense_ranks = [h.get("id") for h in hits if h.get("id")]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"稠密召回失败: {e}")

    # 3) 稀疏召回（BM25 关键词）
    sparse_scores = _bm25_search(rows, query_text, _CANDIDATE_N)
    sparse_ranks = [i for i, _ in sorted(sparse_scores.items(), key=lambda x: -x[1])][: _CANDIDATE_N]

    # 4) RRF 融合
    fused = _rrf([dense_ranks, sparse_ranks])

    # 5) 软过滤加分（岗位/行业匹配）
    for doc_id, score in fused.items():
        row = next((r for r in rows if r["id"] == doc_id), None)
        if row:
            fused[doc_id] = score + 0.01 * _metadata_bonus(row, position_name, industry)

    # 5.5) frequency 软加权：被使用次数越多的优质题，召回优先级略升（弱信号，不喧宾夺主）
    for doc_id, score in fused.items():
        row = next((r for r in rows if r["id"] == doc_id), None)
        if row:
            fused[doc_id] = score + 0.005 * (row.get("frequency") or 0)

    # 6) 按融合分排序
    ranked = [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])]

    # 7) 多样性去重 + 排除历史已问题目（保证不重复出题）
    selected: List[dict] = []
    selected_tokens: List[Set[str]] = []
    for doc_id in ranked:
        row = next((r for r in rows if r["id"] == doc_id), None)
        if not row:
            continue
        content = row["question_content"]
        toks = set(_tokenize(content))
        # 与历史已问题目高度相似 → 跳过
        if any(_jaccard(toks, set(_tokenize(eq))) > _SIMILARITY_JACCARD for eq in exclude):
            continue
        # 与已选题目过于相似 → 跳过（去重）
        if any(_jaccard(toks, st) > _SIMILARITY_JACCARD for st in selected_tokens):
            continue
        selected.append(row)
        selected_tokens.append(toks)
        if len(selected) >= k:
            break
    return selected


async def retrieve_question_references(
    position_name: str,
    interview_type: str,
    difficulty: str,
    industry: str = "",
    k: int = 3,
    context: str = "",
    exclude_questions: Optional[List[str]] = None,
) -> str:
    """返回格式化参考题库文本（供面试官参考/选用）；任何失败返回空字符串。"""
    try:
        selected = await hybrid_retrieve(
            position_name=position_name,
            interview_type=interview_type,
            difficulty=difficulty,
            industry=industry,
            k=k,
            context=context,
            exclude_questions=exclude_questions,
        )
        if not selected:
            return ""
        lines = ["匹配到的参考题库（供参考或直接选用，避免与之前问过的完全相同）："]
        for i, r in enumerate(selected, 1):
            lines.append(
                f"{i}. [{r.get('difficulty', '')}|{r.get('question_type', '')}] {r.get('question_content', '')}"
            )
        logger.info(f"题库混合检索命中 {len(selected)} 条（query={position_name!r}）")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"题库检索失败: {e}")
        return ""


async def retrieve_rubric_by_question(question_text: str, top: int = 1) -> str:
    """根据被问到的问题，从题库语义召回最相近题目的参考答案与评分标准，作为评估 rubric。"""
    if not question_text:
        return ""
    try:
        q_vec = await asyncio.to_thread(embed_query, question_text)
        if not q_vec:
            return ""
        hits = await asyncio.to_thread(query_embeddings, COLLECTION, q_vec, max(3, top))
        if not hits:
            return ""
        rows = await _load_questions()
        by_id = {r["id"]: r for r in rows}
        rubric_parts: List[str] = []
        for h in hits[:top]:
            row = by_id.get(h.get("id"))
            if not row:
                continue
            ec = row.get("evaluation_criteria") or []
            ec_text = "；".join(ec) if isinstance(ec, list) else str(ec)
            part = []
            if row.get("model_answer"):
                part.append(f"参考答案：{row['model_answer']}")
            if ec_text:
                part.append(f"评分要点：{ec_text}")
            if part:
                rubric_parts.append("｜".join(part))
        return "\n".join(rubric_parts)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"评分依据检索失败: {e}")
        return ""


async def record_question_used(content: str) -> None:
    """出题时累计题库题目的使用频次（frequency）。

    最佳匹配：题干文本完全一致（前端出题内容往往取自题库参考题）。
    与具体某场面试解耦——frequency 仅反映「该题被用过多少次」，作为召回软加权信号。
    任何失败都静默忽略，不影响主流程。
    """
    if not content or not content.strip():
        return
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(QuestionBank).where(QuestionBank.question_content == content.strip()).limit(1)
                )
            ).scalar_one_or_none()
            if row is not None:
                row.frequency = (row.frequency or 0) + 1
                await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"累计题目使用频次失败（忽略）: {e}")
