# Autodiag Souveraineté

A self-contained micro-service that receives Tally form submissions, scores them, persists results to SQLite, and sends personalized emails via Brevo. Users land on a result page at `/r?t=<jwt>`.

## Architecture

```
main.py            — FastAPI entry point (two routes: /webhook/tally, /r)
webhook_handler.py — Orchestrates parse → score → persist → email
form_parser.py     — Maps Tally question keys to structured data (driven by config/form.json)
scorer.py          — Computes per-front scores and derives profile (driven by config/scoring.json)
database.py        — SQLite persistence via SQLModel; deduplicates on response_id
email_service.py   — Renders Markdown/Jinja2 templates and sends via Brevo
token_utils.py     — JWT encode/decode for shareable result page links

config/
  form.json        — Tally question keys and answer scoring weights
  scoring.json     — Profile definitions, normalization factors, and routing rules
  emails/
    user.md        — Email sent to the respondent (includes result link + share link)
    owner.md       — Notification email sent to the owner (includes result link)

data/              — SQLite database file (gitignored, mounted as a volume in Docker)
templates/         — Jinja2 HTML for the result page
tests/             — Sample Tally payloads and webhook simulator
```

## Environment variables

All variables are read from the **root `.env`** (one level above `autodiag/`). The service shares that file with the rest of the platform.

### Already present in root `.env`

| Variable | Used for |
|---|---|
| `JWT_SECRET` | Signing result page tokens |
| `BREVO_API_KEY` | Transactional email via Brevo |
| `BREVO_FROM` | Sender email address |
| `BREVO_FROM_NAME` | Sender display name |

### Add these to root `.env`

```ini
# Webhook signature — must match the "Signing secret" set in Tally
WEBHOOK_SECRET=f27b8094-9ddf-4cc5-846e-1927cbc10d5c

OWNER_EMAIL=you@yourdomain.com         # receives a notification on every submission

DIAG_BASE_URL=https://diag.yoga-pro.xyz    # base URL for result page links sent in emails
DIAG_SHARE_URL=https://tally.so/r/ODEX18  # Tally form URL — put in user email "share with a friend" link
CTA_URL=https://yourdomain.com             # call-to-action button on the result page (omit to hide the button)

# Optional — default shown
DATABASE_PATH=./data/autodiag.db
```

> `BASE_URL` is intentionally not reused — it belongs to the main app (`chat.yoga-pro.xyz`). The autodiag service uses `DIAG_BASE_URL` to avoid the conflict.

## Run locally

```bash
cd autodiag
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

`load_dotenv` is pointed at the root `.env` (one directory up), so no local `.env` is needed inside `autodiag/`.

Health check: `curl http://localhost:8001/health`

## Test the webhook locally

A sample Tally payload is in `tests/tally-webhook.json`. The simulator computes the HMAC-SHA256 signature and sends it exactly as Tally would.

```bash
# Basic call — same payload, will be rejected as duplicate if already processed
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET

# --new-id generates a fresh responseId each time → bypasses the duplicate guard
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET --new-id

# --email overrides the respondent address so you don't spam the sample address
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET --new-id --email you@example.com

# Point at a different host/port
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET --new-id --url http://localhost:8001/webhook/tally

# Use a different payload file
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET --new-id --payload tests/other.json
```

Expected output on success:

```
  New responseId: 9N1vVgV → A3F8C2E
  Overriding email: ybabel@free.fr → you@example.com
POST http://localhost:8001/webhook/tally
Payload: tests/tally-webhook.json
Signature: sha256=4b3e1a...

HTTP 200
{
  "status": "ok",
  "profile": "autonome_sans_appui"
}
```

Calling without `--new-id` a second time returns `{"status": "duplicate"}` — useful to verify the deduplication guard works.

## Configure the Tally webhook

1. In your Tally form settings, go to **Integrations → Webhooks**.
2. Set the **Endpoint URL** to:
   ```
   https://diag.yoga-pro.xyz/webhook/tally
   ```
3. Set the **Signing secret** to the value of `WEBHOOK_SECRET` in your `.env`.
4. Select event type **Form response** and save.

Tally computes `HMAC-SHA256(body, signing_secret)`, base64-encodes the digest, and sends it in the header `tally-signature: <base64>`. The server verifies this header on every request. The secret never appears in the URL.

Tally sends a test ping on save — it is ignored (only `FORM_RESPONSE` events are processed).

## Pre-fill the email field in the URL

Tally supports pre-filling form fields via query parameters. The email field has the key `V82pLg`, so pass it directly in the URL:

```
https://tally.so/r/ODEX18?V82pLg=prenom@exemple.com
```

The email input will be pre-filled when the form opens. Useful when sending the form to people whose email you already have (newsletter, CRM export, etc.).

## Config files

### `config/form.json`

Maps Tally question keys to scoring weights. The question keys are the short alphanumeric suffixes Tally uses in webhook payloads (e.g. `XqZ5xg` → field key `question_XqZ5xg`). Update this file whenever the form changes — no code change needed.

- `email_question_key` — key suffix of the email input field
- `context_questions` — key suffixes and option UUIDs for the situation and felt-constraint questions
- `scored_questions` — list of `{key, front, scores: {option_uuid: int}}`
- `disqualification_options` — option UUIDs that short-circuit scoring (no score, no email sent)

### `config/scoring.json`

Controls profile assignment:

- `fronts` — ordered list of scoring dimensions (`energie`, `attention`, `liens`, `moyens`)
- `normalization` — per-front multiplication factor to equalize raw question counts
- `profile_rules` — ordered rules (evaluated by priority) that map score patterns to profiles
- `profiles` — profile definitions (name, tagline, body text, CTA copy, etc.)

Neither config file contains any profile names or question keys in the Python code — all logic is data-driven.

## Deploy with Docker Compose

The service is defined in the root `docker-compose.yml` under the `autodiag` service, exposed behind Traefik at `diag.yoga-pro.xyz`. It reads variables directly from the root `.env` via `env_file: ./.env` — no separate `autodiag/.env` is used.

```bash
# First build
docker compose build autodiag

# Start (or restart after a config change)
docker compose up -d autodiag

# Tail logs
docker compose logs -f autodiag
```

Config and data directories are bind-mounted so you can update `config/form.json` or `config/scoring.json` without rebuilding the image:

```bash
docker compose restart autodiag
```

The SQLite database persists in `autodiag/data/autodiag.db` on the host.

### Rebuild after code changes

```bash
docker compose build autodiag && docker compose up -d autodiag
```

### First deploy checklist

- [ ] Add the autodiag-specific variables to the root `.env` (see above)
- [ ] Ensure `autodiag/data/` exists on the host: `mkdir -p autodiag/data`
- [ ] Traefik network `traefik` is running externally
- [ ] DNS for `diag.yoga-pro.xyz` points to the host
- [ ] Tally webhook configured: correct endpoint URL + signing secret
- [ ] Run the simulator against the live URL to confirm end-to-end delivery:
  ```bash
  python tests/simulate_webhook.py --secret YOUR_SECRET --new-id --email you@example.com \
    --url https://diag.yoga-pro.xyz/webhook/tally
  ```
