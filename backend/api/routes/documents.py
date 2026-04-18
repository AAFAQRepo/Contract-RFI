"""
Document management endpoints — upload, list, get, status.
Phase 1B: fully implemented.
"""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.auth import get_current_user
from models.models import Document, Chunk, User
from services.storage import upload_document, build_object_name, get_presigned_upload_url

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
MAX_FILE_SIZE_MB = 150 # Increased for textbooks


@router.post("/initiate-upload")
async def initiate_upload(
    filename: str,
    content_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Step 1 of Direct Upload: Generate a presigned URL for the client to PUT to MinIO.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'")

    user_id = str(current_user.id)
    document_id = str(uuid.uuid4())
    object_name = build_object_name(user_id, document_id, filename)

    # Generate the URL
    try:
        upload_url = get_presigned_upload_url(object_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")

    # Create placeholder record in DB
    doc = Document(
        id=document_id,
        user_id=user_id,
        filename=filename,
        file_path=object_name,
        file_type=ext.lstrip("."),
        status="uploading",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(doc)
    await db.commit()

    return {
        "document_id": document_id,
        "upload_url": upload_url,
        "object_name": object_name,
    }


@router.post("/finalize-upload/{doc_id}")
async def finalize_upload(
    doc_id: str,
    file_size: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Step 3 of Direct Upload: Client notifies us that the PUT to MinIO is finished.
    Sets status to 'processing' and triggers Celery.
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if str(doc.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    doc.status = "processing"
    doc.file_size_bytes = file_size
    doc.updated_at = datetime.utcnow()
    await db.commit()

    # Enqueue Celery task
    from workers.celery_app import process_document
    process_document.delay(
        document_id=doc_id,
        user_id=str(current_user.id),
        object_name=doc.file_path,
        filename=doc.filename,
    )

    return {"status": "processing", "document_id": doc_id}


@router.post("/upload")
async def upload_document_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # Use authenticated user (currently dummy in auth.py)
    user_id = str(current_user.id)
    document_id = str(uuid.uuid4())

    # Build MinIO path and upload
    object_name = build_object_name(user_id, document_id, file.filename)
    upload_document(
        file_bytes=file_bytes,
        object_name=object_name,
        content_type=file.content_type or "application/octet-stream",
    )

    # Create DB record
    doc = Document(
        id=document_id,
        user_id=user_id,
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
        "message": "Document uploaded. Processing started in background.",
    }


@router.get("/")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all documents."""
    user_id = str(current_user.id)
    result = await db.execute(
        select(Document).where(Document.user_id == user_id).order_by(Document.created_at.desc())
    )
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
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }


@router.get("/{doc_id}")
async def get_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    """Get document metadata."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
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
async def get_document_status(doc_id: str, db: AsyncSession = Depends(get_db)):
    """Get document processing status — used for polling from frontend."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    extra = {}
    if doc.status == "ready":
        # Count chunks
        result = await db.execute(
            select(Chunk).where(Chunk.document_id == doc_id)
        )
        chunks = result.scalars().all()
        extra["retrieval_chunks"] = sum(1 for c in chunks if c.chunk_type == "retrieval")
        extra["analysis_chunks"] = sum(1 for c in chunks if c.chunk_type == "analysis")

    return {
        "document_id": doc_id,
        "status": doc.status,
        "processing_step": doc.processing_step,
        "progress_percent": doc.progress_percent,
        "language": doc.language,
        "page_count": doc.page_count,
        "error_message": doc.error_message,
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
