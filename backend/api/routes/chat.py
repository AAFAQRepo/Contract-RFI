"""
Chat API routes.

Retrieval pipeline:
  1. Query intent classification (regex, zero LLM cost) → adaptive K values.
  2. Dense + Sparse search run concurrently per document.
  3. RRF fusion → single shared cross-encoder reranking pass.
  4. Adaptive top-k cutoff → 3-8 final chunks.
  5. Streaming response over typed SSE events (thinking / token / done).
"""

import json
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth import get_current_user
from models.models import User, Chat
from services.retrieval import HybridRetriever, RetrievedChunk
from services.llm import LLMService
from core.limits import check_usage_limit, increment_usage

router       = APIRouter()
retriever    = HybridRetriever()
llm_service  = LLMService()


# ── Request / Response Models ────────────────────────────────────────────────

class ChatQuery(BaseModel):
    query:           str
    document_ids:    List[str] = []   # All docs scoped to this conversation
    conversation_id: Optional[str] = None

class SourceChunk(BaseModel):
    document_id: str
    page:        int
    text:        str

class ChatResponse(BaseModel):
    id:         str
    query:      str = ""
    answer:     str
    thinking:   str
    sources:    List[SourceChunk]
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sse(event: str, data: dict | str) -> str:
    """
    Format a single Server-Sent Events frame.
    U-1 FIX: Typed events let the frontend distinguish thinking/answer/done
    without parsing raw XML mid-stream.
    """
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ── Main Chat Endpoint ────────────────────────────────────────────────────────

@router.post("/message")
async def chat_message(
    payload: ChatQuery,
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
    _limit:       bool         = Depends(check_usage_limit("queries")),
):
    """
    Main RAG Chat Entry Point — streaming, async retrieval, typed SSE.

    Flow:
      1. CRITICAL-3: Parallel multi-doc retrieval (search_many) or single
         global search — both use the fully async HybridRetriever.
      2. Stream tokens to client as typed SSE frames.
      3. Persist chat record after stream completes.
    """
    start_time = time.time()

    # ── Step 1: Resolve document IDs ────────────────────────────────────────────────
    # Priority order:
    #   a) Frontend sent explicit document_ids  → verify ownership, use them
    #   b) conversation_id provided, no doc IDs → look them up from the DB
    #   c) No conversation, no docs            → empty context (never global search)
    #
    # GLOBAL SEARCH IS NEVER TRIGGERED HERE. Cross-chat leakage is impossible.
    from models.models import Document

    search_doc_ids: List[str] = []

    if payload.document_ids:
        # Verify every supplied ID belongs to this user (IDOR guard)
        verified = await db.execute(
            select(Document.id)
            .where(
                Document.id.in_(payload.document_ids),
                Document.user_id == current_user.id,
            )
        )
        search_doc_ids = [str(r) for r in verified.scalars().all()]

    elif payload.conversation_id:
        # Resolve documents linked to this specific conversation
        linked = await db.execute(
            select(Document.id)
            .where(
                Document.conversation_id == payload.conversation_id,
                Document.user_id == current_user.id,
            )
        )
        search_doc_ids = [str(r) for r in linked.scalars().all()]

    # Retrieve chunks only from verified document scope
    if search_doc_ids:
        chunks: List[RetrievedChunk] = await retriever.search_many(
            query=payload.query,
            user_id=str(current_user.id),
            document_ids=search_doc_ids,
            top_k=8,
        )
    else:
        # No documents in scope — return empty context.
        # The LLM will answer from system prompt only; no cross-chat data ever.
        chunks = []

    # ── Step 1b: Fetch conversation history for multi-turn context ────────────
    conversation_history = []
    if payload.conversation_id:
        hist_result = await db.execute(
            select(Chat)
            .where(
                Chat.conversation_id == payload.conversation_id,
                Chat.user_id == current_user.id,
            )
            .order_by(Chat.created_at.asc())
            .limit(6)  # Last 3 Q/A pairs
        )
        past_chats = hist_result.scalars().all()
        for past in past_chats:
            if past.query:
                conversation_history.append({"role": "user", "content": past.query})
            if past.answer:
                conversation_history.append({"role": "assistant", "content": past.answer})

    # ── Step 2: Stream tokens as typed SSE ───────────────────────────────────
    async def event_generator():
        full_answer = ""
        in_thinking = False

        async for token in llm_service.generate_response_stream(
            query=payload.query,
            chunks=chunks,
            user_name=current_user.name or "User",
            history=conversation_history,
        ):
            full_answer += token

            # Detect thinking/answer boundary and emit typed events (U-1 FIX)
            if "<thinking>" in token:
                in_thinking = True
            if "</thinking>" in token:
                in_thinking = False
                yield _sse("thinking_end", {})
                continue

            event_type = "thinking" if in_thinking else "token"
            yield _sse(event_type, {"v": token})

        # ── Step 3: Emit final "done" event with sources ──────────────────────
        sources_payload = [
            {
                "document_id": c.document_id,
                "page":        c.page,
                # U-2 FIX: 400 chars with ellipsis indicator (was 200, silent truncation)
                "text":        c.text[:400] + ("…" if len(c.text) > 400 else ""),
                "section":     c.section,
                "score":       round(c.score, 4),
            }
            for c in chunks
        ]
        yield _sse("done", {"sources": sources_payload})

        # ── Step 4: Persist to DB (after stream is complete) ─────────────────
        latency_ms = int((time.time() - start_time) * 1000)

        final_thinking = ""
        final_answer   = full_answer
        if "<thinking>" in full_answer and "</thinking>" in full_answer:
            parts          = full_answer.split("</thinking>", 1)
            final_thinking = parts[0].replace("<thinking>", "").strip()
            final_answer   = parts[1].strip()

        from models.models import Conversation, Document
        from sqlalchemy import update as sa_update

        conv_id = payload.conversation_id
        if not conv_id:
            new_conv = Conversation(
                user_id=current_user.id,
                title=(payload.query[:50] + "…") if len(payload.query) > 50 else payload.query,
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
            sources=[
                {"document_id": c.document_id, "page": c.page, "text": c.text[:400]}
                for c in chunks
            ],
            latency_ms=latency_ms,
            cache_hit=False,
        )
        db.add(new_chat)
        await db.commit()

        await increment_usage(current_user.org_id, "queries", db)

    return StreamingResponse(event_generator(), media_type="text/event-stream")



