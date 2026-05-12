<!-- /api/AGENTS.md -->

# API module scope

This directory contains the FastAPI student frontend backend.

## Auth endpoints (`api/auth.py`)

### Login flow (2-step)
1. `POST /api/auth/check-email` — takes `{email}`, returns `{status}`:
   - `first_time` — no password yet + valid reset code (includes `user_id`, `suggested_name`)
   - `activation_expired` — no password yet + reset code expired
   - `normal` — has password
   - `not_found` — no account for this email
2. `POST /api/auth/request-activation` — resends welcome email with a fresh 7-day reset code; always returns `{status: "sent"}` (prevents enumeration)
3. `POST /api/auth/login` — standard login; raises 403 with detail:
   - `pending_approval`
   - `deadline_expired::<message>`
   - `enrollment_expired` — all active enrollments are past their `expires_at`; master is notified by email
4. `POST /api/auth/init-password` — sets first password; accepts optional `new_name` to rename the user's display name on first setup

### Other auth endpoints
- `GET /api/auth/me` — current user
- `GET /api/auth/enrollments` — list active non-expired enrollments
- `POST /api/auth/select-training` — set `active_master_id` in profile
- `POST /api/auth/request-password-reset` — forgot-password flow (1-day reset code)

## Translations
`GET /api/translations/{lang}` — returns flat dot-notation translation map for the given language (lazy singleton, falls back to `en`).

## Rules
- Keep routes thin and focused on HTTP translation.
- Reuse business logic through `shared/common.py`.
- Do not import anything from `st_shared/`.
- Keep authentication centralized in `api/deps.py`.
