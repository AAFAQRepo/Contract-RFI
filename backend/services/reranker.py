"""
Cross-Encoder Reranker Service.

Uses BAAI/bge-reranker-v2-m3 (multilingual, supports Arabic + English).
Takes a list of candidate chunks and re-scores them against the user query,
returning the top-k most relevant chunks in order.

Model size: ~280MB — loaded once and cached.
"""

from typing import Optional
from sentence_transformers import CrossEncoder
from core.config import get_settings

settings = get_settings()

# ── Model (loaded once) ────────────────────────────────────────────────────
_reranker: Optional[CrossEncoder] = None

RERANKER_MODEL = getattr(settings, "RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        print(f"⏳ Loading reranker: {RERANKER_MODEL}")
        _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
        print("✅ Reranker loaded")
    return _reranker


# ── Main function ─────────────────────────────────────────────────────────────

def rerank_chunks(
    query: str,
    chunks,  # list[RetrievedChunk]
    top_k: int = 25,
    min_score: float = -2.0,
) -> list:
    """
    Re-score `chunks` against `query` using the cross-encoder.
    Returns the top `top_k` chunks sorted by reranker score (highest first).

    The cross-encoder reads the full (query, chunk_text) pair, making it far
    more accurate than cosine similarity alone.
    """
    if not chunks:
        return []

    reranker = get_reranker()

    # Pair each chunk with the query
    pairs = [(query, chunk.text) for chunk in chunks]

    # Get relevance scores (single float per pair)
    scores = reranker.predict(pairs, show_progress_bar=False)

    # Attach scores and sort
    scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)

    result = []
    for score, chunk in scored[:top_k]:
        if float(score) < min_score:
            print(f"   🚫 Dropped chunk (score={score:.2f} < threshold={min_score})")
            continue
        chunk.score = float(score)
        result.append(chunk)

    return result
