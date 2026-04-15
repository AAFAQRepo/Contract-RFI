"""
Celery async tasks for document processing.

process_document — full ingestion pipeline using MapReduce:
  1. Router: Download file, if PDF > 50 pages, slice into MinIO tmp bounds.
  2. Map: process_document_chunk parses a slice.
  3. Reduce: merge_document_chunks glues text, embeds, and stores.
"""

import os
import sys

# macOS fix for Python multiprocessing with PyTorch / C-extensions
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

# Add backend directory to sys.path so modules like 'models' can be imported when running Celery
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celery import Celery, chord
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



@celery_app.task(name="workers.test_task")
def test_task(message: str) -> dict:
    """Test task to verify Celery is working."""
    return {"status": "ok", "message": f"Celery received: {message}"}


@celery_app.task(name="workers.process_document", bind=True, max_retries=3)
def process_document(self, document_id: str, user_id: str, object_name: str, filename: str):
    """
    Router task: Downloads document. If it's a large PDF, it slices it into 50-page
    chunks via PyMuPDF (fitz) and fires a chord of map tasks.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    import fitz
    
    from models.models import Document
    from services.storage import download_document, upload_document

    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _update_status(status: str, step: str = None, progress: int = None, error: str = None):
        doc = session.get(Document, document_id)
        if doc:
            doc.status = status
            doc.updated_at = datetime.utcnow()
            if step: doc.processing_step = step
            if progress is not None: doc.progress_percent = progress
            if error: doc.error_message = error
            session.commit()

    try:
        # Pre-check existence
        doc = session.get(Document, document_id)
        if not doc:
            print(f"⚠️  Document {document_id} not found in DB; retrying in 2s...")
            raise self.retry(countdown=2)

        print(f"⏳ Routing document {document_id}")
        _update_status("processing", step="Downloading", progress=10)
        
        # 1. Download
        file_bytes = download_document(object_name)
        is_pdf = filename.lower().endswith(".pdf")
        
        chunk_tasks = []
        
        if is_pdf:
            pdf_doc = fitz.open("pdf", file_bytes)
            total_pages = len(pdf_doc)
            
            if total_pages > 50:
                _update_status("processing", step="Splitting document chunks", progress=20)
                pages_per_chunk = 50
                for start_page in range(0, total_pages, pages_per_chunk):
                    end_page = min(start_page + pages_per_chunk - 1, total_pages - 1)
                    
                    sub_pdf = fitz.open()
                    sub_pdf.insert_pdf(pdf_doc, from_page=start_page, to_page=end_page)
                    sub_bytes = sub_pdf.write()
                    sub_pdf.close()
                    
                    chunk_obj_name = f"temp_chunks/{document_id}/part_{start_page}.pdf"
                    upload_document(sub_bytes, chunk_obj_name)
                    
                    chunk_tasks.append(process_document_chunk.s(
                        doc_id=document_id,
                        chunk_object_name=chunk_obj_name,
                        filename=f"part_{start_page}.pdf",
                        is_temp=True
                    ))
                pdf_doc.close()
            else:
                pdf_doc.close()
                chunk_tasks.append(process_document_chunk.s(
                    doc_id=document_id, 
                    chunk_object_name=object_name, 
                    filename=filename, 
                    is_temp=False
                ))
        else:
            chunk_tasks.append(process_document_chunk.s(
                doc_id=document_id, 
                chunk_object_name=object_name, 
                filename=filename, 
                is_temp=False
            ))

        print(f"🚀 Dispatching {len(chunk_tasks)} mapper tasks for {document_id}")
        _update_status("processing", step=f"Processing {len(chunk_tasks)} parallel chunks", progress=30)
        
        # Chord Callback
        callback = merge_document_chunks.s(
            doc_id=document_id,
            user_id=user_id,
            filename=filename
        )
        chord(chunk_tasks)(callback)
        
        return {"status": "dispatched", "chunks": len(chunk_tasks)}

    except Exception as exc:
        print(f"❌ Routing failed for {document_id}: {exc}")
        _update_status("error", error=str(exc))
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        session.close()


@celery_app.task(name="workers.process_document_chunk", bind=True, max_retries=3)
def process_document_chunk(self, doc_id: str, chunk_object_name: str, filename: str, is_temp: bool):
    """
    Map task: Downloads a slice from MinIO, parses it with Docling, serializes chunks.
    """
    from services.storage import download_document, delete_document
    from services.extraction import extract_and_chunk
    
    file_bytes = download_document(chunk_object_name)
    if is_temp:
        delete_document(chunk_object_name)
        
    lc_docs, full_text, page_count = extract_and_chunk(file_bytes, filename)
    
    serialized_docs = []
    for doc in lc_docs:
        serialized_docs.append({
            "page_content": doc.page_content,
            "metadata": doc.metadata
        })
        
    return {
        "lc_docs": serialized_docs,
        "full_text": full_text,
        "page_count": page_count
    }


@celery_app.task(name="workers.merge_document_chunks", bind=True)
def merge_document_chunks(self, results: list, doc_id: str, user_id: str, filename: str):
    """
    Reducer task: Assembles all map results, runs language detection, embedding, and storage.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime
    import uuid as _uuid
    
    from models.models import Document, Chunk
    from services.language import detect_language
    from services.embedding import store_docling_chunks_in_qdrant
    from dataclasses import dataclass
    
    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _update_status(status: str, step: str = None, progress: int = None, error: str = None):
        doc = session.get(Document, doc_id)
        if doc:
            doc.status = status
            doc.updated_at = datetime.utcnow()
            if step: doc.processing_step = step
            if progress is not None: doc.progress_percent = progress
            if error: doc.error_message = error
            session.commit()

    try:
        _update_status("processing", step="Merging chunks", progress=60)
        print(f"🧩 Merging {len(results)} chunks for {doc_id}")
        
        combined_text = ""
        total_pages = 0
        
        @dataclass
        class DummyDoc:
            page_content: str
            metadata: dict
            
        combined_lc_docs = []
        for r in results:
            if not r: continue
            combined_text += "\n\n" + r.get("full_text", "")
            total_pages += r.get("page_count", 0)
            
            for doc_dict in r.get("lc_docs", []):
                combined_lc_docs.append(DummyDoc(
                    page_content=doc_dict.get("page_content", ""),
                    metadata=doc_dict.get("metadata", {})
                ))
        
        _update_status("processing", step="Detecting language", progress=70)
        language = detect_language(combined_text)
        
        doc = session.get(Document, doc_id)
        if doc:
            doc.language = language
            doc.page_count = max(total_pages, doc.page_count or 0)
            session.commit()
            
        _update_status("processing", step="Embedding chunks", progress=80)
        point_ids = store_docling_chunks_in_qdrant(combined_lc_docs, doc_id, user_id, language)
        
        _update_status("processing", step="Saving to database", progress=90)
        db_chunks = []
        for lc_doc, point_id in zip(combined_lc_docs, point_ids):
            meta = lc_doc.metadata or {}
            dl_meta = meta.get("dl_meta", {})
            headings = dl_meta.get("headings", [])
            section = headings[0] if headings else ""
            
            page = 0
            doc_items = dl_meta.get("doc_items", [])
            if doc_items:
                for item in doc_items:
                    for prov in item.get("prov", []):
                         if prov.get("page_no", 0) > page:
                             page = prov["page_no"]
                             
            db_chunks.append(Chunk(
                id=str(_uuid.uuid4()),
                document_id=doc_id,
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
        session.commit()
        print(f"✅ Document {doc_id} completely merged and processed!")
        return {"document_id": doc_id, "status": "ready", "chunks": len(combined_lc_docs), "pages": total_pages}
        
    except Exception as exc:
        print(f"❌ Merging failed for {doc_id}: {exc}")
        _update_status("error", error=str(exc))
        raise
    finally:
        session.close()
