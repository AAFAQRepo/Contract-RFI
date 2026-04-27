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

DENSE_TOP_K = 30       # Number of candidates from dense search
SPARSE_TOP_K = 30      # Number of candidates from sparse (BM25) search
RRF_K = 60             # Standard RRF constant
RERANK_TOP_K = 50      # Chunks passed to the reranker
FINAL_TOP_K = 40        # Default maximum chunks (increased for flexibility)


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str  # Added for better citations
    text: str
    context_summary: str
    section: str
    page: int
    language: str
    score: float
    chunk_index: Optional[int] = None # For neighbor expansion sorting


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

    # Fetch filenames from Postgres for these document IDs
    doc_ids_raw = list(set(r.payload.get("document_id") for r in response.points if r.payload.get("document_id")))
    filenames = {}
    if doc_ids_raw:
        import uuid as _uuid
        from sqlalchemy import create_engine, text as sa_text
        from core.config import get_settings
        settings = get_settings()
        engine = create_engine(settings.DATABASE_URL_SYNC)
        
        # Convert strings to UUID objects to avoid Postgres type mismatch
        doc_uuids = [_uuid.UUID(did) for did in doc_ids_raw]
        
        with engine.connect() as conn:
            res = conn.execute(
                sa_text("SELECT id, filename FROM documents WHERE id = ANY(:ids)"), 
                {"ids": doc_uuids}
            )
            filenames = {str(row[0]): row[1] for row in res.fetchall()}

    return [
        RetrievedChunk(
            chunk_id=str(r.id),
            document_id=r.payload.get("document_id", ""),
            filename=filenames.get(r.payload.get("document_id", ""), "Unknown Document"),
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
            d.filename,
            c.text,
            c.context_summary,
            c.section,
            c.page,
            c.language,
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
            filename=row.filename,
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

    1. Dense search  → top 30 semantic matches
    2. Sparse search → top 30 keyword matches
    3. RRF            → merged + ranked top 50
    4. Reranker       → final top 5
    """

    def search(
        self,
        query: str,
        user_id: str,
        document_id: Optional[str] = None,
        top_k: int = FINAL_TOP_K,
        rerank: bool = True,
        rerank_threshold: Optional[float] = -4.0,
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
            candidates = rerank_chunks(query, candidates, top_k=top_k, threshold=rerank_threshold)
            print(f"⚡ Reranked → top {len(candidates)}")
        else:
            candidates = candidates[:top_k]

        return candidates

    def expand_with_neighbors(self, chunks: list[RetrievedChunk], n: int) -> list[RetrievedChunk]:
        """Fetch neighboring chunks for each seed chunk to provide continuity."""
        from sqlalchemy import create_engine, text as sa_text
        from core.config import get_settings
        settings = get_settings()
        engine = create_engine(settings.DATABASE_URL_SYNC)

        # 1. Identify all target chunk indices
        # We need chunk_index from the DB for these chunks.
        # Currently RetrievedChunk doesn't have chunk_index. Let's fetch it first.
        chunk_ids = [c.chunk_id for c in chunks]
        
        expanded_chunks_map = {c.chunk_id: c for c in chunks}
        
        with engine.connect() as conn:
            # Get current indices
            res = conn.execute(
                sa_text("SELECT id, document_id, chunk_index FROM chunks WHERE id = ANY(:ids)"),
                {"ids": [str(cid) for cid in chunk_ids]}
            )
            seeds = res.fetchall()
            
            # Map chunk_id to index for sorting seeds later
            idx_map = {str(row[0]): row[2] for row in seeds}
            for c in chunks:
                c.chunk_index = idx_map.get(c.chunk_id)

            neighbor_queries = []
            for row in seeds:
                cid, doc_id, idx = row
                if idx is None: continue
                # Define neighbor range
                for i in range(1, n + 1):
                    neighbor_queries.append((str(doc_id), idx - i))
                    neighbor_queries.append((str(doc_id), idx + i))
            
            if not neighbor_queries:
                return chunks

            unique_doc_ids = list(set(q[0] for q in neighbor_queries))
            neighbor_indices = [q[1] for q in neighbor_queries]
            
            res = conn.execute(
                sa_text("""
                    SELECT 
                        c.id, c.document_id, d.filename, c.text, 
                        c.context_summary, c.section, c.page, c.language, c.chunk_index
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.document_id = ANY(:doc_ids) 
                      AND c.chunk_index = ANY(:indices)
                """),
                {"doc_ids": unique_doc_ids, "indices": neighbor_indices}
            )
            
            for row in res.fetchall():
                rid = str(row[0])
                if rid not in expanded_chunks_map:
                    expanded_chunks_map[rid] = RetrievedChunk(
                        chunk_id=rid,
                        document_id=str(row[1]),
                        filename=row[2],
                        text=row[3],
                        context_summary=row[4],
                        section=row[5],
                        page=row[6],
                        language=row[7],
                        score=0.0,
                        chunk_index=row[8]
                    )

        # Final sorting by document + chunk_index to ensure continuity
        result = list(expanded_chunks_map.values())
        result.sort(key=lambda x: (x.document_id, x.chunk_index or 0))
        
        # Deduplication by text content (sometimes adjacent chunks overlap or repeat)
        seen_text = set()
        deduped = []
        for c in result:
            txt_norm = c.text.strip()
            if txt_norm and txt_norm not in seen_text:
                deduped.append(c)
                seen_text.add(txt_norm)
        
        return deduped
