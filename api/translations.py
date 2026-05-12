"""Public translations endpoint — serves flat key/value maps to the frontend."""

from fastapi import APIRouter
from core.translate import load_all_translations, VALID_LANGUAGES

router = APIRouter(prefix="/api/translations", tags=["translations"])

_cache: dict | None = None


def _get() -> dict:
    global _cache
    if _cache is None:
        _cache = load_all_translations()
    return _cache


@router.get("/{lang}")
def get_translations(lang: str) -> dict:
    """Return all translation keys for the requested language.

    Falls back to 'en' for unknown language codes. Public — no auth required.
    """
    if lang not in VALID_LANGUAGES:
        lang = "en"
    all_t = _get()
    return all_t.get(lang, all_t.get("en", {}))
