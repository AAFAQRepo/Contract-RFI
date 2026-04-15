"""
Embedding service.

Uses multilingual-e5-large-instruct to generate dense vector embeddings.
Query prefix:    "query: {text}"
Document prefix: "passage: {text}"

Stores retrieval chunk embeddings in Qdrant.
"""

import uuid
from typing import Optional

from sentence_transformers import SentenceTransformer
from qdrant_client.models import PointStruct

from core.config import get_settings
from core.clients import qdrant_client, QDRANT_COLLECTION

settings = get_settings()

# ── Model (loaded once, cached globally) ──────────────────────────────
_model: Optional[SentenceTransformer] = None


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        import logging
        logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)
        print(f"⏳ Loading embedding model: {settings.EMBEDDING_MODEL}")
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        _model.max_seq_length = 512
        print("✅ Embedding model loaded")
    return _model


# ── Encoding helpers ──────────────────────────────────────────────────

def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed document passages (with 'passage: ' prefix)."""
    model = get_embedding_model()
    prefixed = [f"passage: {t}" for t in texts]
    embeddings = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=True, batch_size=128)
    return embeddings.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a single query (with 'query: ' prefix)."""
    model = get_embedding_model()
    embedding = model.encode(f"query: {text}", normalize_embeddings=True)
    return embedding.tolist()


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

    print(f"✅ Stored {len(points)} Docling vectors in Qdrant")
    return point_ids
