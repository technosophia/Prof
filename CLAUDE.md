# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Backend
uvicorn api:app --host 0.0.0.0 --port 8000 --reload   # FastAPI + React frontend (app.yoga-pro.xyz)
streamlit run prof.py                                    # Streamlit admin backoffice (coach.yoga-pro.xyz)

# Frontend — rebuild after ANY change to frontend/src/
cd frontend && npm run build          # output goes to ../frontend_dist/ (served by FastAPI)
tools/restart-frontend.sh             # compile + restart uvicorn in one step

# Tests
pytest shared/tests/                  # fast unit tests only — run these
pytest                                # full E2E suite (Playwright + real server) — slow, ask user for results
pytest shared/tests/test_enrollment_expiry.py   # single file
pytest -k "test_past_expiry"          # single test by name
pytest -m unit                        # by marker (unit / integration / slow)
```

## Architecture

```
/core        — meta-code: logging, database, config, translations. No dependencies.
/shared      — business logic shared across everything: users, conversations, LLM, prompts, email.
/modules     — self-contained functional units (plug-and-play, deleting one breaks nothing).
/api         — FastAPI routes (thin HTTP layer, delegates to shared/).
/frontend    — React/Vite SPA, served from frontend_dist/ by FastAPI.
prof.py      — Streamlit admin entry point.
```

**Dependency rule:** `core ← shared ← {modules, api, frontend}`. Modules never depend on each other.

## Key design patterns

### Module system
Each module is a directory in `/modules/` with a `module.json` that declares injection points. The app discovers and loads modules automatically. Deleting a module directory leaves the rest intact.

### User & enrollment model
Three roles: `admin → master → normal`. A normal user can be enrolled with multiple masters via the `user_enrollments` table (`user_id`, `master_id`, `product_key`, `enrolled_at`, `is_active`, `expires_at`). Active training stored in `UserTable.profile["active_master_id"]`.

Expiry lives at the **enrollment level** (`expires_at`), not on the user. `get_user_enrollments()` silently filters expired rows. On login, `authenticate_user_with_status()` checks enrollment expiry after password verification and returns `"enrollment_expired"` — which also triggers a master alert email.

### Auth flow (2-step login)
`POST /api/auth/check-email` → `first_time | activation_expired | normal | not_found`  
Then `POST /api/auth/login` which can return 403 `enrollment_expired | deadline_expired::<msg> | pending_approval`.

### Payhip webhook
`POST /webhooks/payhip` (no `/api` prefix — Traefik routes by host). Creates user or adds enrollment. `master_product_keys` table maps product permalink → master. `enrollment_duration_days` on that table drives `expires_at` computation at webhook time.

### Translations
`core/translate.py`: `load_all_translations()` walks the project for `*/translations/{en,fr}.json`. Flat dot-notation keys. Exposed to the frontend via `GET /api/translations/{lang}`. Email templates use the same system via `shared/transactional_email.py`.

### Singletons
`UserManager`, `ConversationManager`, etc. are singletons accessed via `shared/common.py`. In tests: reset with `UserManager._instance = None` in `setup_method` / `teardown_method`.

### Configuration layering
`config.json` (defaults) → `local_config.json` (prod overrides, gitignored) → `test_config.json` (test overrides). Secrets in `.env`.

## Testing patterns

Unit tests mock the DB entirely — no real database needed:
```python
mgr.db = MagicMock()
mgr.db.get_session = MagicMock(return_value=_ctx_manager)
mgr._ensure_table_exists = MagicMock()
```

**Faking time** — `shared/users.py` uses `from datetime import datetime`, so patch `shared.users.datetime` with a subclass:
```python
class FakeDatetime(datetime):
    _now = datetime(2026, 1, 1)
    @classmethod
    def utcnow(cls): return cls._now

with patch("shared.users.datetime", FakeDatetime):
    FakeDatetime._now = datetime(2030, 6, 1)
    ...
```

**Patching locally-imported functions** — functions imported inside a method body must be patched on their source module, not on the caller:
```python
import shared.transactional_email as te
with patch.object(te, "send_enrollment_expired_alert", return_value=(True, "ok")):
    ...
```

## Streamlit pitfalls
- Never use duplicate keys for widgets.
- Use `st.session_state` for any state that must survive `st.rerun()` (triggered after every button click).
- Use `@st.cache_resource` for singletons/managers loaded once.

## Required environment variables
```
MYSQL_HOST / MYSQL_PORT / MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DRIVER
JWT_SECRET
APP_URL                  # https://app.yoga-pro.xyz  (used in email links)
BREVO_API_KEY            # transactional email
BREVO_FROM               # verified sender address
PAYHIP_API_KEY           # webhook HMAC secret
MAILER_LITE_API          # optional — MailerLite onboarding automation
MAILER_LITE_GROUP_ID     # optional
```
LLM keys: `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, etc. (only the ones in use need to be set).
