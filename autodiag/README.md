# Autodiag Souveraineté

A self-contained micro-service that receives Tally form submissions, scores them, persists results to SQLite, and sends personalized emails via Brevo. Users land on a result page at `/r?t=<jwt>`.

## Architecture

```
main.py            — FastAPI entry point (two routes: /webhook/tally, /r)
webhook_handler.py — Orchestrates parse → score → persist → email
form_parser.py     — Maps Tally UUIDs to structured data (driven by config/form.json)
scorer.py          — Computes per-front scores and derives profile (driven by config/scoring.json)
database.py        — SQLite persistence via SQLModel; deduplicates on response_id
email_service.py   — Renders Markdown/Jinja2 templates and sends via Brevo
token_utils.py     — JWT encode/decode for shareable result page links

config/
  form.json        — Tally question UUIDs and answer scoring weights
  scoring.json     — Profile definitions, normalization factors, and routing rules
  emails/
    user.md        — Email sent to the respondent
    owner.md       — Notification email sent to the owner

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
| `BREVO_API_KEY` | Transactional email |
| `BREVO_FROM` | Sender email address |
| `BREVO_FROM_NAME` | Sender display name |

### Add these to root `.env`

```ini
# Autodiag-specific
WEBHOOK_SECRET=change_me_to_a_long_random_string

OWNER_EMAIL=you@yourdomain.com        # receives a notification on every submission

DIAG_BASE_URL=https://diag.yoga-pro.xyz   # base URL for result page links in emails
DIAG_SHARE_URL=https://diag.yoga-pro.xyz  # base URL for sharing (can differ from DIAG_BASE_URL)
CTA_URL=https://yourdomain.com            # call-to-action link on the result page

# Optional — default shown
DATABASE_PATH=./data/autodiag.db
```

> `BASE_URL` is intentionally not reused — it belongs to the main app (chat.yoga-pro.xyz). The autodiag service uses `DIAG_BASE_URL` to avoid the conflict.

## Run locally

```bash
cd autodiag
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

`load_dotenv` is pointed at the root `.env` (one directory up), so no local `.env` is needed inside `autodiag/`.

Health check: `curl http://localhost:8001/health`

## Test the webhook locally

A sample Tally payload is in `tests/tally-webhook.json`. The simulator sends it to the running server:

```bash
# Basic call — uses the sample payload
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET

# Override the respondent email to avoid sending to the real address in the sample
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET --email you@example.com

# Point at a different host/port
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET --url http://localhost:8001/webhook/tally

# Use a different payload file
python tests/simulate_webhook.py --secret YOUR_WEBHOOK_SECRET --payload tests/my-other-payload.json
```

Expected output on success:

```
POST http://localhost:8001/webhook/tally?secret=...
Payload: tests/tally-webhook.json

HTTP 200
{
  "status": "ok",
  "profile": "clarté"
}
```

A second call with the same payload returns `{"status": "duplicate"}` — the server deduplicates on `responseId`.

## Configure the Tally webhook

1. In your Tally form settings, go to **Integrations → Webhooks**.
2. Set the endpoint URL to:
   ```
   https://diag.yoga-pro.xyz/webhook/tally?secret=YOUR_WEBHOOK_SECRET
   ```
3. Select event type **Form response**.
4. Save. Tally will send a test ping (it is ignored — only `FORM_RESPONSE` events are processed).

The `secret` query parameter must match `WEBHOOK_SECRET` in the root `.env`.

## Config files

### `config/form.json`

Maps Tally question UUIDs to scoring weights. Update this whenever the form changes:

- `email_question_uuid` — UUID of the email input field
- `context_questions` — UUIDs and option labels for situation and felt-constraint questions
- `scored_questions` — list of `{uuid, front, scores: {option_uuid: int}}`
- `disqualification_options` — option UUIDs that short-circuit scoring (no score, no email)

### `config/scoring.json`

Controls profile assignment:

- `fronts` — ordered list of scoring dimensions (`energie`, `attention`, `liens`, `moyens`)
- `normalization` — per-front multiplication factor to equalize raw question counts
- `profile_rules` — ordered rules (evaluated by priority) that map score patterns to profiles
- `profiles` — profile definitions (title, description, CTA text, etc.)

Neither file contains any profile or question names in the Python code — all logic is data-driven.

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

Config and data directories are bind-mounted so you can update `config/form.json` or `config/scoring.json` without rebuilding the image — just restart the container:

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
- [ ] Ensure `autodiag/data/` directory exists on the host (`mkdir -p autodiag/data`)
- [ ] Traefik network `traefik` is running externally
- [ ] DNS for `diag.yoga-pro.xyz` points to the host
- [ ] Tally webhook URL configured with the correct secret
- [ ] Run the simulator against the live URL to confirm end-to-end delivery
