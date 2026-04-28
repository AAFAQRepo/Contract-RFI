"""
FastAPI application — main entry point.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.clients import init_minio, init_qdrant, init_redis
from api.routes import documents, chat, review, health, retrieval, auth, workspace
from core.auth import get_password_hash

from sqlalchemy import text
from core.database import async_session
from core.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

async def seed_dummy_user():
    """Seed a real admin user for login (admin@contractrfi.com / admin123)."""
    async with async_session() as db:
        user_id = "00000000-0000-0000-0000-000000000001"
        email = "admin@contractrfi.com"
        
        # Hash the password: admin123
        hashed_pw = get_password_hash("admin123")
        
        await db.execute(text(
            "INSERT INTO users (id, email, name, password_hash) "
            "VALUES (:id, :email, :name, :password_hash) "
            "ON CONFLICT (id) DO UPDATE SET password_hash = EXCLUDED.password_hash"
        ), {"id": user_id, "email": email, "name": "Admin", "password_hash": hashed_pw})
        await db.commit()
        print(f"✅ User {email} seeded/updated")

async def auto_migrate():
    """Ensure the database schema has the required columns for the RAG Evolution."""
    async with async_session() as db:
        print("🛠️ Running auto-migrations...")
        try:
            # Add chunk_index to chunks if it doesn't exist
            await db.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_index INTEGER;"))
            # Add thinking to chats if it doesn't exist
            await db.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS thinking TEXT;"))
            # Add Ragas scores
            await db.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS faithfulness_score FLOAT;"))
            await db.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS relevancy_score FLOAT;"))
            await db.commit()
            print("✅ Database schema is up to date.")
        except Exception as e:
            print(f"⚠️ Auto-migration failed (this is expected if already applied): {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize service connections on startup."""
    print("🚀 Starting Contract RFI API...")
    init_minio()
    init_qdrant()
    await init_redis()
    await auto_migrate()
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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

app.include_router(workspace.router, prefix="/api/workspace", tags=["Workspace"])
