"""
Hybrid Retrieval Service — Adaptive Dense + Sparse (NO HyDE).

Pipeline per query:
  1. Classify query intent  → determines adaptive K values
  2. Dense search (Qdrant)  → semantic similarity via embeddings
  3. Sparse search (Postgres FTS / BM25-approx) → keyword / exact-match
  4. RRF Fusion             → merge ranked lists
  5. Cross-encoder Reranking → BAAI/bge-reranker-v2-m3
  6. Adaptive top-k cutoff  → cuts at first significant score gap

Query Intent → K Strategy
  - factual / lookup  : tight K (dense=15, sparse=15) — precision over recall
  - analytical        : wide K  (dense=40, sparse=40) — need more context
  - listing / enum    : wide K  (dense=40, sparse=30) — enumerate all items
  - conversational    : medium K (dense=20, sparse=20) — balanced
  - default           : medium K (dense=25, sparse=25)
"""

import asyncio
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from sqlalchemy import create_engine, text as sa_text
from qdrant_client.models import Filter, FieldCondition, MatchValue

from core.clients import qdrant_client, QDRANT_COLLECTION
from core.config import get_settings
from services.embedding import embed_query


# ── Constants ────────────────────────────────────────────────────────────────

RRF_K        = 60   # Standard RRF constant
RERANK_TOP_K = 50   # Max candidates fed to the cross-encoder
FINAL_TOP_K  = 8    # Hard cap on returned chunks

# Postgres text-search config names per ISO 639-1 language code.
_PG_TS_CONFIG: dict[str, str] = {
    "en": "english",
    "ar": "arabic",
    "hi": "simple",
    "de": "german",
    "fr": "french",
    "es": "spanish",
}


# ── CRITICAL-2 FIX: Module-level singleton sync engine ───────────────────────

