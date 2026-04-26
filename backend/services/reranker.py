"""
Cross-Encoder Reranker Service.

Uses BAAI/bge-reranker-v2-m3 (multilingual, supports Arabic + English).
Takes a list of candidate chunks and re-scores them against the user query,
returning the top-k most relevant chunks in order.

Fixes applied (from audit):
  R-3 — max_length raised from 512 → 1024.
        HybridChunker produces chunks up to 600 tokens; after adding the
        query, the previous 512-token cap was silently truncating chunk
        content and scoring degraded partial text.
"""

from typing import Optional
from sentence_transformers import CrossEncoder
from core.config import get_settings

settings = get_settings()

# ── Model (loaded once at first call) ─────────────────────────────────────────
_reranker: Optional[CrossEncoder] = None

RERANKER_MODEL = getattr(settings, "RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        print(f"⏳ Loading reranker: {RERANKER_MODEL}  (max_length=1024)")
        # R-3 FIX: 512 → 1024.  bge-reranker-v2-m3 supports 1024 tokens.
        # Previous value silently truncated chunks >512 tokens, scoring partial text.
        _reranker = CrossEncoder(RERANKER_MODEL, max_length=1024)
        print("✅ Reranker loaded")
    return _reranker


# ── Main function ─────────────────────────────────────────────────────────────

def rerank_chunks(
    query: str,
    chunks,          # list[RetrievedChunk]
    top_k: int = 5,
) -> list:
    """
    Re-score `chunks` against `query` using the cross-encoder.
    Returns the top `top_k` chunks sorted by reranker score (highest first).

    NOTE: This function is intentionally synchronous.  It must be called via
    asyncio.run_in_executor in any async context (enforced in retrieval.py).
    """
    if not chunks:
        return []

    reranker = get_reranker()

    pairs  = [(query, chunk.text) for chunk in chunks]
    scores = reranker.predict(pairs, show_progress_bar=False)

    scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)

    result = []
    for score, chunk in scored[:top_k]:
        chunk.score = float(score)
        result.append(chunk)

    return result
