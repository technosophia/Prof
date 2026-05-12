<!-- /frontend/AGENTS.md -->

# Frontend module scope

This directory contains the React student chat SPA (React + Vite).
Built output goes to `../frontend_dist/` and is served directly by FastAPI.
Rebuild after any change: `npm run build`.

## Key pages and flows

### `src/pages/Login.jsx` — 2-step login
1. **Step 1** — email or username → Continue
   - username (no @): skip check, go straight to password form
   - email: POST `/api/auth/check-email` → branches on status
2. **Step 2 branches** (`loginMode` state):
   - `normal` — password form; 403 `enrollment_expired` shows "access expired" message
   - `first_time` — display name + reset code + new password form → `/api/auth/init-password`
   - `activation_expired` — warning + "Send new activation email" → `/api/auth/request-activation`
- Waitlist tab only rendered when `availableLists.length > 0`
- Wrong password shows inline "Forgot password?" link

### `src/lib/api.js` — all API calls
Centralise every backend call here. Auth helpers:
- `auth.checkEmail(email)`, `auth.requestActivation(email)`, `auth.initPassword(userId, code, password, newName?)`
- `auth.enrollments()`, `auth.selectTraining(masterId)`
- `translations.get(lang)` — fetch flat translation map

## Rules
- Keep API calls centralized in `src/lib/api.js`.
- Keep pages lean and push UI pieces into components.
- No backend logic in components.
- After any change: `npm run build` to update `frontend_dist/`.
