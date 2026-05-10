"""Payhip Webhook API endpoints."""

import json

from fastapi import APIRouter, Header, Request

from modules.payhip_webhook.payhip_webhook import get_payhip_webhook_manager

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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