# ── Conversations ─────────────────────────────────────────────────────────────

class NewConversationRequest(BaseModel):
    document_ids: List[str] = []
    title: Optional[str] = None


@router.post("/conversations")
async def create_conversation(
    payload:      NewConversationRequest,
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """
    Pre-create a conversation and atomically link document_ids.

    Call this BEFORE sending the first message so that every conversation
    has a UUID from the very start, preventing the race condition where the
    first message has no conversation_id and triggers a cross-chat search.
    """
    from models.models import Conversation, Document
    from sqlalchemy import update as sa_update

    conv = Conversation(
        user_id=current_user.id,
        title=payload.title or "New Chat",
    )
    db.add(conv)
    await db.flush()   # get the generated UUID

    # Atomically link documents to this conversation (ownership-verified)
    if payload.document_ids:
        await db.execute(
            sa_update(Document)
            .where(Document.id.in_(payload.document_ids))
            .where(Document.user_id == current_user.id)
            .values(conversation_id=conv.id)
        )

    await db.commit()
    return {
        "id":         str(conv.id),
        "title":      conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
    }


@router.get("/conversations")
async def list_conversations(
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """List all chat sessions for the current user."""
    from models.models import Conversation
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    convs = result.scalars().all()
    return [
        {"id": str(c.id), "title": c.title, "updated_at": c.updated_at.isoformat()}
        for c in convs
    ]


@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id:      str,
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
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


# ── History & Sessions ────────────────────────────────────────────────────────

@router.get("/history", response_model=List[ChatResponse])
async def chat_history(
    conversation_id: Optional[str] = Query(None),
    document_id:     Optional[str] = Query(None),
    db:              AsyncSession   = Depends(get_db),
    current_user:    User           = Depends(get_current_user),
):
    """Fetch persistent chat history for a session or document."""
    query = select(Chat).where(Chat.user_id == current_user.id)
    if conversation_id:
        query = query.where(Chat.conversation_id == conversation_id)
    elif document_id:
        if document_id == "global":
            query = query.where(Chat.document_id == None)   # noqa: E711
        else:
            query = query.where(Chat.document_id == document_id)

    result = await db.execute(query.order_by(Chat.created_at.asc()))
    chats  = result.scalars().all()

    return [
        ChatResponse(
            id=str(c.id),
            query=c.query or "",
            answer=c.answer,
            thinking="",
            sources=[SourceChunk(**s) for s in (c.sources or [])],
            created_at=c.created_at.isoformat(),
        )
        for c in chats
    ]


@router.get("/sessions")
async def chat_sessions(
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """
    Returns distinct chat sessions for the sidebar.
    Groups global chats (no document) as a single 'General Chat' session.
    """
    from sqlalchemy import func

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
    rows   = result.all()

    return [
        {
            "document_id":     str(row.document_id) if row.document_id else None,
            "is_global":       row.document_id is None,
            "title":           row.first_query[:60] if row.first_query else "General Chat",
            "message_count":   row.message_count,
            "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        }
        for row in rows
    ]


# ── Clear / Delete ────────────────────────────────────────────────────────────

@router.delete("/clear")
async def clear_chat(
    document_id:  Optional[str] = Query(None),
    db:           AsyncSession   = Depends(get_db),
    current_user: User           = Depends(get_current_user),
):
    """Wipe chat history for the current user (optionally scoped to a document)."""
    stmt = sa_delete(Chat).where(Chat.user_id == current_user.id)
    if document_id == "global" or not document_id:
        stmt = stmt.where(Chat.document_id == None)  # noqa: E711
    else:
        stmt = stmt.where(Chat.document_id == document_id)
    await db.execute(stmt)
    await db.commit()
    return {"message": "Chat history cleared"}


@router.delete("/{chat_id}")
async def delete_chat_message(
    chat_id:      str,
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """Delete a specific chat message."""
    from uuid import UUID
    try:
        chat_uuid = UUID(chat_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat ID format")

    result   = await db.execute(
        select(Chat).where(Chat.id == chat_uuid, Chat.user_id == current_user.id)
    )
    chat_msg = result.scalar_one_or_none()
    if not chat_msg:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.delete(chat_msg)
    await db.commit()
    return {"message": "Message deleted"}
