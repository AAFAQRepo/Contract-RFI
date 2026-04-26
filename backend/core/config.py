"""
Core configuration — loads all settings from .env
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ──
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-this-in-production"

    # ── PostgreSQL ──
    DATABASE_URL: str = "postgresql+asyncpg://admin:changeme@localhost:5432/contract_rfi"
    DATABASE_URL_SYNC: str = "postgresql://admin:changeme@localhost:5432/contract_rfi"

    # ── Redis ──
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Qdrant ──
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # ── MinIO ──
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "contracts"
    MINIO_SECURE: bool = False

    # ── LLM (SGLang) ──
    SGLANG_LLM_PROVIDER: str = "sglang"
    SGLANG_API_KEY: str = ""
    SGLANG_BASE_URL: str = "https://locallm.aafaq.ai/v1"
    SGLANG_INTENT_MODEL: str = "meta-llama/Llama-3.1-8B-Instruct"
    SGLANG_USE_FORM_DATA: bool = False

    # ── Embedding ──
    EMBEDDING_MODEL: str = "Alibaba-NLP/gte-multilingual-base"
    EMBEDDING_SERVICE_URL: str = "http://localhost:8080"

    # ── Reranker ──
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # ── Celery ──
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── OCR Engine ──
    # suryaocr (default, GPU optimized) | rapidocr (fast fallback)
    OCR_ENGINE: str = "suryaocr"

    # ── GPU Offloading ──
    USE_GPU_SERVER: bool = False
    GPU_SERVER_IP: str = "localhost"

    # ── CORS ──
    # Comma-separated list of allowed origins.  A-1 FIX: was hardcoded in main.py.
    # Example: ALLOWED_ORIGINS=http://localhost:5173,https://app.yourdomain.com
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    # ── SMTP (Email) ──
    SMTP_HOST: str = "smtp.email.eu-frankfurt-1.oci.oraclecloud.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@notification.eu-frankfurt-1.oci.oraclecloud.com"
    SMTP_TLS: bool = True

    model_config = {
        "env_file": [".env", "../.env", "backend/.env"],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "case_sensitive": False
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
