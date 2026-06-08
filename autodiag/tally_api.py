"""Tally API client for autodiag aggregate reporting."""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

TALLY_API_BASE_URL = "https://api.tally.so"


class TallyApiError(RuntimeError):
    """Raised when Tally cannot return submissions for the configured form."""


def fetch_all_submissions_with_questions(
    *,
    api_key: str,
    form_id: str,
    limit: int = 500,
    timeout: int = 20,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return all completed submissions and question metadata, following pagination."""
    if not api_key:
        raise TallyApiError("TALLY_API_KEY is required")
    if not form_id:
        raise TallyApiError("form_id is required")

    http = session or requests.Session()
    headers = {"Authorization": f"Bearer {api_key}"}
    submissions: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    page = 1

    while True:
        logger.info("Fetching Tally submissions for form=%s page=%s", form_id, page)
        response = http.get(
            f"{TALLY_API_BASE_URL}/forms/{form_id}/submissions",
            headers=headers,
            params={"page": page, "limit": limit, "filter": "completed"},
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise TallyApiError(
                f"Tally API returned HTTP {response.status_code}: {response.text[:300]}"
            )

        payload = response.json()
        page_submissions = payload.get("submissions", [])
        if not isinstance(page_submissions, list):
            raise TallyApiError("Tally API response did not contain a submissions list")
        submissions.extend(page_submissions)
        if not questions and isinstance(payload.get("questions"), list):
            questions = payload["questions"]

        if not payload.get("hasMore"):
            break
        page += 1

    logger.info("Fetched %d Tally submissions for form=%s", len(submissions), form_id)
    return submissions, questions


def fetch_all_submissions(**kwargs) -> list[dict[str, Any]]:
    """Backward-compatible helper that returns only submission objects."""
    submissions, _questions = fetch_all_submissions_with_questions(**kwargs)
    return submissions
