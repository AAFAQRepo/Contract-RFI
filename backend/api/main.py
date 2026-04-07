"""
FastAPI application — main entry point.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.clients import init_minio, init_qdrant, init_redis
from api.routes import documents, chat, review, health, retrieval, auth
from core.auth import get_password_hash

from sqlalchemy import text
from core.database import async_session

async def seed_dummy_user():
    """Seed a real admin user for login (admin@contractrfi.com / admin123)."""
    async with async_session() as db:
        user_id = "00000000-0000-0000-0000-000000000001"
        email = "admin@contractrfi.com"
        
        # Hash the password: admin123
        hashed_pw = get_password_hash("admin123")
        
        await db.execute(text(
            f"INSERT INTO users (id, email, name, password_hash) VALUES ('{user_id}', '{email}', 'Admin', '{hashed_pw}') "
            "ON CONFLICT (id) DO UPDATE SET password_hash = EXCLUDED.password_hash"
        ))
        await db.commit()
        print(f"✅ User {email} seeded/updated")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize service connections on startup."""
    print("🚀 Starting Contract RFI API...")
    init_minio()
    init_qdrant()
    await init_redis()
    await seed_dummy_user()
    print("✅ All services connected")
    yield
    print("👋 Shutting down...")


app = FastAPI(
    title="Contract RFI — Legal AI Platform",
    description="AI-powered contract chat & review with multilingual support",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
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
