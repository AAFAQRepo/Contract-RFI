from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.auth import get_current_user
from models.models import User, Document, Chat, UsageRecord, Conversation
from core.limits import get_org_subscription, get_current_usage, PLAN_LIMITS

router = APIRouter()

@router.get("/stats")
async def get_workspace_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aggregate workspace statistics for the dashboard."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="No organization found")

    # 1. Monthly Usage
    usage = await get_current_usage(current_user.org_id, db)
    sub = await get_org_subscription(current_user.org_id, db)
    limits = PLAN_LIMITS.get(sub.plan, PLAN_LIMITS["free"])

    # 2. Total Documents Count
    doc_count_res = await db.execute(
        select(func.count(Document.id)).where(Document.user_id == current_user.id)
    )
    total_docs = doc_count_res.scalar() or 0

    # 3. Total Messages Count
    msg_count_res = await db.execute(
        select(func.count(Chat.id)).where(Chat.user_id == current_user.id)
    )
    total_messages = msg_count_res.scalar() or 0

    return {
        "usage": {
            "documents": {"used": usage.documents_used, "limit": limits["documents"]},
            "queries": {"used": usage.queries_used, "limit": limits["queries"]},
        },
        "totals": {
            "documents": total_docs,
            "messages": total_messages
        },
        "plan": sub.plan
    }

@router.get("/activity")
async def get_recent_activity(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Fetch recent document uploads and chat interactions."""
    # Fetch recent documents
    doc_res = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(desc(Document.created_at))
        .limit(limit // 2)
    )
    recent_docs = doc_res.scalars().all()

    # Fetch recent conversations
    conv_res = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(desc(Conversation.updated_at))
        .limit(limit // 2)
    )
    recent_convs = conv_res.scalars().all()

    # Combine and sort (manual sort for simplicity in MVP)
    activity = []
    for d in recent_docs:
        activity.append({
            "type": "document",
            "id": str(d.id),
            "title": d.filename,
            "timestamp": d.created_at.isoformat(),
            "status": d.status
        })
    for c in recent_convs:
        activity.append({
            "type": "chat",
            "id": str(c.id),
            "title": c.title,
            "timestamp": c.updated_at.isoformat()
        })
    
    activity.sort(key=lambda x: x["timestamp"], reverse=True)
    return activity[:limit]

@router.get("/usage")
async def get_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Return flat usage data for the SubscriptionContext."""
    if not current_user.org_id:
        return {"documents": 0, "queries": 0, "limit": 5, "plan": "free"}

    usage = await get_current_usage(current_user.org_id, db)
    sub = await get_org_subscription(current_user.org_id, db)
    limits = PLAN_LIMITS.get(sub.plan, PLAN_LIMITS["free"])

    return {
        "documents": usage.documents_used,
        "queries": usage.queries_used,
        "limit": limits["documents"],
        "plan": sub.plan,
    }
