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


@celery_app.task(name="workers.parse_document_task", bind=True, max_retries=3)
def parse_document_task(self, document_id: str, user_id: str, object_name: str, filename: str):
    """
    Stage 1: High-latency GPU extraction with MinerU.
    Saves raw results to storage as artifacts.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    import json
    from models.models import Document
    from services.storage import download_document, upload_artifact
    from services.extraction import parse_only

    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _update_status(status: str, step: str = None, progress: int = None, error: str = None):
        doc = session.get(Document, document_id)
        if doc:
            doc.status = status
            if step: doc.processing_step = step
            if progress is not None: doc.progress_percent = progress
            if error: doc.error_message = error
            doc.updated_at = datetime.utcnow()
            session.commit()

    try:
        print(f"⏳ Stage 1: Parsing document {document_id}")
        _update_status("processing", step="Parsing structure", progress=10)

        # 1. Download from MinIO
        file_bytes = download_document(object_name)
        _update_status("processing", step="Extracting text", progress=20)

        # 2. Extract with MinerU
        full_text, content_list = parse_only(file_bytes, filename)
        _update_status("processing", step="Saving artifacts", progress=50)

        # 3. Save artifacts back to MinIO for Stage 2
        prefix = f"{user_id}/{document_id}/artifacts"
        upload_artifact(f"{prefix}/content_list.json", json.dumps(content_list).encode("utf-8"))
        upload_artifact(f"{prefix}/full.md", full_text.encode("utf-8"), content_type="text/markdown")

        # 4. Trigger Stage 2
        print(f"✅ Stage 1 complete for {document_id}. Triggering Stage 2...")
        finalize_ingestion_task.delay(document_id, user_id, filename)
        
    except Exception as exc:
        print(f"❌ Stage 1 failed for {document_id}: {exc}")
        session.rollback()
        _update_status("error", error=str(exc))
        raise self.retry(exc=exc, countdown=5)
    finally:
        session.close()


@celery_app.task(name="workers.finalize_ingestion_task", bind=True, max_retries=3)
def finalize_ingestion_task(self, document_id: str, user_id: str, filename: str):
    """
    Stage 2: Chunking, Language Detection, and Embedding. 
    Uses the cached artifacts from Stage 1.
    """
    import uuid as _uuid
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    from models.models import Document, Chunk
    from services.storage import download_document
    from services.extraction import chunk_from_results
    from services.language import detect_language
    from services.embedding import store_parsed_chunks_in_qdrant

    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _update_status(status: str, step: str = None, progress: int = None, error: str = None):
        doc = session.get(Document, document_id)
        if doc:
            doc.status = status
            if step: doc.processing_step = step
            if progress is not None: doc.progress_percent = progress
            if error: doc.error_message = error
            doc.updated_at = datetime.utcnow()
            session.commit()

    try:
        print(f"🔢 Stage 2: Ingesting document {document_id}")
        _update_status("processing", step="Analyzing structure", progress=60)

        # 1. Download artifacts
        prefix = f"{user_id}/{document_id}/artifacts"
        cl_bytes = download_document(f"{prefix}/content_list.json")
        md_bytes = download_document(f"{prefix}/full.md")
        
        content_list = json.loads(cl_bytes.decode("utf-8"))
        full_text = md_bytes.decode("utf-8")

        # 2. Structure-aware Chunking
        _update_status("processing", step="Chunking", progress=70)
        lc_docs, page_count = chunk_from_results(content_list, full_text)

        # 3. Language Detect & Meta Update
        language = detect_language(full_text)
        doc = session.get(Document, document_id)
        if doc:
            doc.language = language
            doc.page_count = page_count
            session.commit()

        # 4. Embedding & Qdrant
        _update_status("processing", step="Embedding", progress=85)
        point_ids = store_parsed_chunks_in_qdrant(lc_docs, document_id, user_id, language)

        # 5. Save chunks to Postgres
        _update_status("processing", step="Finalizing", progress=95)
        db_chunks = []
        for lc_doc, point_id in zip(lc_docs, point_ids):
            meta = lc_doc.metadata or {}
            headings = meta.get("dl_meta", {}).get("headings", [])
            section = headings[0] if headings else ""
            
            # Simplified page extraction from the new meta structure
            page = 0
            prov = meta.get("dl_meta", {}).get("doc_items", [{}])[0].get("prov", [{}])[0]
            page = prov.get("page_no", 0)

            db_chunks.append(Chunk(
                id=str(_uuid.uuid4()),
                document_id=document_id,
                chunk_type="retrieval",
                text=lc_doc.page_content,
                context_summary=f"[Page {page}] {section}".strip() if page else section,
                section=section,
                page=page,
                language=language,
                token_count=len(lc_doc.page_content.split()),
                qdrant_point_id=point_id,
            ))
        
        session.add_all(db_chunks)
        _update_status("ready", step="Completed", progress=100)
        print(f"✅ Pipeline complete for {document_id}")

    except Exception as exc:
        print(f"❌ Stage 2 failed for {document_id}: {exc}")
        session.rollback()
        _update_status("error", error=str(exc))
        raise self.retry(exc=exc, countdown=5)
    finally:
        session.close()
