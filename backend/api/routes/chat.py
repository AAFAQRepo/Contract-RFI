from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth import get_current_user
from models.models import User
from services.retrieval import HybridRetriever, RetrievedChunk
from services.llm import LLMService

router = APIRouter()
retriever = HybridRetriever()
llm_service = LLMService()

# ── Models ──────────────────────────────────────────────────────────────────

class ChatQuery(BaseModel):
    query: str
    document_id: Optional[str] = None  # Optional: limit search to specific doc

class SourceChunk(BaseModel):
    document_id: str
    page: int
    text: str

class ChatResponse(BaseModel):
    answer: str
    thinking: str
    sources: List[SourceChunk]

# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/message", response_model=ChatResponse)
async def chat_message(
    payload: ChatQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Main RAG Chat Entry Point.
    1. Retrieve context chunks (Hybrid: Semantic + Keyword)
    2. Rerank to find top 5
    3. Call LLM (Llama 3.1) with context
    4. Return structured response
    """
    try:
        # 1. Retrieve Context
        chunks: List[RetrievedChunk] = retriever.search(
            query=payload.query,
            user_id=str(current_user.id),
            document_id=payload.document_id,
            top_k=5
        )

        if not chunks:
            return ChatResponse(
                answer="I couldn't find any relevant information in your uploaded documents to answer this question.",
                thinking="No relevant chunks found in Qdrant/Postgres for the current query.",
                sources=[]
            )

        # 2. Generate LLM Response
        # We use the non-streaming version initially for the UI's thinking/answer structure
        llm_result = await llm_service.generate_thought_and_answer(
            query=payload.query,
            chunks=chunks
        )

        # 3. Format sources for frontend
        sources = [
            SourceChunk(
                document_id=c.document_id,
                page=c.page,
                text=c.text[:200] + "..." # Snippet
            )
            for c in chunks
        ]

        return ChatResponse(
            answer=llm_result["answer"],
            thinking=llm_result["thinking"] or "Analyzing document context...",
            sources=sources
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG Pipeline Error: {str(e)}")

@router.get("/history")
async def chat_history(
    document_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get chat history (Metadata only for now)."""
    # Phase 1E: Database-backed history retrieval
    return {"history": [], "message": "History storage coming in Phase 1E"}
