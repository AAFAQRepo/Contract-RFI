"""
Hybrid Retrieval Service.

Pipeline:
  1. [Optional] HyDE — generate a hypothetical clause to close the
     conversational↔formal-legal semantic gap before embedding.
  2. Dense search  — semantic similarity via gte-multilingual-base embeddings
  3. Sparse search — language-aware PostgreSQL FTS (BM25-approximated via ts_rank_cd)
  4. RRF Fusion   — Reciprocal Rank Fusion to merge both ranked lists
  5. Reranking    — Cross-encoder reranker (BAAI/bge-reranker-v2-m3, max_length=1024)
  6. Adaptive top-k — cuts at the first significant score gap rather than a hard limit

Fixes applied (from audit):
  CRITICAL-1  — rerank_chunks() is called inside run_in_executor; never blocks the event loop.
  CRITICAL-2  — Module-level singleton SQLAlchemy engine (no more per-request engine creation).
  CRITICAL-3  — HybridRetriever.search() is now async; multi-doc fan-out uses asyncio.gather
                 + a single shared reranking pass.
  CRITICAL-7  — Sparse search language-aware: detects query language and sets the correct
                 PostgreSQL text-search configuration (english / arabic / hindi).
  R-1         — Adaptive top-k: cuts the ranked list at the first score drop > 50 %.
  R-2         — FINAL_TOP_K reduced to 8 (prevents 20×600-token context window overflow).
  R-3         — Cross-encoder max_length bumped to 1024 (see reranker.py).
  R-4         — HyDE optional: generates a hypothetical contract clause before embedding.
"""

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from sqlalchemy import create_engine, text as sa_text
from qdrant_client.models import Filter, FieldCondition, MatchValue

from core.clients import qdrant_client, QDRANT_COLLECTION
from core.config import get_settings
from services.embedding import embed_query

# ── Constants ────────────────────────────────────────────────────────────────

DENSE_TOP_K  = 30   # Candidates from dense search
SPARSE_TOP_K = 30   # Candidates from sparse (BM25-approx) search
RRF_K        = 60   # Standard RRF constant
RERANK_TOP_K = 50   # Candidates fed to the cross-encoder
FINAL_TOP_K  = 8    # Final chunks returned (down from 20 → fits 8B context window)

# HyDE: generate a hypothetical clause to bridge the conversational→legal gap.
# Disable if you want to skip the extra LLM call on every query.
HYDE_ENABLED = True

# Postgres text-search config names per ISO 639-1 language code.
# Falls back to 'simple' for unsupported languages (avoids zero-result errors).
_PG_TS_CONFIG: dict[str, str] = {
    "en":  "english",
    "ar":  "arabic",
    "hi":  "simple",   # PostgreSQL has no Hindi config; 'simple' = no stemming
    "de":  "german",
    "fr":  "french",
    "es":  "spanish",
}

# ── CRITICAL-2 FIX: Module-level singleton sync engine ───────────────────────

@lru_cache(maxsize=1)
def _get_sync_engine():
    """
    Return (and cache) the single synchronous SQLAlchemy engine used by
    sparse_search.  Called once; subsequent calls return the cached object.
    Previously this engine was created on every request — a severe bug.
    """
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


# ── HyDE — Hypothetical Document Embedding (R-4) ─────────────────────────────

async def _hyde_embed(query: str) -> list[float]:
    """
    Generate a hypothetical contract clause that would answer `query`, then
    embed that clause instead of the raw query.

    This closes the semantic gap between conversational language
    ("what are the penalties for late delivery?") and formal legal text
    ("The Contractor shall pay liquidated damages of 0.5% per calendar week…").

    Falls back to embedding the raw query if the LLM call fails.
    """
    try:
        from openai import AsyncOpenAI
        settings = get_settings()
        client = AsyncOpenAI(
            base_url=settings.SGLANG_BASE_URL,
            api_key=settings.SGLANG_API_KEY,
        )
        resp = await client.chat.completions.create(
            model=settings.SGLANG_INTENT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a contract drafting assistant. "
                        "Given a question about a contract, write a single short "
                        "contract clause (2-4 sentences) that would answer the question. "
                        "Use formal legal language. Output only the clause text."
                    ),
                },
                {"role": "user", "content": query},
            ],
            max_tokens=150,
            temperature=0.1,
        )
        hypothetical_clause = resp.choices[0].message.content or query
    except Exception as exc:
        print(f"⚠️  HyDE LLM call failed ({exc}); falling back to raw query embedding.")
        hypothetical_clause = query

    return embed_query(hypothetical_clause)


