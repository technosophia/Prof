# Payhip Webhook Module

## Purpose
Auto-subscription webhook for Payhip: when a customer purchases a product, a user account
is created (or an enrollment added if the account already exists) and associated with the
master who owns that product key. A welcome email with the user's reset code is then sent
so the user can set their first password.

## Webhook Events
- `paid` — one-time purchase
- `subscription.created` — new subscription

## Processing Flow
```
POST /api/webhooks/payhip
  → verify signature (HMAC-SHA256, skipped in simulator)
  → look up master_id from product_key
  → duplicate check (skippable with force=True)
  → if new email → create user, add enrollment, set active_master
  → if existing email → add enrollment only
  → _send_welcome_email(email, username, reset_code)
      → MailerSend transactional (if MAILERSEND_API_KEY set): sends email with reset code
      → MailerLite upsert: subscriber fields include reset_code for automation template
```

## Database Tables

### master_product_keys
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR(36) | Primary key |
| master_id | VARCHAR(36) | Associated master user ID |
| product_key | VARCHAR(64) | Payhip product permalink |
| product_name | VARCHAR(255) | Optional display name |
| is_active | BOOLEAN | Must be 1 — raw SQL INSERT must set this explicitly |
| created_at | TIMESTAMP | Must be set explicitly in raw SQL (no Python default) |

### payhip_webhook_log
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR(36) | Primary key |
| event_type | VARCHAR(32) | paid / subscription.created |
| customer_email | VARCHAR(255) | Customer email |
| product_key | VARCHAR(64) | Product key from payload |
| master_id | VARCHAR(36) | Resolved master ID |
| user_id | VARCHAR(36) | Created/updated user ID |
| status | VARCHAR(32) | success / duplicate / error |
| error_message | TEXT | Error details |
| raw_payload | TEXT | Full JSON payload |
| transaction_id | VARCHAR(64) | Payhip transaction/subscription ID |
| created_at | TIMESTAMP | Must be set explicitly in raw SQL |

## Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `PAYHIP_API_KEY` | Yes (prod) | HMAC-SHA256 signing secret from Payhip |
| `MAILER_LITE_API` | Recommended | MailerLite API key for subscriber upsert |
| `MAILER_LITE_GROUP_ID` | Recommended | Group ID — triggers automation email |
| `MAILERSEND_API_KEY` | Optional | MailerSend key for transactional email with reset code |
| `MAILERSEND_FROM` | If above set | Verified sender address |
| `MAILERSEND_FROM_NAME` | Optional | Sender display name |
| `APP_URL` | Optional | Public app URL for the "set password" link in email |

## API Endpoint
```
POST /api/webhooks/payhip        — real Payhip webhook (signature verified)
```

## Admin UI (4 tabs)
- **Associations** — link Payhip product keys to master users
- **Logs** — view webhook history with raw JSON payloads
- **Simulator** — send a fake webhook to test the pipeline; shows DB reset_code and email delivery diagnostics
- **Settings** — endpoint info and env var status

## Known Pitfalls
- SQLite stores `is_active` and `created_at` as-is from INSERT: Python-level `default=` on Column does NOT apply to raw `text()` SQL — always set them explicitly.
- SQLite returns `created_at` as a string, not a `datetime`. Use `hasattr(v, 'isoformat')` before calling `.isoformat()`.
- MailerLite "subscriber joins group" automation only fires when the subscriber is *added* to the group, not on subsequent upserts. Use "Remove from group" in the Debug → MailerLite tab to re-trigger during testing.
- MailerLite template variable syntax: `{{ subscriber.fields.reset_code }}` (new builder) or `{$reset_code}` (classic builder). The field key must be exactly `reset_code`.

## Do / Don't
- Do: associate each Payhip product with a master before going live
- Do: set `MAILER_LITE_GROUP_ID` via the Debug → MailerLite tab (saved to `local_config.json`)
- Do: monitor Logs tab after first real purchase
- Don't: manually create users for Payhip purchases — use the webhook
- Don't: delete the MailerLite subscriber to re-test — just remove from the group
