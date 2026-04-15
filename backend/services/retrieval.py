"""
Hybrid Retrieval Service.

Pipeline:
  1. Dense search  — semantic similarity via multilingual-e5-large embeddings
  2. Sparse search — keyword matching via BM25 (rank_bm25 against Postgres text)
  3. RRF Fusion   — Reciprocal Rank Fusion to merge both ranked lists
  4. Reranking    — Cross-encoder reranker to select final top-k chunks

Usage:
    from services.retrieval import HybridRetriever
    results = HybridRetriever().search(query, user_id, document_id=None, top_k=5)
"""

from dataclasses import dataclass
from typing import Optional

from qdrant_client.models import Filter, FieldCondition, MatchValue

from core.clients import qdrant_client, QDRANT_COLLECTION
from services.embedding import embed_query

# ── Constants ────────────────────────────────────────────────────────────────

DENSE_TOP_K = 60       # Number of candidates from dense search
SPARSE_TOP_K = 60      # Number of candidates from sparse (BM25) search
RRF_K = 60             # Standard RRF constant (controls score smoothing)
RERANK_TOP_K = 100      # Chunks passed to the reranker
FINAL_TOP_K = 30        # Final returned chunks after reranking


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    text: str
    context_summary: str
    section: str
    page: int
    language: str
    score: float


# ── Dense Search ─────────────────────────────────────────────────────────────

def dense_search(
    query: str,
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = DENSE_TOP_K,
) -> list[RetrievedChunk]:
    """Semantic search: embed query → find nearest chunks in Qdrant."""
    query_vector = embed_query(query)

    # Build filters: always filter by user, optionally filter by document
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


# ── Sparse Search (BM25 via Postgres) ────────────────────────────────────────

def sparse_search(
    query: str,
    user_id: str,
    document_id: Optional[str] = None,
    top_k: int = SPARSE_TOP_K,
) -> list[RetrievedChunk]:
    """
    Keyword-based BM25 search.

    Uses PostgreSQL full-text search (ts_rank with plainto_tsquery) since
    we already store chunk text in Postgres. This avoids the need to
    add a separate Elasticsearch service.
    """
    from sqlalchemy import create_engine, text as sa_text
    from core.config import get_settings

    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL_SYNC)

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
            c.qdrant_point_id,
            ts_rank(
                to_tsvector('english', c.text),
                plainto_tsquery('english', :query)
            ) AS bm25_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.user_id = :user_id
          {doc_filter}
          AND to_tsvector('english', c.text) @@ plainto_tsquery('english', :query)
        ORDER BY bm25_score DESC
        LIMIT :top_k
    """

    params = {"query": query, "user_id": user_id, "top_k": top_k}
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


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def reciprocal_rank_fusion(
    *ranked_lists: list[RetrievedChunk],
    k: int = RRF_K,
) -> list[RetrievedChunk]:
    """
    Merge multiple ranked lists into one using RRF.

    RRF score = sum(1 / (k + rank_i)) for each retrieval source.
    Higher score = better. Chunks appearing in both sources score much higher.
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list, start=1):
            cid = chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            chunk_map[cid] = chunk  # keep latest reference

    # Sort by fused score descending
    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    result = []
    for cid in sorted_ids:
        chunk = chunk_map[cid]
        chunk.score = scores[cid]
        result.append(chunk)

    return result


# ── Main Retriever ────────────────────────────────────────────────────────────

class HybridRetriever:
    """
    High-level retrieval interface.

    1. Dense search  → top 60 semantic matches
    2. Sparse search → top 60 keyword matches
    3. RRF            → merged + ranked top 100
    4. Reranker       → final top 30
    """

    def search(
        self,
        query: str,
        user_id: str,
        document_id: Optional[str] = None,
        top_k: int = FINAL_TOP_K,
        rerank: bool = True,
    ) -> list[RetrievedChunk]:

        print(f"🔍 Dense search for: {query[:80]}...")
        dense_results = dense_search(query, user_id, document_id, DENSE_TOP_K)
        print(f"   └─ Dense: {len(dense_results)} candidates")

        print(f"🔍 Sparse (BM25) search...")
        try:
            sparse_results = sparse_search(query, user_id, document_id, SPARSE_TOP_K)
            print(f"   └─ Sparse: {len(sparse_results)} candidates")
        except Exception as e:
            print(f"   ⚠️  Sparse search failed (using dense only): {e}")
            sparse_results = []

        # RRF fusion
        if sparse_results:
            fused = reciprocal_rank_fusion(dense_results, sparse_results)
        else:
            fused = dense_results

        candidates = fused[:RERANK_TOP_K]
        print(f"📊 RRF: {len(candidates)} candidates after fusion")

        # Reranking
        if rerank and candidates:
            from services.reranker import rerank_chunks
            candidates = rerank_chunks(query, candidates, top_k=top_k)
            print(f"⚡ Reranked → top {len(candidates)}")
        else:
            candidates = candidates[:top_k]

        return candidates