@lru_cache(maxsize=1)
def _get_sync_engine():
    settings = get_settings()
    return create_engine(
        settings.DATABASE_URL_SYNC,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    chunk_id:        str
    document_id:     str
    text:            str
    context_summary: str
    section:         str
    page:            int
    language:        str
    score:           float


# ── Adaptive K Strategy ───────────────────────────────────────────────────────

@dataclass
class KStrategy:
    dense_k:  int
    sparse_k: int
    label:    str


def _classify_query(query: str) -> KStrategy:
    """
    Classify query intent and return adaptive K values.

    Rules are simple regex heuristics — fast, zero LLM calls.
    Fallback to 'default' if nothing matches.
    """
    q = query.lower().strip()
    words = len(q.split())

    # ── Listing / Enumeration queries ────────────────────────────────────────
    # "list all", "what are all the", "mention all", "give me all X", "enumerate"
    listing_patterns = [
        r"\b(list|enumerate|mention|name|give me|show me)\s+(all|every|each)\b",
        r"\ball\s+(the\s+)?\w+(s)?\b",       # "all the clauses", "all penalties"
        r"\bhow many\b",
        r"\b\d+\s+(courses?|programs?|items?|points?|clauses?|sections?)\b",
        r"\bwhat are (the|all)\b",
    ]
    if any(re.search(p, q) for p in listing_patterns):
        print(f"   🎯 Query intent: LISTING → dense=40, sparse=30")
        return KStrategy(dense_k=40, sparse_k=30, label="listing")

    # ── Analytical / Comparative queries ─────────────────────────────────────
    # "compare", "analyze", "explain", "summarize", "what is the difference"
    analytical_patterns = [
        r"\b(analyz|compar|evaluat|assess|review|summariz|explain|describe|discuss)\b",
        r"\b(difference|distinction|contrast|versus|vs\.?)\b",
        r"\b(risk|liability|obligation|duty|requirement)\b",
        r"\bwhat (does|do|is|are) .{10,}\?",  # longer analytical questions
    ]
    if any(re.search(p, q) for p in analytical_patterns) or words > 15:
        print(f"   🎯 Query intent: ANALYTICAL → dense=40, sparse=40")
        return KStrategy(dense_k=40, sparse_k=40, label="analytical")

    # ── Factual / Lookup queries ──────────────────────────────────────────────
    # Short, specific — page numbers, dates, amounts, names
    factual_patterns = [
        r"\bwhat is (the )?(date|amount|price|cost|page|section|clause|article|number)\b",
        r"\bwhen (is|was|will)\b",
        r"\bwho (is|are|was|were)\b",
        r"\bpage \d+\b",
        r"\bsection \d+\b",
        r"\barticle \d+\b",
        r"^\s*\d+\s*$",  # just a number
    ]
    if any(re.search(p, q) for p in factual_patterns) or words <= 5:
        print(f"   🎯 Query intent: FACTUAL → dense=15, sparse=15")
        return KStrategy(dense_k=15, sparse_k=15, label="factual")

    # ── Conversational / Greeting ─────────────────────────────────────────────
    conversational_patterns = [
        r"^(hi|hello|hey|thanks|thank you|ok|okay|sure|great|good)\b",
        r"\bhow are you\b",
        r"\bwhat can you do\b",
        r"\bwho are you\b",
    ]
    if any(re.search(p, q) for p in conversational_patterns):
        print(f"   🎯 Query intent: CONVERSATIONAL → dense=10, sparse=10")
        return KStrategy(dense_k=10, sparse_k=10, label="conversational")

    # ── Default / Medium ─────────────────────────────────────────────────────
    print(f"   🎯 Query intent: DEFAULT → dense=25, sparse=25")
    return KStrategy(dense_k=25, sparse_k=25, label="default")


# ── Language Detection ────────────────────────────────────────────────────────

def _detect_pg_ts_config(query: str) -> str:
    """Detect query language and map to the correct Postgres FTS configuration."""
    try:
        from services.language import detect_language
        lang = detect_language(query)
        config = _PG_TS_CONFIG.get(lang, "simple")
        if lang not in ("en", "", "unknown"):
            print(f"   🌐 Query language: {lang!r} → ts_config={config!r}")
        return config
    except Exception:
        return "english"


# ── Dense Search ─────────────────────────────────────────────────────────────

def _dense_search_sync(
    query_vector: list[float],
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = 25,
) -> list[RetrievedChunk]:
    """Synchronous dense search — runs in executor."""
    must = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
    if document_id:
        must.append(FieldCondition(key="document_id", match=MatchValue(value=document_id)))

    response = qdrant_client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=query_vector,
        query_filter=Filter(must=must),
        limit=top_k,
        with_payload=True,
    )

    return [
        RetrievedChunk(
            chunk_id=str(r.id),
            document_id=r.payload.get("document_id", ""),
            text=r.payload.get("text", ""),
            context_summary=r.payload.get("context_summary", ""),
            section=r.payload.get("section", ""),
            page=r.payload.get("page", 0),
            language=r.payload.get("language", "en"),
            score=r.score,
        )
        for r in response.points
    ]


