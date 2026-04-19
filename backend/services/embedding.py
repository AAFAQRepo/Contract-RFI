"""
Embedding service.

Uses Alibaba-NLP/gte-multilingual-base to generate dense vector embeddings.
Dimension: 768. No query/passage prefixes required.

Stores retrieval chunk embeddings in Qdrant.
"""

import uuid
from typing import Optional

import time
from concurrent.futures import ThreadPoolExecutor
import torch
import httpx
from qdrant_client.models import PointStruct

from core.config import get_settings
from core.clients import qdrant_client, QDRANT_COLLECTION

settings = get_settings()


# ── Remote Embedding Client ───────────────────────────────────────────

# Global client for connection pooling (Industry standard for microservices)
_http_client = httpx.Client(
    timeout=60.0, 
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)

def _send_single_batch(batch: list[str], attempt_info: str = "") -> list[list[float]]:
    """Helper function to send a single batch to TEI with retry logic."""
    max_retries = 3
    retry_delay = 2
    for attempt in range(max_retries):
        try:
            response = _http_client.post(
                f"{settings.EMBEDDING_SERVICE_URL}/embed",
                json={"inputs": batch}
            )
            response.raise_for_status()
            return response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as net_exc:
            if attempt < max_retries - 1:
                print(f"⚠️  {attempt_info} attempt {attempt+1} failed: {net_exc}. Retrying...")
                time.sleep(retry_delay)
                continue
            raise
        except Exception as exc:
            print(f"❌ {attempt_info} failed: {exc}")
            raise
    return []

def embed_passages(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Embed document passages using a remote inference server (TEI).
    Uses CONCURRENT sub-batching to maximize TEI's internal throughput.
    """
    if not texts:
        return []

    # Create sub-batches
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    
    # Process batches CONCURRENTLY
    # This hits TEI's continuous batching engine all at once
    all_embeddings = []
    with ThreadPoolExecutor(max_workers=min(len(batches), 20)) as executor:
        # Use map to preserve order easily
        futures = [
            executor.submit(_send_single_batch, b, f"Batch {i}") 
            for i, b in enumerate(batches)
        ]
        for future in futures:
            all_embeddings.extend(future.result())
            
    return all_embeddings


def embed_query(text: str) -> list[float]:
    """Embed a single query via remote service."""
    embeddings = embed_passages([text])
    return embeddings[0] if embeddings else []


# ── Qdrant storage ────────────────────────────────────────────────────

def store_chunks_in_qdrant(
    retrieval_chunks,      # list[RetrievalChunk]
    document_id: str,
    user_id: str,
) -> list[str]:
    """
    Embed retrieval chunks and upsert into Qdrant.
    Returns list of Qdrant point IDs.
    """
    if not retrieval_chunks:
        return []

    texts = [c.text for c in retrieval_chunks]
    embeddings = embed_passages(texts)

    points = []
    point_ids = []

    for chunk, embedding in zip(retrieval_chunks, embeddings):
        point_id = chunk.chunk_id
        point_ids.append(point_id)
        points.append(
            PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "document_id": document_id,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "context_summary": chunk.context_summary,
                    "section": chunk.section,
                    "page": chunk.page,
                    "language": chunk.language,
                    "clause_type": "",
                    "user_id": user_id,
                    "chunk_type": "retrieval",
                },
            )
        )

    # Upsert in batches of 1000
    batch_size = 1000
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=batch)

    print(f"✅ Stored {len(points)} vectors in Qdrant")
    return point_ids


def store_docling_chunks_in_qdrant(
    lc_docs: list,       # LangChain Document objects from DoclingLoader
    document_id: str,
    user_id: str,
    language: str,
) -> list[str]:
    """
    Embed Docling-produced LangChain Document chunks and upsert into Qdrant.
    Returns list of Qdrant point IDs.
    """
    if not lc_docs:
        return []

    texts = [doc.page_content for doc in lc_docs]
    embeddings = embed_passages(texts)
    
    return store_precomputed_chunks_in_qdrant(
        lc_docs=lc_docs,
        embeddings=embeddings,
        document_id=document_id,
        user_id=user_id,
        language=language
    )


def store_precomputed_chunks_in_qdrant(
    lc_docs: list,
    embeddings: list[list[float]],
    document_id: str,
    user_id: str,
    language: str,
) -> list[str]:
    """
    Upsert pre-computed Docling chunks into Qdrant.
    """
    if not lc_docs or not embeddings:
        return []

    points = []
    point_ids = []

    for doc, embedding in zip(lc_docs, embeddings):
        point_id = str(uuid.uuid4())
        point_ids.append(point_id)

        # Extract rich metadata from Docling's dl_meta
        meta = doc.metadata or {}
        dl_meta = meta.get("dl_meta", {})
        headings = dl_meta.get("headings", [])
        section = headings[0] if headings else ""

        # Extract page number from doc_items provenance
        page = 0
        doc_items = dl_meta.get("doc_items", [])
        if doc_items:
            for item in doc_items:
                for prov in item.get("prov", []):
                    if prov.get("page_no", 0) > page:
                        page = prov["page_no"]

        context_summary = f"[Page {page}] {section}".strip() if page else section

        points.append(
            PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "document_id": document_id,
                    "chunk_id": point_id,
                    "text": doc.page_content,
                    "context_summary": context_summary,
                    "section": section,
                    "page": page,
                    "language": language,
                    "clause_type": "",
                    "user_id": user_id,
                    "chunk_type": "retrieval",
                },
            )
        )

    # Upsert in batches of 1000
    batch_size = 1000
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=batch)

    print(f"✅ Stored {len(points)} pre-computed vectors in Qdrant")
    return point_ids
