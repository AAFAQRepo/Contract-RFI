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
    document_ids: List[str] = []  # All docs scoped to this conversation
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
    
    # 1. Retrieve context from ALL documents in this conversation
    chunks: List[RetrievedChunk] = []
    
    # Industry standard thresholds for BGE-v2-m3
    # We increase the PER_DOC_TOP_K to allow more "potential" relevant info to be surfaced
    PER_DOC_TOP_K = 25
    TOTAL_TOP_K = 35 
    RERANK_THRESHOLD = -4.0 
    
    for doc_id in payload.document_ids:
        doc_chunks = retriever.search(
            query=payload.query,
            user_id=str(current_user.id),
            document_id=doc_id,
            top_k=PER_DOC_TOP_K,
            rerank_threshold=RERANK_THRESHOLD
        )
        chunks.extend(doc_chunks)

    # Re-rank combined results by score, keep top TOTAL_TOP_K seeds
    # We pick the top 20 'seed' chunks and then expand them.
    # Increasing this ensures better recall for exhaustive lists.
    SEED_TOP_K = 50
    seeds = sorted(chunks, key=lambda c: getattr(c, 'score', 0), reverse=True)[:SEED_TOP_K]

    # 2. Adjacent Chunk Expansion (Industry Standard for long-form documents)
    # Fetch 1 chunk before and 1 after for each seed to ensure semantic continuity.
    if seeds:
        print(f"🔗 Expanding {len(seeds)} seed chunks with neighbors...")
        chunks = retriever.expand_with_neighbors(seeds, n=1)
        print(f"   └─ Total context size: {len(chunks)} chunks after expansion & deduplication")
    else:
        chunks = []

    # 3. Confidence Gating (Basic)
    if payload.document_ids and seeds:
        best_score = getattr(seeds[0], 'score', 0)
        print(f"📊 Best Rerank Score: {best_score:.4f}")
        if best_score < -6.0:
            print(f"🛑 Confidence Gate: Score {best_score:.4f} is very low. LLM will likely refuse.")
    elif payload.document_ids:
        print(f"⚠️ No RAG context survived the threshold ({RERANK_THRESHOLD}) for this query.")

    # 2. Agentic RAG Pipeline (Phase 2: The Verification Pipeline)
    # ----------------------------------------------------------------------
    # Step A: Draft & Audit (Internal)
    full_draft_text = ""
    async for token in llm_service.generate_response_stream(
        query=payload.query,
        chunks=chunks,
        user_name=current_user.name or "User"
    ):
        full_draft_text += token

    # Parse draft
    final_thinking = ""
    draft_answer = full_draft_text
    if "<thinking>" in full_draft_text and "</thinking>" in full_draft_text:
        parts = full_draft_text.split("</thinking>", 1)
        final_thinking = parts[0].replace("<thinking>", "").strip()
        draft_answer = parts[1].strip()

    # Step B: Agentic Audit & Correction
    final_answer = draft_answer
    if chunks:
        corrected = await llm_service.verify_and_correct_response(payload.query, chunks, draft_answer)
        if corrected:
            final_answer = corrected
            print("🕵️ Auditor corrected the response.")

    # 3. Final Persistence (using verified content)
    # ----------------------------------------------------------------------
    latency_ms = int((time.time() - start_time) * 1000)
    from models.models import Conversation, Document, Chat
    from sqlalchemy import update as sa_update
    
    conv_id = payload.conversation_id
    if not conv_id:
        new_conv = Conversation(
            user_id=current_user.id,
            title=payload.query[:50] + "..." if len(payload.query) > 50 else payload.query
        )
        db.add(new_conv)
        await db.flush()
        conv_id = new_conv.id
        if payload.document_ids:
            await db.execute(
                sa_update(Document)
                .where(Document.id.in_(payload.document_ids))
                .where(Document.user_id == current_user.id)
                .values(conversation_id=conv_id)
            )

    new_chat = Chat(
        user_id=current_user.id,
        conversation_id=conv_id,
        document_id=payload.document_ids[0] if payload.document_ids else None,
        query=payload.query,
        answer=final_answer,
        thinking=final_thinking,
        sources=[{"document_id": c.document_id, "page": c.page, "text": c.text[:200]} for c in chunks],
        latency_ms=latency_ms,
        cache_hit=False
    )
    db.add(new_chat)
    
    # Increment usage
    await increment_usage(current_user.org_id, "queries", db)
    await db.commit()

    # 4. Return Final Verified Stream
    # ----------------------------------------------------------------------
    async def verified_generator():
        # First send the thinking tag (hidden by UI logic but kept for history)
        yield f"<thinking>{final_thinking}</thinking>\n"
        
        # Stream the verified answer for smooth UI experience
        words = final_answer.split(' ')
        for i, word in enumerate(words):
            yield word + (' ' if i < len(words) - 1 else '')
            await asyncio.sleep(0.01)

    return StreamingResponse(verified_generator(), media_type="text/event-stream")

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

@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a conversation and all its messages."""
    from models.models import Conversation
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if str(conv.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed")
    await db.delete(conv)
    await db.commit()
    return {"message": f"Conversation {conv_id} deleted"}

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
            thinking=c.thinking or "", 
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
