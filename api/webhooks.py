"""Payhip Webhook API endpoints."""

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from api.deps import get_current_user
from modules.payhip_webhook.payhip_webhook import get_payhip_webhook_manager

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class SimulatePayhipRequest(BaseModel):
    email: str
    product_key: str
    event_type: str = "paid"
    customer_name: str = ""


@router.post("/payhip")
async def receive_payhip_webhook(
    request: Request,
    x_payhip_signature: str | None = Header(None, alias="x-payhip-signature"),
):
    """Receive Payhip webhook and create user if applicable."""
    body = await request.body()
    raw_payload = body.decode("utf-8")

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as e:
        return {"error": "Invalid JSON", "detail": str(e)}, 400

    manager = get_payhip_webhook_manager()

    if x_payhip_signature:
        if not manager.verify_signature(body, x_payhip_signature):
            return {"error": "Invalid signature"}, 401

    status_code, message = manager.process_webhook(payload, raw_payload)

    if status_code >= 400:
        return {"error": message}, status_code

    return {"status": message}, status_code


@router.post("/payhip/simulate")
async def simulate_payhip_webhook(
    payload: SimulatePayhipRequest,
    current_user: dict = Depends(get_current_user),
):
    """Simulate a Payhip webhook event for testing (admin/master only)."""
    if current_user.get("role") not in ("admin", "master"):
        raise HTTPException(status_code=403, detail="Forbidden")

    simulated = {
        "type": payload.event_type,
        "email": payload.email,
        "product_link": payload.product_key,
        "id": f"sim_{payload.email.split('@')[0]}",
    }
    raw = json.dumps(simulated)

    manager = get_payhip_webhook_manager()
    status_code, message = manager.process_webhook(simulated, raw)

    return {"status": message, "http_code": status_code, "payload_sent": simulated}
