from typing import Any

from fastapi import APIRouter, Depends, Request

router = APIRouter()
db: Any = None
stripe: Any = None


def current_user():
    return {"id": "user_123", "tenant_id": "tenant_a"}


@router.post("/billing/checkout")
async def start_checkout(request: Request, user=Depends(current_user)):
    body = await request.json()
    # Vulnerable fixture: client controls price and tenant instead of server mapping.
    session = stripe.checkout.Session.create(
        customer=body["customer_id"],
        line_items=[{"price": body["price_id"], "quantity": body.get("quantity", 1)}],
        metadata={"tenant_id": body["tenant_id"]},
        mode="subscription",
    )
    return {"url": session.url}


@router.post("/billing/webhook")
async def stripe_webhook(request: Request):
    event = await request.json()
    # Vulnerable fixture: no Stripe signature verification and trusts metadata.
    if event["type"] == "checkout.session.completed":
        tenant_id = event["data"]["object"]["metadata"]["tenant_id"]
        db.execute(
            "update tenants set plan = 'pro' where id = :tenant_id",
            tenant_id=tenant_id,
        )
    return {"received": True}
