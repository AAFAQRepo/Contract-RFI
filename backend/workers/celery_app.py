"""
Celery async tasks for document processing.

process_document — full ingestion pipeline:
  1. Download file from MinIO
  2. Extract + chunk with MinerU (pipeline backend, parse_method=auto)
  3. Detect language
  4. Embed chunks → Qdrant
  5. Store chunks → PostgreSQL
  6. Update document status
"""

import os
import sys

# macOS fix for Python multiprocessing with PyTorch / C-extensions
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"


# Add backend directory to sys.path so modules like 'models' can be imported when running Celery
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celery import Celery
from core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "contract_rfi",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


# ── Pre-warm GPU models in child worker processes ─────────────────────
from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def _preload_models(**kwargs):
    """Load the embedding model into GPU memory when the worker process starts.
    This runs in the child process, which is safe for CUDA initialization
    and eliminates the ~3s cold-start penalty on the first document."""
    try:
        from services.embedding import get_embedding_model
        get_embedding_model()
        print("🔥 Embedding model pre-warmed in worker process")
    except Exception as exc:
        print(f"⚠️  Could not pre-warm embedding model: {exc}")


@celery_app.task(name="workers.test_task")
def test_task(message: str) -> dict:
    """Test task to verify Celery is working."""
    return {"status": "ok", "message": f"Celery received: {message}"}


@celery_app.task(name="workers.process_document", bind=True, max_retries=3)
def process_document(self, document_id: str, user_id: str, object_name: str, filename: str):
    """
    Full async ingestion pipeline for a single document.
    Uses MinerU pipeline backend (auto parse_method: txt for digital PDFs,
    OCR for scanned docs) + rule-based chunker over content_list.json.
    """
    import uuid as _uuid
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    from models.models import Document, Chunk
    from services.storage import download_document
    from services.extraction import extract_and_chunk
    from services.language import detect_language
    from services.embedding import store_parsed_chunks_in_qdrant

    # Sync engine for Celery (not async)
    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)

    def _update_status(session, status: str, step: str = None, progress: int = None, error: str = None):
        doc = session.get(Document, document_id)
        if doc:
            doc.status = status
            doc.updated_at = datetime.utcnow()
            if step:
                doc.processing_step = step
            if progress is not None:
                doc.progress_percent = progress
            if error:
                doc.error_message = error
            session.commit()

    session = Session()
    try:
        # Pre-check existence (handles the race condition on server)
        doc = session.get(Document, document_id)
        if not doc:
            print(f"⚠️  Document {document_id} not found in DB; retrying in 2s...")
            raise self.retry(countdown=2)

        print(f"⏳ Processing document {document_id}")
        _update_status(session, "processing", step="Downloading", progress=10)

        # 1. Download from MinIO
        print(f"⬇️  Downloading {object_name}")
        file_bytes = download_document(object_name)
        _update_status(session, "processing", step="Extracting text", progress=30)

        # 2. Extract + chunk with MinerU (single call)
        print(f"📄 Extracting and chunking {filename} (MinerU)")
        lc_docs, full_text, page_count = extract_and_chunk(file_bytes, filename)
        _update_status(session, "processing", step="Detecting language", progress=50)

        # 3. Detect language
        language = detect_language(full_text)
        print(f"🌐 Detected language: {language}")

        # 4. Update document metadata
        doc = session.get(Document, document_id)
        if doc:
            doc.language = language
            doc.page_count = page_count
            doc.updated_at = datetime.utcnow()
            session.commit()
        
        _update_status(session, "processing", step="Embedding chunks", progress=70)

        # 5. Embed + store chunks in Qdrant
        print(f"🔢 Embedding {len(lc_docs)} chunks...")
        point_ids = store_parsed_chunks_in_qdrant(lc_docs, document_id, user_id, language)
        _update_status(session, "processing", step="Saving to database", progress=90)

        # 6. Store chunks in PostgreSQL for reference
        print(f"💾 Storing {len(lc_docs)} chunks in database...")
        db_chunks = []

        for lc_doc, point_id in zip(lc_docs, point_ids):
            meta = lc_doc.metadata or {}
            dl_meta = meta.get("dl_meta", {})
            headings = dl_meta.get("headings", [])
            section = headings[0] if headings else ""

            # Extract page number
            page = 0
            doc_items = dl_meta.get("doc_items", [])
            if doc_items:
                for item in doc_items:
                    for prov in item.get("prov", []):
                        if prov.get("page_no", 0) > page:
                            page = prov["page_no"]

            db_chunks.append(Chunk(
                id=str(_uuid.uuid4()),
                document_id=document_id,
                chunk_type="retrieval",
                text=lc_doc.page_content,
                context_summary=f"[Page {page}] {section}".strip() if page else section,
                section=section,
                clause_type=None,
                page=page,
                language=language,
                token_count=len(lc_doc.page_content.split()),
                qdrant_point_id=point_id,
            ))

        session.add_all(db_chunks)

        # 7. Mark as ready
        _update_status(session, "ready", step="Completed", progress=100)
        session.commit()

        print(f"✅ Document {document_id} processed successfully")
        return {
            "document_id": document_id,
            "status": "ready",
            "chunks": len(lc_docs),
            "language": language,
            "pages": page_count,
        }

    except Exception as exc:
        print(f"❌ Processing failed for {document_id}: {exc}")
        _update_status(session, "error", str(exc))
        session.commit()
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

    finally:
        session.close()
