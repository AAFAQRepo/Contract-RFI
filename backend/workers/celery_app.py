"""
Celery async tasks for document processing.

process_document — full ingestion pipeline:
  1. Download file from MinIO
  2. Three-tier extraction: Lean → Enriched (FAST tables) → OCR
  3. Detect language
  4. Chunk with Docling HybridChunker
  5. Embed chunks → Qdrant
  6. Store chunks → PostgreSQL
  7. Update document status
"""

import os
import sys

# macOS fix for Python multiprocessing with PyTorch / C-extensions
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"


# Add backend directory to sys.path so modules like 'models' can be imported when running Celery
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celery import Celery, chord, group
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


# Workers will hit the remote TEI endpoint for embeddings, so no local model loading is needed here.


@celery_app.task(name="workers.test_task")
def test_task(message: str) -> dict:
    """Test task to verify Celery is working."""
    return {"status": "ok", "message": f"Celery received: {message}"}


@celery_app.task(name="workers.extract_chunk_task", max_retries=3)
def extract_chunk_task(chunk_bytes: bytes, filename: str, offset_page_no: int) -> tuple[list[dict], list[list[float]], str, int]:
    """
    Worker task: Extracts text AND generates embeddings for a PDF chunk.
    Distributing embedding inference across workers improves speed and spreads GPU load.
    Returns (serialized_lc_docs, embeddings, full_text, page_count).
    """
    from services.extraction import extract_and_chunk
    from services.embedding import embed_passages

    lc_docs, full_text, page_count = extract_and_chunk(chunk_bytes, filename, offset_page_no)

    # NEW: Perform embedding inference in parallel within this worker
    texts = [d.page_content for d in lc_docs]
    embeddings = embed_passages(texts)

    # Serialize for Celery JSON compatibility
    serialized_docs = [
        {"page_content": d.page_content, "metadata": d.metadata}
        for d in lc_docs
    ]
    return serialized_docs, embeddings, full_text, page_count


@celery_app.task(name="workers.finalize_document_ingestion")
def finalize_document_ingestion(results, document_id: str, user_id: str, filename: str):
    """
    Reducer task: Merges results from parallel extraction segments,
    detects language, embeds chunks, and stores everything in DB/Qdrant.
    """
    import uuid as _uuid
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    from models.models import Document, Chunk
    from services.language import detect_language
    from services.embedding import store_docling_chunks_in_qdrant
    from services.extraction import _ChunkDoc  # For type hinting if needed

    # results is a list of [serialized_docs, embeddings, full_text, page_count]
    all_lc_docs = []
    all_embeddings = []
    merged_full_text_parts = []
    total_page_count = 0

    # Sort results by offset (implicitly stored in results order if using chord)
    for sc_docs, embeddings, full_text, page_count in results:
        # Reconstruct _ChunkDoc objects
        all_lc_docs.extend([
            _ChunkDoc(page_content=d["page_content"], metadata=d["metadata"])
            for d in sc_docs
        ])
        all_embeddings.extend(embeddings)
        if full_text:
            merged_full_text_parts.append(full_text)
        total_page_count += page_count

    merged_full_text = "\n\n".join(merged_full_text_parts)

    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _update_status(sess, status: str, step: str = None, progress: int = None, error: str = None):
        doc = sess.get(Document, document_id)
        if doc:
            doc.status = status
            doc.updated_at = datetime.utcnow()
            if step:
                doc.processing_step = step
            if progress is not None:
                doc.progress_percent = progress
            if error:
                doc.error_message = error
            sess.commit()

    try:
        print(f"🏁 Merging results for {document_id} ({len(all_lc_docs)} chunks total)")
        _update_status(session, "processing", step="Merging results", progress=50)

        # 1. Detect language
        language = detect_language(merged_full_text)
        print(f"🌐 Merged language detection: {language}")

        # 2. Update document metadata
        doc = session.get(Document, document_id)
        if doc:
            doc.language = language
            doc.page_count = total_page_count
            doc.updated_at = datetime.utcnow()
            session.commit()

        _update_status(session, "processing", step="Saving to database", progress=70)

        # 3. Store pre-computed chunks in Qdrant (NO inference here)
        print(f"💾 Storing {len(all_lc_docs)} merged chunks in Qdrant (using pre-computed vectors)...")
        from services.embedding import store_precomputed_chunks_in_qdrant
        point_ids = store_precomputed_chunks_in_qdrant(
            all_lc_docs, 
            all_embeddings, 
            document_id, 
            user_id, 
            language
        )
        _update_status(session, "processing", step="Finalizing database", progress=90)

        # 4. Store chunks in PostgreSQL
        print(f"💾 Storing {len(all_lc_docs)} chunks in database...")
        db_chunks = []

        for lc_doc, point_id in zip(all_lc_docs, point_ids):
            meta = lc_doc.metadata or {}
            dl_meta = meta.get("dl_meta", {})
            headings = dl_meta.get("headings", [])
            section = headings[0] if headings else ""

            # Extract page number (already adjusted by offset in the worker)
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
                page=page,
                language=language,
                token_count=len(lc_doc.page_content.split()),
                qdrant_point_id=point_id,
            ))

        session.add_all(db_chunks)
        _update_status(session, "ready", step="Completed", progress=100)
        session.commit()

        print(f"✅ Parallel processing for {document_id} completed")

    except Exception as exc:
        print(f"❌ Finalization failed for {document_id}: {exc}")
        _update_status(session, "error", error=str(exc))
        session.commit()
    finally:
        session.close()


