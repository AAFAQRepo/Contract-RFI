"""
FastAPI application — main entry point.

Fixes applied (from audit):
  CRITICAL-6 — Removed hardcoded admin seed from the startup lifespan.
               seed_dummy_user() reset the password to 'admin123' on every
               deploy, including production. Use a one-time CLI command or
               Alembic data migration for initial users instead.
  A-1        — CORS origins are now driven by the ALLOWED_ORIGINS env var
               instead of being hardcoded to 'http://localhost:5173'.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.clients import init_minio, init_qdrant, init_redis
from api.routes import documents, chat, review, health, retrieval, auth, workspace
from core.config import get_settings

from core.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize service connections on startup."""
    print("🚀 Starting Contract RFI API...")
    init_minio()
    init_qdrant()
    await init_redis()
    # CRITICAL-6 FIX: seed_dummy_user() removed.
    # It seeded admin@contractrfi.com / admin123 on EVERY startup via
    # ON CONFLICT DO UPDATE — resetting any rotated password in production.
    # Use a one-time Alembic data migration or CLI command for initial users.
    print("✅ All services connected")
    yield
    print("👋 Shutting down...")


app = FastAPI(
    title="Contract RFI — Legal AI Platform",
    description="AI-powered contract chat & review with multilingual support",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — A-1 FIX: driven by env var, not hardcoded to localhost:5173 ───────
# Set ALLOWED_ORIGINS in .env as a comma-separated list:
#   ALLOWED_ORIGINS=http://localhost:5173,https://app.yourdomain.com
_raw_origins = getattr(settings, "ALLOWED_ORIGINS", "http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(review.router, prefix="/api/review", tags=["Review"])
app.include_router(retrieval.router, prefix="/api", tags=["Retrieval"])

app.include_router(workspace.router, prefix="/api/workspace", tags=["Workspace"])