async def _dense_search(
    query_vector: list[float],
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = 25,
) -> list[RetrievedChunk]:
    """Async wrapper: runs Qdrant search in the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _dense_search_sync, query_vector, user_id, document_id, top_k
    )


# ── Sparse Search (Language-Aware BM25 via Postgres) ─────────────────────────

def _sparse_search_sync(
    query: str,
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = 25,
    pg_ts_config: str = "english",
) -> list[RetrievedChunk]:
    """
    Keyword-based BM25-approximated search using PostgreSQL ts_rank_cd.
    Uses the singleton engine — no per-request engine creation.
    """
    engine = _get_sync_engine()
    doc_filter = "AND c.document_id = :document_id" if document_id else ""

    sql = f"""
        SELECT
            c.id               AS chunk_id,
            c.document_id,
            c.text,
            c.context_summary,
            c.section,
            c.page,
            c.language,
            ts_rank_cd(
                to_tsvector(:ts_config, c.text),
                plainto_tsquery(:ts_config, :query),
                32
            ) AS bm25_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.user_id = :user_id
          {doc_filter}
          AND to_tsvector(:ts_config, c.text) @@ plainto_tsquery(:ts_config, :query)
        ORDER BY bm25_score DESC
        LIMIT :top_k
    """

    params: dict = {
        "query":     query,
        "user_id":   user_id,
        "top_k":     top_k,
        "ts_config": pg_ts_config,
    }
    if document_id:
        params["document_id"] = document_id

    with engine.connect() as conn:
        rows = conn.execute(sa_text(sql), params).fetchall()

    return [
        RetrievedChunk(
            chunk_id=str(row.chunk_id),
            document_id=str(row.document_id),
            text=row.text,
            context_summary=row.context_summary or "",
            section=row.section or "",
            page=row.page or 0,
            language=row.language or "en",
            score=float(row.bm25_score),
        )
        for row in rows
    ]


async def _sparse_search(
    query: str,
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = 25,
    pg_ts_config: str = "english",
) -> list[RetrievedChunk]:
    """Async wrapper: runs Postgres FTS in the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _sparse_search_sync, query, user_id, document_id, top_k, pg_ts_config
    )


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def _reciprocal_rank_fusion(
    *ranked_lists: list[RetrievedChunk],
    k: int = RRF_K,
) -> list[RetrievedChunk]:
    """Merge multiple ranked lists using RRF. Higher score = better."""
    scores:    dict[str, float]          = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list, start=1):
            cid = chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            chunk_map[cid] = chunk

    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    result = []
    for cid in sorted_ids:
        chunk = chunk_map[cid]
        chunk.score = scores[cid]
        result.append(chunk)
    return result


# ── Adaptive Top-K Cutoff ─────────────────────────────────────────────────────

def _adaptive_cutoff(
    chunks: list[RetrievedChunk],
    hard_limit: int,
    min_k: int = 3,
    drop_threshold: float = 0.50,
) -> list[RetrievedChunk]:
    """
    Cut the reranked list at the first position where the score drops by
    more than `drop_threshold` relative to the top score.

    Example: scores [0.92, 0.88, 0.40, 0.39] → cut at index 2.
    Always returns at least `min_k` chunks and at most `hard_limit` chunks.
    """
    if len(chunks) <= min_k:
        return chunks[:hard_limit]

    top_score = chunks[0].score
    if top_score <= 0:
        return chunks[:hard_limit]

    for i in range(min_k, min(len(chunks), hard_limit)):
        if chunks[i].score < top_score * (1 - drop_threshold):
            return chunks[:i]

    return chunks[:hard_limit]


# ── Reranking (async, off the event loop) ────────────────────────────────────

