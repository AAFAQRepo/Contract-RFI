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


@celery_app.task(name="workers.extract_batch_task", max_retries=3)
def extract_batch_task(segments: list[tuple[bytes, int]], filename: str) -> list[tuple[list[dict], list[list[float]], str, int]]:
    """
    Experimental high-speed batch task for Scanned PDFs.
    Sends all segments to the OCR service in ONE call to leverage A10 CUDA batching.
    Returns a list of (serialized_docs, embeddings, full_text, page_count).
    """
    from services.extraction import remote_convert_batch, _build_lc_docs_from_document
    from services.embedding import embed_passages

    # Prepare files for the batch call
    # segments is list of (bytes, page_offset)
    batch_input = []
    for i, (chunk_bytes, offset) in enumerate(segments):
        part_name = f"part_{i}_{filename}"
        batch_input.append((chunk_bytes, part_name))

    results, batch_latency = remote_convert_batch(batch_input)
    print(f"🚀 [Batch OCR] Completed {len(segments)} segments in {batch_latency:.2f}s")

    final_output = []
    for i, (doc, markdown, page_count) in enumerate(results):
        offset = segments[i][1]
        
        # Build LangChain docs (chunking)
        lc_docs = _build_lc_docs_from_document(doc, offset_page_no=offset)
        
        # Embeddings
        texts = [d.page_content for d in lc_docs]
        embeddings = embed_passages(texts)
        
        # Serialize for Celery
        serialized_docs = [{"page_content": d.page_content, "metadata": d.metadata} for d in lc_docs]
        final_output.append((serialized_docs, embeddings, markdown, page_count))

    return final_output


@celery_app.task(name="workers.process_document", bind=True, max_retries=3)
def process_document(self, document_id: str, user_id: str, object_name: str, filename: str):
    """
    Coordinator task for document ingestion.
    Now supports Batch Parallelism for Scanned PDFs on A10 GPUs.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    from models.models import Document
    from services.storage import download_document
    from services.extraction import split_pdf_into_chunks, is_scanned_pdf_fast_bytes

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
        doc = session.get(Document, document_id)
        if not doc:
            raise self.retry(countdown=2)

        print(f"⏳ Starting ingestion for {document_id}")
        _update_status(session, "processing", step="Downloading", progress=10)

        file_bytes = download_document(object_name)
        ext = filename.lower().split('.')[-1]
        
        if ext == 'pdf':
            is_scanned = is_scanned_pdf_fast_bytes(file_bytes)
            
            import fitz
            pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = len(pdf_doc)
            pdf_doc.close()
            
            if is_scanned:
                # 🚀 BATCH MODE for Scanned PDFs
                # For small docs (< 50 pages), we send the whole file as one segment.
                # This is much faster on the A10 than splitting.
                if total_pages <= 50:
                    print(f"🚀 Scanned PDF detected ({total_pages} pages). Sending original file for peak A10 speed.")
                    segments = [(file_bytes, 0)]
                else:
                    print(f"🚀 Large Scanned PDF detected ({total_pages} pages). Splitting into 20-page segments.")
                    num_segments = max(1, (total_pages + 19) // 20)
                    segments = split_pdf_into_chunks(file_bytes, n=num_segments)
                
                _update_status(session, "processing", step="Running Fast A10 OCR", progress=30)
                
                batch_res = extract_batch_task(segments, filename)
                finalize_document_ingestion(batch_res, document_id, user_id, filename)
                
                return {"status": "completed_batch", "parts": len(segments)}
            else:
                # 🔀 CHORD MODE for Digital PDFs
                # We still split digital PDFs because they are handled by CPUs across workers
                num_segments = max(2, min(8, (total_pages + 74) // 75))
                print(f"🔀 Digital PDF detected ({total_pages} pages): splitting into {num_segments} workers")
                _update_status(session, "processing", step=f"Dispatching {num_segments} workers", progress=20)
                
                segments = split_pdf_into_chunks(file_bytes, n=num_segments)
                callback = finalize_document_ingestion.s(document_id=document_id, user_id=user_id, filename=filename)
                header = [extract_chunk_task.s(chunk_bytes, filename, offset) for chunk_bytes, offset in segments]
                chord(header)(callback)
                
                return {"status": "dispatched", "parts": len(segments)}
        else:
            # Non-PDF
            segments = [(file_bytes, 0)]
            header = [extract_chunk_task.s(file_bytes, filename, 0)]
            callback = finalize_document_ingestion.s(document_id=document_id, user_id=user_id, filename=filename)
            chord(header)(callback)
            return {"status": "dispatched", "parts": 1}

    except Exception as exc:
        import traceback
        traceback.print_exc()
        _update_status(session, "error", error=str(exc))
        session.commit()
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        session.close()
