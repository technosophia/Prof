"""FastAPI entry point for the autodiag micro-service."""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from database import init_db
from token_utils import decode_result_token
from webhook_handler import handle_tally_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SCORING_CONFIG = Path(__file__).parent / "config" / "scoring.json"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("autodiag ready")
    yield


app = FastAPI(title="Autodiag Souveraineté", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/tally")
async def tally_webhook(request: Request, secret: str = Query(...)):
    expected = os.environ.get("WEBHOOK_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

    payload = await request.json()

    if payload.get("eventType") != "FORM_RESPONSE":
        return {"status": "ignored", "eventType": payload.get("eventType")}

    return handle_tally_webhook(payload)


@app.get("/r", response_class=HTMLResponse)
def result_page(request: Request, t: str = Query(...)):
    try:
        data = decode_result_token(t)
    except Exception:
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré.")

    with open(_SCORING_CONFIG) as f:
        scoring = json.load(f)

    profile_key = data["profile"]
    if profile_key not in scoring["profiles"]:
        raise HTTPException(status_code=400, detail="Profil inconnu.")

    profile = scoring["profiles"][profile_key]

    # Build a front → French label map from profile definitions
    front_to_label = {
        p["front"]: p["front_label"]
        for p in scoring["profiles"].values()
        if p.get("front")
    }

    scores = {
        "energie": data["e"],
        "attention": data["a"],
        "liens": data["l"],
        "moyens": data["m"],
    }
    felt = data.get("felt", "")

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "profile": profile,
            "scores": scores,
            "felt_constraint": felt,
            "felt_label": front_to_label.get(felt, felt),
            "situation": data.get("situation", ""),
            "cta_url": os.environ.get("CTA_URL", "#"),
        },
    )