def _rerank_sync(
    query: str,
    chunks: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """Synchronous cross-encoder reranking — always called via run_in_executor."""
    from services.reranker import rerank_chunks
    return rerank_chunks(query, chunks, top_k=top_k)


async def _rerank_async(
    query: str,
    chunks: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """
    Runs the blocking cross-encoder predict() call in a thread-pool executor
    so it never stalls the FastAPI async event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _rerank_sync, query, chunks, top_k)


# ── Main Retriever ────────────────────────────────────────────────────────────

class HybridRetriever:
    """
    Fully async hybrid retriever. NO HyDE — raw query is embedded directly.

    Single-document flow:
      1. Classify query intent → adaptive dense_k / sparse_k
      2. Embed raw query (no LLM call)
      3. Dense search + Sparse search (concurrent)
      4. RRF fusion
      5. Cross-encoder reranking (async executor)
      6. Adaptive top-k cutoff

    Multi-document flow:
      Steps 3-4 run in parallel per document, then a single shared
      reranking pass over all pooled candidates.
    """

    async def search(
        self,
        query: str,
        user_id: str,
        document_id: Optional[str] = None,
        top_k: int = FINAL_TOP_K,
        rerank: bool = True,
    ) -> list[RetrievedChunk]:
        """Single-document (or global) search with adaptive K."""
        return await self._search_one(
            query=query,
            user_id=user_id,
            document_id=document_id,
            top_k=top_k,
            rerank=rerank,
        )

    async def search_many(
        self,
        query: str,
        user_id: str,
        document_ids: list[str],
        top_k: int = FINAL_TOP_K,
        rerank: bool = True,
    ) -> list[RetrievedChunk]:
        """
        Multi-document parallel retrieval with adaptive K.

        Runs dense+sparse+RRF for each document concurrently, pools all
        candidates, then runs ONE shared reranking pass for comparable scores.
        """
        if not document_ids:
            return await self._search_one(
                query=query, user_id=user_id, document_id=None,
                top_k=top_k, rerank=rerank,
            )

        # Classify once for all documents
        strategy = _classify_query(query)
        pg_ts_config = _detect_pg_ts_config(query)

        # Embed raw query — no HyDE, no extra LLM call
        loop = asyncio.get_event_loop()
        query_vector = await loop.run_in_executor(None, embed_query, query)

        # Fan out dense+sparse+RRF per document — all concurrent
        per_doc_tasks = [
            self._fetch_candidates(
                query, query_vector, user_id, doc_id, pg_ts_config, strategy
            )
            for doc_id in document_ids
        ]
        per_doc_candidates: list[list[RetrievedChunk]] = await asyncio.gather(*per_doc_tasks)

        # Pool and deduplicate
        all_candidates: list[RetrievedChunk] = []
        seen: set[str] = set()
        for candidates in per_doc_candidates:
            for c in candidates:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_candidates.append(c)

        if not all_candidates:
            return []

        # Single shared reranking pass
        if rerank and all_candidates:
            feed = all_candidates[:RERANK_TOP_K]
            print(f"⚡ Reranking {len(feed)} pooled candidates from {len(document_ids)} docs [{strategy.label}]")
            reranked = await _rerank_async(query, feed, top_k=min(RERANK_TOP_K, len(feed)))
        else:
            reranked = sorted(all_candidates, key=lambda c: c.score, reverse=True)

        final = _adaptive_cutoff(reranked, hard_limit=top_k)
        print(f"✅ Final: {len(final)} chunks from {len(document_ids)} documents")
        return final

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch_candidates(
        self,
        query: str,
        query_vector: list[float],
        user_id: str,
        document_id: Optional[str],
        pg_ts_config: str,
        strategy: KStrategy,
    ) -> list[RetrievedChunk]:
        """Run dense + sparse + RRF for one document."""
        dense_task  = _dense_search(query_vector, user_id, document_id, strategy.dense_k)
        sparse_task = _sparse_search(query, user_id, document_id, strategy.sparse_k, pg_ts_config)

        dense_results, sparse_results_or_err = await asyncio.gather(
            dense_task, sparse_task, return_exceptions=True
        )

        if isinstance(sparse_results_or_err, Exception):
            print(f"   ⚠️  Sparse search failed for doc {document_id}: {sparse_results_or_err}")
            sparse_results: list[RetrievedChunk] = []
        else:
            sparse_results = sparse_results_or_err

        if isinstance(dense_results, Exception):
            print(f"   ⚠️  Dense search failed for doc {document_id}: {dense_results}")
            dense_results = []

        fused = (
            _reciprocal_rank_fusion(dense_results, sparse_results)
            if sparse_results
            else dense_results
        )
        return fused[:RERANK_TOP_K]

    async def _search_one(
        self,
        query: str,
        user_id: str,
        document_id: Optional[str],
        top_k: int,
        rerank: bool,
    ) -> list[RetrievedChunk]:
        """Internal single-document/global search path."""
        strategy     = _classify_query(query)
        pg_ts_config = _detect_pg_ts_config(query)

        # Embed raw query directly — no HyDE
        loop = asyncio.get_event_loop()
        query_vector = await loop.run_in_executor(None, embed_query, query)

        candidates = await self._fetch_candidates(
            query, query_vector, user_id, document_id, pg_ts_config, strategy
        )

        if rerank and candidates:
            reranked = await _rerank_async(
                query, candidates, top_k=min(RERANK_TOP_K, len(candidates))
            )
        else:
            reranked = sorted(candidates, key=lambda c: c.score, reverse=True)

        return _adaptive_cutoff(reranked, hard_limit=top_k)