@celery_app.task(name="workers.process_document", bind=True, max_retries=3)
def process_document(self, document_id: str, user_id: str, object_name: str, filename: str):
    """
    Coordinator task for document ingestion.
    Implementation:
      1. Download file from MinIO.
      2. If PDF, split into two segments for parallel processing.
      3. Dispatch workers via Chord and merge in finalized task.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    from models.models import Document
    from services.storage import download_document
    from services.extraction import split_pdf_into_chunks

    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _update_status(sess, status: str, step: str = None, progress: int = None, error: str = None):
        doc = sess.get(Document, document_id)
        if doc:
            doc.status = status
            doc.updated_at = datetime.utcnow()
            if step:
                doc.processing_step = step
            if progress is not None:
                doc.progress_percent = progress
            if error:
                doc.error_message = error
            sess.commit()

    try:
        # Pre-check existence
        doc = session.get(Document, document_id)
        if not doc:
            raise self.retry(countdown=2)

        print(f"⏳ Starting parallel ingestion for {document_id}")
        _update_status(session, "processing", step="Downloading", progress=10)

        # 1. Download
        file_bytes = download_document(object_name)

        # 2. Coordinate Extraction
        ext = filename.lower().split('.')[-1]
        
        if ext == 'pdf':
            print("🔀 PDF detected: splitting into five parallel segments")
            _update_status(session, "processing", step="Splitting PDF", progress=20)
            segments = split_pdf_into_chunks(file_bytes, n=5)
        else:
            # Single segment for non-PDFs
            segments = [(file_bytes, 0)]

        # 3. Create Chord: Map (Extract) -> Reduce (Finalize)
        _update_status(session, "processing", step=f"Dispatching {len(segments)} workers", progress=30)
        
        callback = finalize_document_ingestion.s(
            document_id=document_id,
            user_id=user_id,
            filename=filename
        )
        
        header = [
            extract_chunk_task.s(chunk_bytes, filename, offset)
            for chunk_bytes, offset in segments
        ]
        
        chord(header)(callback)
        
        print(f"📡 Coordination complete for {document_id}. Workers dispatched.")
        return {"status": "dispatched", "parts": len(segments)}

    except Exception as exc:
        print(f"❌ Coordination failed for {document_id}: {exc}")
        _update_status(session, "error", error=str(exc))
        session.commit()
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        session.close()
