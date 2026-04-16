"""
Service clients for MinIO, Qdrant, and Redis.
Initialized once and reused across the app.
"""

from minio import Minio
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import redis.asyncio as aioredis
from core.config import get_settings

settings = get_settings()

# ── MinIO Client ──

minio_client = Minio(
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)


def init_minio():
    """Create the default bucket if it doesn't exist."""
    if not minio_client.bucket_exists(settings.MINIO_BUCKET):
        minio_client.make_bucket(settings.MINIO_BUCKET)
        print(f"✅ Created MinIO bucket: {settings.MINIO_BUCKET}")
    else:
        print(f"✅ MinIO bucket exists: {settings.MINIO_BUCKET}")


# ── Qdrant Client ──

qdrant_client = QdrantClient(
    host=settings.QDRANT_HOST,
    port=settings.QDRANT_PORT,
)

QDRANT_COLLECTION = "text_chunks"
EMBEDDING_DIMENSION = 768  # Alibaba-NLP/gte-multilingual-base output dimension


def init_qdrant():
    """Create (or recreate) the text_chunks collection with the correct dimension."""
    collections = [c.name for c in qdrant_client.get_collections().collections]
    if QDRANT_COLLECTION in collections:
        # Check stored dimension — recreate if it doesn't match
        info = qdrant_client.get_collection(QDRANT_COLLECTION)
        stored_dim = info.config.params.vectors.size
        if stored_dim != EMBEDDING_DIMENSION:
            print(
                f"⚠️  Qdrant collection '{QDRANT_COLLECTION}' has dimension {stored_dim}, "
                f"expected {EMBEDDING_DIMENSION}. Recreating..."
            )
            qdrant_client.delete_collection(collection_name=QDRANT_COLLECTION)
        else:
            print(f"✅ Qdrant collection exists with correct dimension ({EMBEDDING_DIMENSION})")
            return

    qdrant_client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(
            size=EMBEDDING_DIMENSION,
            distance=Distance.COSINE,
        ),
    )
    print(f"✅ Created Qdrant collection: {QDRANT_COLLECTION} (dim={EMBEDDING_DIMENSION})")


# ── Redis Client ──

redis_client = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
)


async def init_redis():
    """Verify Redis connection."""
    pong = await redis_client.ping()
    if pong:
        print("✅ Redis connected")
    return pong
