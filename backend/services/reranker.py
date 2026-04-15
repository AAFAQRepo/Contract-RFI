"""
Cross-Encoder Reranker Service.

Uses BAAI/bge-reranker-v2-m3 (multilingual, supports Arabic + English).
Takes a list of candidate chunks and re-scores them against the user query,
returning the top-k most relevant chunks in order.

Model size: ~280MB — loaded once and cached.
"""

import httpx
from core.config import get_settings

settings = get_settings()

RERANKER_MODEL = getattr(settings, "RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

# ── Main function ─────────────────────────────────────────────────────────────

def rerank_chunks(
    query: str,
    chunks,  # list[RetrievedChunk]
    top_k: int = 5,
    min_score_threshold: float = -2.0,
) -> list:
    """
    Re-score `chunks` against `query` using the Infinity Server.
    Returns the top `top_k` chunks sorted by reranker score (highest first).
    """
    if not chunks:
        return []

    docs_text = [chunk.text for chunk in chunks]
    
    url = f"{settings.INFINITY_BASE_URL}/rerank"
    payload = {
        "model": RERANKER_MODEL,
        "query": query,
        "documents": docs_text,
        "return_documents": False
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
        # Infinity /rerank returns {"results": [{"index": i, "relevance_score": s}, ...]}
        # We need to map scores back to our original chunks array order
        # Since 'results' might already be sorted by the API, we use the original index
        scores = [0.0] * len(chunks)
        for item in data.get("results", []):
            scores[item["index"]] = float(item["relevance_score"])
            
    except Exception as e:
        print(f"⚠️ Infinity rerank failed: {e}")
        # Fallback to 0.0 scores
        scores = [0.0] * len(chunks)

    # Attach scores and sort
    scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)

    result = []
    for score, chunk in scored:
        if score < min_score_threshold and len(result) > 0:
            # Keep at least 1 chunk if all are terrible, otherwise break
            continue
        chunk.score = float(score)
        result.append(chunk)
        if len(result) >= top_k:
            break

    return result
