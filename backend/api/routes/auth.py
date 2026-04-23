from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from pydantic import BaseModel, EmailStr, ConfigDict
import random
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
from core.rate_limit import limiter
from core.email import send_otp_email

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
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    email: str
    name: Optional[str] = None
    company: Optional[str] = None
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

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str

class ResendOTPRequest(BaseModel):
    email: EmailStr

# ── ROUTES ──

@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    data: UserRegister, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user and create their organization."""
    normalized_email = data.email.lower().strip()
    
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
        
    # Check if user exists
    existing = await db.execute(select(User).where(User.email == normalized_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create Org
    org_name = data.company or f"{data.name or 'My'}'s Team"
    org = Organization(name=org_name)
    db.add(org)
    await db.flush() # Get org.id

    # Generate 6-digit OTP
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])

    # Create User
    new_user = User(
        email=normalized_email,
        name=data.name,
        password_hash=get_password_hash(data.password),
        company=data.company,
        role="owner", # First user is owner
        org_id=org.id,
        is_verified=False,
        verification_token=otp
    )
    db.add(new_user)
    await db.flush()
    
    org.owner_id = new_user.id
    await db.commit()
    await db.refresh(new_user)

    # Send verification email in background
    background_tasks.add_task(send_otp_email, normalized_email, otp)

    return {"message": "User registered successfully", "user_id": str(new_user.id), "email": normalized_email}

@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and return access + refresh tokens."""
    normalized_email = data.email.lower().strip()
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your account first."
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
@limiter.limit("3/minute")
async def forgot_password(request: Request, data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Generate a reset token and 'send' an email."""
    normalized_email = data.email.lower().strip()
    result = await db.execute(select(User).where(User.email == normalized_email))
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
@limiter.limit("3/minute")
async def reset_password(request: Request, data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid token."""
    result = await db.execute(select(User).where(User.reset_token == data.token))
    user = result.scalar_one_or_none()
    
    if not user or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    user.password_hash = get_password_hash(data.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()
    
    return {"message": "Password updated successfully"}

@router.patch("/me", response_model=UserResponse)
async def update_profile(
    request: ProfileUpdate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update user profile details."""
    if request.name is not None:
        current_user.name = request.name
    if request.company is not None:
        current_user.company = request.company
    
    await db.commit()
    await db.refresh(current_user)
    return current_user

@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Securely change user password."""
    if not verify_password(request.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid old password")
    
    current_user.password_hash = get_password_hash(request.new_password)
    await db.commit()
    return {"message": "Password updated successfully"}

@router.get("/check-email")
@limiter.limit("10/minute")
async def check_email(request: Request, email: EmailStr, db: AsyncSession = Depends(get_db)):
    """Check if an email is already registered. Returns available: bool"""
    normalized_email = email.lower().strip()
    result = await db.execute(select(User).where(User.email == normalized_email))
    existing = result.scalar_one_or_none()
    return {"available": existing is None}

@router.post("/verify-otp")
@limiter.limit("10/minute")
async def verify_otp(request: Request, data: VerifyOTPRequest, db: AsyncSession = Depends(get_db)):
    """Verify the 6-digit OTP and activate the user account."""
    normalized_email = data.email.lower().strip()
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.is_verified:
        return {"message": "Account already verified", "verified": True}
        
    if user.verification_token != data.otp:
        raise HTTPException(status_code=400, detail="Invalid verification code")
        
    user.is_verified = True
    user.verification_token = None
    await db.commit()
    
    return {"message": "Email verified successfully", "verified": True}

@router.post("/resend-otp")
@limiter.limit("2/minute")
async def resend_otp(
    request: Request,
    data: ResendOTPRequest, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Regenerate and resend a 6-digit OTP."""
    normalized_email = data.email.lower().strip()
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.is_verified:
        return {"message": "Account already verified"}
        
    # Generate new OTP
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    user.verification_token = otp
    await db.commit()
    
    # Send verification email in background
    background_tasks.add_task(send_otp_email, normalized_email, otp)
    
    return {"message": "Verification code resent"}