# ── Dense Search ─────────────────────────────────────────────────────────────

def _dense_search_sync(
    query_vector: list[float],
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = DENSE_TOP_K,
) -> list[RetrievedChunk]:
    """Synchronous dense search — runs in executor (see dense_search)."""
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


async def dense_search(
    query_vector: list[float],
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = DENSE_TOP_K,
) -> list[RetrievedChunk]:
    """Async wrapper: runs Qdrant search in the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _dense_search_sync,
        query_vector,
        user_id,
        document_id,
        top_k,
    )


# ── Sparse Search (Language-Aware BM25 via Postgres) ─────────────────────────

def _sparse_search_sync(
    query: str,
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = SPARSE_TOP_K,
    pg_ts_config: str = "english",
) -> list[RetrievedChunk]:
    """
    Keyword-based BM25-approximated search using PostgreSQL ts_rank_cd.

    CRITICAL-2 FIX: Uses the module-level singleton engine — no more per-request
    engine creation.

    CRITICAL-7 FIX: `pg_ts_config` is set by the caller based on detected query
    language, so Arabic/Hindi queries no longer map to the English lexicon.
    """
    engine = _get_sync_engine()

    doc_filter = "AND c.document_id = :document_id" if document_id else ""

    # ts_rank_cd includes document coverage (normalization=32) for better length balance.
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


async def sparse_search(
    query: str,
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = SPARSE_TOP_K,
    pg_ts_config: str = "english",
) -> list[RetrievedChunk]:
    """Async wrapper: runs Postgres FTS in the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sparse_search_sync,
        query,
        user_id,
        document_id,
        top_k,
        pg_ts_config,
    )


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def reciprocal_rank_fusion(
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


# ── Adaptive Top-K (R-1) ─────────────────────────────────────────────────────

def _adaptive_cutoff(
    chunks: list[RetrievedChunk],
    hard_limit: int,
    min_k: int = 3,
    drop_threshold: float = 0.50,
) -> list[RetrievedChunk]:
    """
    Cut the reranked list at the first position where the score drops by more
    than `drop_threshold` relative to the top score.  This avoids returning
    marginally-relevant chunks that hurt answer quality.

    Example: scores [0.92, 0.88, 0.85, 0.40, 0.39] → cut at index 3.
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
    CRITICAL-1 FIX: Runs the blocking cross-encoder predict() call in a thread
    pool executor so it never stalls the FastAPI async event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _rerank_sync, query, chunks, top_k)


# ── Main Retriever ────────────────────────────────────────────────────────────

class HybridRetriever:
    """
    Fully async high-level retrieval interface.

    Single-document flow:
      1. [HyDE]  Generate hypothetical clause → embed
      2. Dense   → top 30 semantic matches
      3. Sparse  → top 30 keyword matches  (language-aware)
      4. RRF     → merged top 50
      5. Rerank  → cross-encoder (async, executor)
      6. Adaptive cutoff → final 3-8 chunks

    Multi-document flow  (CRITICAL-3 FIX):
      All per-document dense+sparse+RRF steps run in PARALLEL via asyncio.gather.
      All candidates are pooled and passed through ONE shared reranking pass,
      producing comparable scores across documents.
    """

    async def search(
        self,
        query: str,
        user_id: str,
        document_id: Optional[str] = None,
        top_k: int = FINAL_TOP_K,
        rerank: bool = True,
        use_hyde: bool = HYDE_ENABLED,
    ) -> list[RetrievedChunk]:
        """Single-document (or global) search."""
        return await self._search_one(
            query=query,
            user_id=user_id,
            document_id=document_id,
            top_k=top_k,
            rerank=rerank,
            use_hyde=use_hyde,
        )

    async def search_many(
        self,
        query: str,
        user_id: str,
        document_ids: list[str],
        top_k: int = FINAL_TOP_K,
        rerank: bool = True,
        use_hyde: bool = HYDE_ENABLED,
    ) -> list[RetrievedChunk]:
        """
        CRITICAL-3 FIX: Multi-document parallel retrieval.

        Runs dense+sparse+RRF for each document concurrently, pools all
        candidates, then runs a SINGLE shared reranking pass so scores
        are comparable across documents.
        """
        if not document_ids:
            # Global search — no document filter
            return await self._search_one(
                query=query,
                user_id=user_id,
                document_id=None,
                top_k=top_k,
                rerank=rerank,
                use_hyde=use_hyde,
            )

        # Step 1: Compute query vector once (with optional HyDE)
        query_vector = await self._get_query_vector(query, use_hyde)

        # Step 2: Detect query language once
        pg_ts_config = self._detect_pg_ts_config(query)

        # Step 3: Fan out dense+sparse+RRF PER document — all concurrent
        per_doc_tasks = [
            self._fetch_candidates(query, query_vector, user_id, doc_id, pg_ts_config)
            for doc_id in document_ids
        ]
        per_doc_candidates: list[list[RetrievedChunk]] = await asyncio.gather(*per_doc_tasks)

        # Step 4: Pool all candidates from all documents
        all_candidates: list[RetrievedChunk] = []
        for candidates in per_doc_candidates:
            all_candidates.extend(candidates)

        if not all_candidates:
            return []

        # Deduplicate by chunk_id (a chunk cannot appear twice)
        seen: set[str] = set()
        unique_candidates: list[RetrievedChunk] = []
        for c in all_candidates:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                unique_candidates.append(c)

        # Step 5: Single shared reranking pass (async, executor)
        if rerank and unique_candidates:
            rerank_candidates = unique_candidates[:RERANK_TOP_K]
            print(f"⚡ Reranking {len(rerank_candidates)} pooled candidates from {len(document_ids)} docs")
            reranked = await _rerank_async(query, rerank_candidates, top_k=min(RERANK_TOP_K, len(rerank_candidates)))
        else:
            reranked = sorted(unique_candidates, key=lambda c: c.score, reverse=True)

        # Step 6: Adaptive cutoff
        final = _adaptive_cutoff(reranked, hard_limit=top_k)
        print(f"✅ Final: {len(final)} chunks from {len(document_ids)} documents")
        return final

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_query_vector(self, query: str, use_hyde: bool) -> list[float]:
        """Embed query (with or without HyDE)."""
        if use_hyde:
            print("🧪 HyDE: generating hypothetical clause...")
            vector = await _hyde_embed(query)
            print("   └─ HyDE embedding done")
        else:
            loop = asyncio.get_event_loop()
            vector = await loop.run_in_executor(None, embed_query, query)
        return vector

    def _detect_pg_ts_config(self, query: str) -> str:
        """
        CRITICAL-7 FIX: Detect query language and map to the correct Postgres
        text-search configuration.  Prevents Arabic/Hindi queries from silently
        returning zero rows due to English lexicon mismatch.
        """
        try:
            from services.language import detect_language
            lang = detect_language(query)
            config = _PG_TS_CONFIG.get(lang, "simple")
            if lang not in ("en", ""):
                print(f"   🌐 Query language detected: {lang!r} → ts_config={config!r}")
            return config
        except Exception:
            return "english"

    async def _fetch_candidates(
        self,
        query: str,
        query_vector: list[float],
        user_id: str,
        document_id: Optional[str],
        pg_ts_config: str,
    ) -> list[RetrievedChunk]:
        """Run dense + sparse + RRF for one document. Runs concurrently with peers."""
        dense_task  = dense_search(query_vector, user_id, document_id, DENSE_TOP_K)
        sparse_task = sparse_search(query, user_id, document_id, SPARSE_TOP_K, pg_ts_config)

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
            reciprocal_rank_fusion(dense_results, sparse_results)
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
        use_hyde: bool,
    ) -> list[RetrievedChunk]:
        """Internal single-document/global search path."""
        query_vector = await self._get_query_vector(query, use_hyde)
        pg_ts_config = self._detect_pg_ts_config(query)

        candidates = await self._fetch_candidates(
            query, query_vector, user_id, document_id, pg_ts_config
        )

        if rerank and candidates:
            reranked = await _rerank_async(query, candidates, top_k=min(RERANK_TOP_K, len(candidates)))
        else:
            reranked = sorted(candidates, key=lambda c: c.score, reverse=True)

        return _adaptive_cutoff(reranked, hard_limit=top_k)
