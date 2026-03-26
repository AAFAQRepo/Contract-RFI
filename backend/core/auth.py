from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from models.models import User

# Hardcoded dummy user ID for development (matches seeded DB user)
DUMMY_USER_ID = "00000000-0000-0000-0000-000000000001"

async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    """
    Dependency that returns a dummy development user.
    In production, this would decode a JWT and fetch the user from DB.
    """
    # Fetch the dummy user from DB (ensures the model is valid)
    result = await db.execute(text("SELECT * FROM users WHERE id = :uid"), {"uid": DUMMY_USER_ID})
    row = result.fetchone()
    
    if not row:
        # Fallback if seed failed
        return User(id=DUMMY_USER_ID, email="admin@contractrfi.com")
        
    return User(
        id=row.id,
        email=row.email
    )
