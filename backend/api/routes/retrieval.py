"""
Retrieval API routes.

POST /retrieval/search  — Run the full hybrid retrieval for a query.
                          Used for testing the RAG pipeline before
                          wiring it into the chat flow.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.auth import get_current_user
from models.models import User
from services.retrieval import HybridRetriever

router = APIRouter(prefix="/retrieval", tags=["Retrieval"])


# ── Request / Response schemas ────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    document_id: Optional[str] = None
    top_k: int = 5
    rerank: bool = True


class ChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    context_summary: str
    section: str
    page: int
    language: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[ChunkResult]
    total: int


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/search", response_model=SearchResponse)
def search(
    req: SearchRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run the hybrid retrieval pipeline.

    Steps:
      1. Dense semantic search (Qdrant embeddings)
      2. Sparse keyword search (Postgres full-text BM25)
      3. Reciprocal Rank Fusion (RRF)
      4. Cross-encoder reranking (bge-reranker-v2-m3)

    Returns top-k most relevant chunks for the given query.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    retriever = HybridRetriever()
    results = retriever.search(
        query=req.query,
        user_id=str(current_user.id),
        document_id=req.document_id,
        top_k=req.top_k,
        rerank=req.rerank,
    )

    return SearchResponse(
        query=req.query,
        results=[
            ChunkResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                text=r.text,
                context_summary=r.context_summary,
                section=r.section,
                page=r.page,
                language=r.language,
                score=r.score,
            )
            for r in results
        ],
        total=len(results),
    )
