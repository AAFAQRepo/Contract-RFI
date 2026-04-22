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

from core.limits import check_usage_limit, increment_usage

router = APIRouter()
retriever = HybridRetriever()
llm_service = LLMService()

# ── Models ──────────────────────────────────────────────────────────────────

class ChatQuery(BaseModel):
    query: str
    document_id: Optional[str] = None
    conversation_id: Optional[str] = None

class SourceChunk(BaseModel):
    document_id: str
    page: int
    text: str

class ChatResponse(BaseModel):
    id: str
    query: str = ""   # user's original question
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
    _limit: bool = Depends(check_usage_limit("queries")),
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
        from models.models import Conversation
        
        conv_id = payload.conversation_id
        if not conv_id:
            # Create new conversation
            new_conv = Conversation(
                user_id=current_user.id,
                title=payload.query[:50] + "..." if len(payload.query) > 50 else payload.query
            )
            db.add(new_conv)
            await db.flush()
            conv_id = new_conv.id

        new_chat = Chat(
            user_id=current_user.id,
            conversation_id=conv_id,
            document_id=payload.document_id if payload.document_id else None,
            query=payload.query,
            answer=final_answer,
            sources=[{"document_id": c.document_id, "page": c.page, "text": c.text[:200]} for c in chunks],
            latency_ms=latency_ms,
            cache_hit=False
        )
        db.add(new_chat)
        await db.commit()

        # Increment usage
        await increment_usage(current_user.org_id, "queries", db)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all chat sessions for the current user."""
    from models.models import Conversation
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    convs = result.scalars().all()
    return [{
        "id": str(c.id),
        "title": c.title,
        "updated_at": c.updated_at.isoformat()
    } for c in convs]

@router.get("/history", response_model=List[ChatResponse])
async def chat_history(
    conversation_id: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch persistent chat history for a session or document."""
    from models.models import Chat
    
    query = select(Chat).where(Chat.user_id == current_user.id)
    if conversation_id:
        query = query.where(Chat.conversation_id == conversation_id)
    elif document_id:
        if document_id == "global":
            query = query.where(Chat.document_id == None)
        else:
            query = query.where(Chat.document_id == document_id)
    
    result = await db.execute(query.order_by(Chat.created_at.asc()))
    chats = result.scalars().all()
    
    return [
        ChatResponse(
            id=str(c.id),
            query=c.query or "",
            answer=c.answer,
            thinking="", 
            sources=[SourceChunk(**s) for s in (c.sources or [])],
            created_at=c.created_at.isoformat()
        )
        for c in chats
    ]


@router.get("/sessions")
async def chat_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns a list of distinct chat sessions for the sidebar.
    - Global chats (no document) are grouped as a single 'General Chat' session.
    - Document-linked chats appear per-document.
    """
    from sqlalchemy import func, text
    
    # Fetch one row per document_id (NULLs included), ordered by most recent message
    stmt = (
        select(
            Chat.document_id,
            func.max(Chat.created_at).label("last_message_at"),
            func.count(Chat.id).label("message_count"),
            func.min(Chat.query).label("first_query"),
        )
        .where(Chat.user_id == current_user.id)
        .group_by(Chat.document_id)
        .order_by(func.max(Chat.created_at).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    sessions = []
    for row in rows:
        sessions.append({
            "document_id": str(row.document_id) if row.document_id else None,
            "is_global": row.document_id is None,
            "title": row.first_query[:60] if row.first_query else "General Chat",
            "message_count": row.message_count,
            "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        })
    return sessions

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

@router.delete("/{chat_id}")
async def delete_chat_message(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a specific chat message."""
    from uuid import UUID
    
    try:
        chat_uuid = UUID(chat_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat ID format")

    stmt = select(Chat).where(Chat.id == chat_uuid, Chat.user_id == current_user.id)
    result = await db.execute(stmt)
    chat_msg = result.scalar_one_or_none()

    if not chat_msg:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.delete(chat_msg)
    await db.commit()
    return {"message": "Message deleted"}
