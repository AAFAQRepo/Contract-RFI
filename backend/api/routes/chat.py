import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth import get_current_user
from models.models import User, Chat
from services.retrieval import HybridRetriever, RetrievedChunk
from services.llm import LLMService

router = APIRouter()
retriever = HybridRetriever()
llm_service = LLMService()

# ── Models ──────────────────────────────────────────────────────────────────

class ChatQuery(BaseModel):
    query: str
    document_id: Optional[str] = None

class SourceChunk(BaseModel):
    document_id: str
    page: int
    text: str

class ChatResponse(BaseModel):
    id: str
    answer: str
    thinking: str
    sources: List[SourceChunk]
    created_at: str

# ── Endpoints ───────────────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse
import json
import asyncio

@router.post("/message")
async def chat_message(
    payload: ChatQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Main RAG Chat Entry Point with Streaming & Persistence.
    """
    start_time = time.time()
    
    # 1. Retrieve Context (Sync/Async retrieval)
    chunks: List[RetrievedChunk] = []
    if payload.document_id:
        chunks = retriever.search(
            query=payload.query,
            user_id=str(current_user.id),
            document_id=payload.document_id,
            top_k=5
        )

    # 2. Generator for Streaming
    async def event_generator():
        full_answer = ""
        thinking = ""
        in_thinking = False
        
        # We start by notifying the UI we are beginning
        # (The thinking block logic actually happens in the model stream)
        
        async for token in llm_service.generate_response_stream(
            query=payload.query,
            chunks=chunks,
            user_name=current_user.name or "User"
        ):
            full_answer += token
            
            # Detect <thinking> tags to help UI
            if "<thinking>" in token: in_thinking = True
            if "</thinking>" in token: in_thinking = False
            
            # Yield token as a simple string or JSON
            # We'll use a simple "type:token" format or just the token
            yield token

        # 3. Final Persistence (Done after stream finishes)
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Parse final result for DB
        final_thinking = ""
        final_answer = full_answer
        if "<thinking>" in full_answer and "</thinking>" in full_answer:
            parts = full_answer.split("</thinking>", 1)
            final_thinking = parts[0].replace("<thinking>", "").strip()
            final_answer = parts[1].strip()

        # Save to DB
        new_chat = Chat(
            user_id=current_user.id,
            document_id=payload.document_id if payload.document_id else None,
            query=payload.query,
            answer=final_answer,
            sources=[{"document_id": c.document_id, "page": c.page, "text": c.text[:200]} for c in chunks],
            latency_ms=latency_ms,
            cache_hit=False
        )
        db.add(new_chat)
        await db.commit()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/history", response_model=List[ChatResponse])
async def chat_history(
    document_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch persistent chat history for a document or 'global' (None)."""
    
    query = select(Chat).where(Chat.user_id == current_user.id)
    
    if document_id == "global" or not document_id:
        query = query.where(Chat.document_id == None)
    else:
        query = query.where(Chat.document_id == document_id)
        
    result = await db.execute(query.order_by(Chat.created_at.asc()))
    chats = result.scalars().all()
    
    return [
        ChatResponse(
            id=str(c.id),
            answer=c.answer,
            thinking="", 
            sources=[SourceChunk(**s) for s in (c.sources or [])],
            created_at=c.created_at.isoformat()
        )
        for c in chats
    ]

@router.delete("/clear")
async def clear_chat(
    document_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Wipe chat history."""
    from sqlalchemy import delete as sa_delete
    
    stmt = sa_delete(Chat).where(Chat.user_id == current_user.id)
    
    if document_id == "global" or not document_id:
        stmt = stmt.where(Chat.document_id == None)
    else:
        stmt = stmt.where(Chat.document_id == document_id)
        
    await db.execute(stmt)
    await db.commit()
    return {"message": "Chat history cleared"}
