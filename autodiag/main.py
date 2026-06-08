"""FastAPI entry point for the autodiag micro-service."""

import base64
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Query, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import init_db
from token_utils import decode_result_token
from webhook_handler import handle_tally_webhook
from tally_aggregate import aggregate_submissions, load_form_config, load_scoring_config
from tally_api import TallyApiError, fetch_all_submissions_with_questions

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_SCORING_CONFIG = Path(__file__).parent / "config" / "scoring.json"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("autodiag ready")
    yield


app = FastAPI(title="Autodiag Souveraineté", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/tally")
async def tally_webhook(request: Request, tally_signature: str | None = Header(default=None)):
    signing_secret = os.environ.get("WEBHOOK_SECRET", "")
    body = await request.body()

    if signing_secret:
        expected_sig = base64.b64encode(
            hmac.new(signing_secret.encode(), body, hashlib.sha256).digest()
        ).decode()
        if not tally_signature or not hmac.compare_digest(tally_signature, expected_sig):
            logger.warning(
                "Webhook signature mismatch — got: %s | expected: %s | secret_len: %d | body_len: %d",
                tally_signature, expected_sig, len(signing_secret), len(body),
            )
            raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body)

    if payload.get("eventType") != "FORM_RESPONSE":
        return {"status": "ignored", "eventType": payload.get("eventType")}

    return handle_tally_webhook(payload)


@app.get("/radar", response_class=HTMLResponse)
def radar_page(request: Request):
    api_key = os.environ.get("TALLY_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="TALLY_API_KEY is not configured")

    form_config = load_form_config()
    scoring_config = load_scoring_config()
    form_id = form_config["form_id"]

    try:
        submissions, questions = fetch_all_submissions_with_questions(api_key=api_key, form_id=form_id)
    except TallyApiError as exc:
        logger.exception("Unable to fetch Tally submissions for form %s", form_id)
        raise HTTPException(status_code=502, detail=str(exc))

    aggregate = aggregate_submissions(
        submissions,
        questions=questions,
        form_config=form_config,
        scoring_config=scoring_config,
    )
    profile_names = {
        key: profile.get("name", key)
        for key, profile in scoring_config["profiles"].items()
    }
    chart_labels = [aggregate.front_labels.get(front, front) for front in aggregate.fronts]
    chart_values = [aggregate.average_scores[front] for front in aggregate.fronts]
    chart_stds = [aggregate.std_scores.get(front, 0) for front in aggregate.fronts]

    return templates.TemplateResponse(
        request=request,
        name="radar.html",
        context={
            "aggregate": aggregate,
            "profile_names": profile_names,
            "front_labels": aggregate.front_labels,
            "chart_labels": chart_labels,
            "chart_values": chart_values,
            "chart_stds": chart_stds,
            "chart_max": max(aggregate.max_scores.values()) if aggregate.max_scores else 12,
        },
    )


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
        request=request,
        name="result.html",
        context={
            "profile": profile,
            "scores": scores,
            "felt_constraint": felt,
            "felt_label": front_to_label.get(felt, felt),
            "situation": data.get("situation", ""),
            "cta_url": os.environ.get("CTA_URL", "#"),
        },
    )
