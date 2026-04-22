from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from core.auth import (
    create_access_token, 
    create_refresh_token, 
    verify_password, 
    get_password_hash,
    get_current_user,
    SECRET_KEY, 
    ALGORITHM
)
from core.database import get_db
from models.models import User, Organization

router = APIRouter()

# ── SCHEMAS ──

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    company: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenRefreshRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    company: Optional[str]
    role: str
    is_verified: bool
    onboarding_completed: bool

class OnboardingResponseSchema(BaseModel):
    use_case: str
    company_name: Optional[str] = None
    preferred_language: str = "en"
    selected_plan: str = "free"

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# ── ROUTES ──

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: UserRegister, db: AsyncSession = Depends(get_db)):
    """Register a new user and create their organization."""
    # Check if user exists
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create Org
    org_name = request.company or f"{request.name or 'My'}'s Team"
    org = Organization(name=org_name)
    db.add(org)
    await db.flush() # Get org.id

    # Create User
    new_user = User(
        email=request.email,
        name=request.name,
        password_hash=get_password_hash(request.password),
        company=request.company,
        role="owner", # First user is owner
        org_id=org.id,
        is_verified=False # Should trigger email in production
    )
    db.add(new_user)
    await db.flush()
    
    org.owner_id = new_user.id
    await db.commit()
    await db.refresh(new_user)

    return {"message": "User registered successfully", "user_id": str(new_user.id)}

@router.post("/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and return access + refresh tokens."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login
    user.last_login_at = datetime.utcnow()
    await db.commit()

    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "onboarding_completed": user.onboarding_completed
        }
    }

@router.post("/refresh")
async def refresh_token(request: TokenRefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access token."""
    try:
        payload = jwt.decode(request.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    new_access_token = create_access_token(data={"sub": user.email})
    return {"access_token": new_access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user profile."""
    return current_user

@router.post("/onboarding")
async def save_onboarding(request: OnboardingResponseSchema, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Save onboarding responses and mark user as onboarded."""
    from models.models import OnboardingResponse
    
    # Check if exists
    result = await db.execute(select(OnboardingResponse).where(OnboardingResponse.user_id == current_user.id))
    onboarding = result.scalar_one_or_none()
    
    if not onboarding:
        onboarding = OnboardingResponse(user_id=current_user.id)
        db.add(onboarding)
    
    onboarding.use_case = request.use_case
    onboarding.company_name = request.company_name
    onboarding.preferred_language = request.preferred_language
    onboarding.selected_plan = request.selected_plan
    onboarding.completed_at = datetime.utcnow()
    
    current_user.onboarding_completed = True
    if request.company_name:
        current_user.company = request.company_name
        
    await db.commit()
    return {"message": "Onboarding completed"}
@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Generate a reset token and 'send' an email."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if user:
        # In real app: generate unique random string, save to DB with expiry
        token = f"reset_{user.id}_{int(datetime.utcnow().timestamp())}" 
        user.reset_token = token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        await db.commit()
        
        # Simulate email
        print(f"📧 EMAIL: Password reset for {user.email}. Link: /reset-password?token={token}")
    
    return {"message": "If your email is registered, you will receive a reset link."}

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid token."""
    result = await db.execute(select(User).where(User.reset_token == request.token))
    user = result.scalar_one_or_none()
    
    if not user or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    user.password_hash = get_password_hash(request.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()
    
    return {"message": "Password updated successfully"}
