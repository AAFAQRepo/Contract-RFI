import stripe
import os
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
DOMAIN = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Plan ID mapping (Stripe Price IDs)
STRIPE_PRICES = {
    "pro": os.getenv("STRIPE_PRICE_PRO", "price_pro_placeholder"),
    "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE", "price_ent_placeholder"),
}

async def create_checkout_session(customer_email: str, plan_id: str, org_id: str):
    """Create a Stripe Checkout session for a subscription."""
    price_id = STRIPE_PRICES.get(plan_id)
    if not price_id:
        raise ValueError(f"Invalid plan ID: {plan_id}")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price": price_id,
            "quantity": 1,
        }],
        mode="subscription",
        customer_email=customer_email,
        success_url=f"{DOMAIN}/billing?success=true&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{DOMAIN}/billing?canceled=true",
        metadata={
            "org_id": org_id,
            "plan_id": plan_id
        }
    )
    return session

async def create_portal_session(stripe_customer_id: str):
    """Create a Stripe Billing Portal session."""
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=f"{DOMAIN}/billing",
    )
    return session
