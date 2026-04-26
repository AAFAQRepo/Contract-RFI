"""
Document management endpoints — upload, list, get, status.

Fixes applied (from audit):
  CRITICAL-5 — get_document and get_document_status now require authentication
               and verify that the requesting user owns the document (IDOR fix).
  A-2        — get_document_status uses SQL COUNT / GROUP BY instead of loading
               all chunk ORM objects into memory to count them.
"""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from core.database import get_db
from core.auth import get_current_user
from models.models import Document, Chunk, User
from services.storage import upload_document, build_object_name

from core.limits import check_usage_limit, increment_usage

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
MAX_FILE_SIZE_MB = 100


@router.post("/upload")
async def upload_document_endpoint(
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _limit: bool = Depends(check_usage_limit("documents")),
):
    """Upload a contract document. Stores in MinIO, queues Celery processing."""
    # Validate extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: PDF, DOCX",
        )

    # Read bytes
    file_bytes = await file.read()

    # Validate size
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb:.1f} MB). Maximum: {MAX_FILE_SIZE_MB} MB",
        )

    user_id = str(current_user.id)
    document_id = str(uuid.uuid4())

    # Build MinIO path and upload
    object_name = build_object_name(user_id, document_id, file.filename)
    upload_document(
        file_bytes=file_bytes,
        object_name=object_name,
        content_type=file.content_type or "application/octet-stream",
    )

    # Create DB record, optionally scoped to a conversation
    doc = Document(
        id=document_id,
        user_id=user_id,
        conversation_id=conversation_id if conversation_id else None,
        filename=file.filename,
        file_path=object_name,
        file_size_bytes=len(file_bytes),
        file_type=ext.lstrip("."),
        status="processing",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(doc)
    await db.commit()

    # Increment usage
    await increment_usage(current_user.org_id, "documents", db)

    # Enqueue Celery task
    from workers.celery_app import process_document
    process_document.delay(
        document_id=document_id,
        user_id=user_id,
        object_name=object_name,
        filename=file.filename,
    )

    return {
        "document_id": document_id,
        "filename": file.filename,
        "status": "processing",
        "size_mb": round(size_mb, 2),
        "conversation_id": conversation_id,
        "message": "Document uploaded. Processing started in background.",
    }


@router.get("/")
async def list_documents(
    conversation_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List documents. If conversation_id provided, return only docs for that chat."""
    user_id = str(current_user.id)
    query = select(Document).where(Document.user_id == user_id)
    if conversation_id:
        query = query.where(Document.conversation_id == conversation_id)
    else:
        # No filter: return only orphaned docs (no conversation)
        query = query.where(Document.conversation_id == None)  # noqa: E711
    result = await db.execute(query.order_by(Document.created_at.desc()))
    docs = result.scalars().all()
    return {
        "documents": [
            {
                "id": str(d.id),
                "filename": d.filename,
                "status": d.status,
                "processing_step": d.processing_step,
                "progress_percent": d.progress_percent,
                "language": d.language,
                "page_count": d.page_count,
                "size_mb": round((d.file_size_bytes or 0) / (1024 * 1024), 2),
                "conversation_id": str(d.conversation_id) if d.conversation_id else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get document metadata.
    CRITICAL-5 FIX: requires auth + ownership verification (IDOR fix).
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed")
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "status": doc.status,
        "processing_step": doc.processing_step,
        "progress_percent": doc.progress_percent,
        "language": doc.language,
        "contract_type": doc.contract_type,
        "page_count": doc.page_count,
        "file_type": doc.file_type,
        "size_mb": round((doc.file_size_bytes or 0) / (1024 * 1024), 2),
        "error_message": doc.error_message,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/{doc_id}/status")
async def get_document_status(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get document processing status — used for polling from frontend.
    CRITICAL-5 FIX: requires auth + ownership verification (IDOR fix).
    A-2 FIX: uses SQL COUNT/GROUP BY instead of loading all chunk rows.
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed")

    extra = {}
    if doc.status == "ready":
        # A-2 FIX: COUNT via SQL, never load chunk text into memory.
        count_result = await db.execute(
            select(Chunk.chunk_type, func.count(Chunk.id).label("cnt"))
            .where(Chunk.document_id == doc_id)
            .group_by(Chunk.chunk_type)
        )
        counts = {row.chunk_type: row.cnt for row in count_result.all()}
        extra["retrieval_chunks"] = counts.get("retrieval", 0)
        extra["analysis_chunks"]  = counts.get("analysis", 0)

    return {
        "document_id":    doc_id,
        "status":         doc.status,
        "processing_step": doc.processing_step,
        "progress_percent": doc.progress_percent,
        "language":       doc.language,
        "page_count":     doc.page_count,
        "error_message":  doc.error_message,
        **extra,
    }


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document from Postgres, MinIO, and Qdrant (all its vectors)."""
    from sqlalchemy import delete as sa_delete
    from core.clients import qdrant_client, QDRANT_COLLECTION
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    from services.storage import minio_client
    from core.config import get_settings

    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if str(doc.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed")

    # 1. Delete Qdrant vectors for this document
    try:
        qdrant_client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]),
        )
    except Exception as e:
        print(f"⚠️  Qdrant cleanup warning: {e}")

    # 2. Delete from MinIO
    try:
        settings = get_settings()
        minio_client.remove_object(settings.MINIO_BUCKET, doc.file_path)
    except Exception as e:
        print(f"⚠️  MinIO cleanup warning: {e}")

    # 3. Delete chunks from Postgres
    await db.execute(sa_delete(Chunk).where(Chunk.document_id == doc_id))

    # 4. Delete document record
    await db.delete(doc)
    await db.commit()

    return {"message": f"Document {doc_id} deleted successfully"}
