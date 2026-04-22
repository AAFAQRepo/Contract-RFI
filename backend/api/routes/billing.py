import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.auth import get_current_user
from core.limits import PLAN_LIMITS, get_org_subscription, get_current_usage
from core.stripe_utils import create_checkout_session, create_portal_session, WEBHOOK_SECRET
from models.models import User, Subscription

router = APIRouter()

@router.get("/plans")
async def list_plans():
    """List available subscription plans."""
    return [
        {"id": "free", "name": "Free", "price": 0, "limits": PLAN_LIMITS["free"]},
        {"id": "pro", "name": "Pro", "price": 29, "limits": PLAN_LIMITS["pro"]},
        {"id": "enterprise", "name": "Enterprise", "price": 99, "limits": PLAN_LIMITS["enterprise"]},
    ]

@router.get("/subscription")
async def get_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current organization subscription."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="No organization found")
    
    sub = await get_org_subscription(current_user.org_id, db)
    return {
        "plan": sub.plan,
        "status": sub.status,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "stripe_customer_id": sub.stripe_customer_id
    }

@router.get("/usage")
async def get_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current monthly usage vs limits."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="No organization found")
    
    sub = await get_org_subscription(current_user.org_id, db)
    usage = await get_current_usage(current_user.org_id, db)
    limits = PLAN_LIMITS.get(sub.plan, PLAN_LIMITS["free"])
    
    return {
        "plan": sub.plan,
        "usage": {
            "documents": {"used": usage.documents_used, "limit": limits["documents"]},
            "queries": {"used": usage.queries_used, "limit": limits["queries"]},
            "storage_mb": {"used": round(usage.storage_bytes_used / (1024*1024), 2), "limit": limits["max_file_mb"]}
        }
    }

@router.post("/checkout")
async def checkout(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a Stripe Checkout Session."""
    plan_id = payload.get("plan_id")
    if plan_id not in PLAN_LIMITS:
        raise HTTPException(status_code=400, detail="Invalid plan ID")
    
    try:
        session = await create_checkout_session(
            customer_email=current_user.email,
            plan_id=plan_id,
            org_id=str(current_user.org_id)
        )
        return {"checkout_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/portal")
async def portal(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a Stripe Billing Portal session."""
    sub = await get_org_subscription(current_user.org_id, db)
    if not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found")
    
    try:
        session = await create_portal_session(sub.stripe_customer_id)
        return {"portal_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhooks."""
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        org_id = session["metadata"]["org_id"]
        plan_id = session["metadata"]["plan_id"]
        
        # Update subscription
        result = await db.execute(select(Subscription).where(Subscription.org_id == org_id))
        sub = result.scalar_one_or_none()
        if sub:
            sub.plan = plan_id
            sub.status = "active"
            sub.stripe_customer_id = session["customer"]
            sub.stripe_subscription_id = session["subscription"]
            await db.commit()

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        result = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == subscription["id"]))
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "canceled"
            sub.plan = "free"
            await db.commit()

    return {"status": "success"}
