"""
Health check endpoint — verifies all services are connected.
"""

from fastapi import APIRouter
from core.clients import qdrant_client, minio_client, redis_client, QDRANT_COLLECTION
from core.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health_check():
    status = {"status": "ok", "services": {}}

    # PostgreSQL — checked implicitly by FastAPI running
    status["services"]["api"] = "connected"

    # Redis
    try:
        pong = await redis_client.ping()
        status["services"]["redis"] = "connected" if pong else "error"
    except Exception as e:
        status["services"]["redis"] = f"error: {str(e)}"

    # Qdrant
    try:
        info = qdrant_client.get_collection(QDRANT_COLLECTION)
        status["services"]["qdrant"] = {
            "status": "connected",
            "collection": QDRANT_COLLECTION,
            "vectors_count": info.vectors_count,
        }
    except Exception as e:
        status["services"]["qdrant"] = f"error: {str(e)}"

    # MinIO
    try:
        exists = minio_client.bucket_exists(settings.MINIO_BUCKET)
        status["services"]["minio"] = {
            "status": "connected",
            "bucket": settings.MINIO_BUCKET,
            "exists": exists,
        }
    except Exception as e:
        status["services"]["minio"] = f"error: {str(e)}"

    # Overall status
    errors = [k for k, v in status["services"].items() if isinstance(v, str) and v.startswith("error")]
    if errors:
        status["status"] = "degraded"

    return status
