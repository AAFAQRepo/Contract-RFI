from datetime import datetime
from fastapi import HTTPException, status, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.auth import get_current_user
from models.models import User, Organization, Subscription, UsageRecord

PLAN_LIMITS = {
    "free":       {"documents": 50,  "queries": 500,  "max_file_mb": 25,  "ocr": True},
    "pro":        {"documents": 200, "queries": 2000, "max_file_mb": 100, "ocr": True},
    "enterprise": {"documents": -1,  "queries": -1,   "max_file_mb": 500, "ocr": True},
}

async def get_org_subscription(org_id: str, db: AsyncSession) -> Subscription:
    """Get or create the free subscription for an organization."""
    result = await db.execute(select(Subscription).where(Subscription.org_id == org_id))
    sub = result.scalar_one_or_none()
    
    if not sub:
        sub = Subscription(org_id=org_id, plan="free", status="active")
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
    return sub

async def get_current_usage(org_id: str, db: AsyncSession) -> UsageRecord:
    """Get the usage record for the current month."""
    now = datetime.utcnow()
    period_start = datetime(now.year, now.month, 1)
    
    result = await db.execute(
        select(UsageRecord).where(
            UsageRecord.org_id == org_id,
            UsageRecord.period_start == period_start
        )
    )
    usage = result.scalar_one_or_none()
    
    if not usage:
        usage = UsageRecord(org_id=org_id, period_start=period_start)
        db.add(usage)
        await db.commit()
        await db.refresh(usage)
    return usage

def check_usage_limit(resource: str):
    """
    FastAPI dependency factory. 
    Usage: Depends(check_usage_limit("documents"))
    """
    async def dependency(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        if not user.org_id:
            raise HTTPException(status_code=403, detail="User not part of any organization")
        
        sub = await get_org_subscription(user.org_id, db)
        usage = await get_current_usage(user.org_id, db)
        
        limits = PLAN_LIMITS.get(sub.plan, PLAN_LIMITS["free"])
        limit_val = limits.get(resource)
        
        # -1 means unlimited
        if limit_val == -1:
            return True
            
        current_val = getattr(usage, f"{resource}_used", 0)
        
        if current_val >= limit_val:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "limit_exceeded",
                    "resource": resource,
                    "limit": limit_val,
                    "used": current_val,
                    "upgrade_url": "/billing"
                }
            )
        return True
        
    return dependency

async def increment_usage(org_id: str, resource: str, db: AsyncSession, amount: int = 1):
    """Increment the usage count for a resource."""
    usage = await get_current_usage(org_id, db)
    attr = f"{resource}_used"
    if hasattr(usage, attr):
        setattr(usage, attr, getattr(usage, attr) + amount)
        await db.commit()
