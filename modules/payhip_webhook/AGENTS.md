# Payhip Webhook Module

## Purpose
Auto-subscription webhook for Payhip: when a customer purchases a product, a user account
is created (or an enrollment added/reactivated if the account already exists) and associated
with the master who owns that product key. A welcome email with the user's reset code is
then sent so the user can set their first password.

## Webhook Events
- `paid` — one-time purchase
- `subscription.created` — new subscription

## Processing Flow
```
POST /webhooks/payhip   (no /api prefix — routed directly by Traefik)
  → verify signature (HMAC-SHA256, skipped in simulator)
  → look up (master_id, enrollment_duration_days) from product_key
  → compute expires_at = now + timedelta(days=enrollment_duration_days)  [None if 0/unset]
  → duplicate check (skippable with force=True)
  → if new email  → create user, add_enrollment(expires_at=expires_at), set_active_master
  → if known email → add_enrollment(expires_at=expires_at)  [reactivates + refreshes expiry]
  → _send_welcome_email(email, name, reset_code, lang)
      → MailerSend transactional (if MAILERSEND_API_KEY set): multilingual email with reset code
```

## Enrollment Expiry
Each product association can have an `enrollment_duration_days` (nullable). When set, the
enrollment's `expires_at` is computed at webhook time. On the student's next login attempt:
- expired → `enrollment_expired` (HTTP 403) + alert email sent to the master
- live / unlimited → login proceeds normally

Admin can edit `enrollment_duration_days` per product in the Associations tab.

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
| enrollment_duration_days | INTEGER | NULL = unlimited; otherwise days until enrollment expires |

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
| `MAILERSEND_API_KEY` | Recommended | MailerSend key for transactional welcome email |
| `MAILERSEND_FROM` | If above set | Verified sender address |
| `MAILERSEND_FROM_NAME` | Optional | Sender display name |
| `APP_URL` | Required | Public app URL for "activate account" link — must be `https://app.yoga-pro.xyz` |
| `MAILER_LITE_API` | Optional | MailerLite API key for subscriber upsert |
| `MAILER_LITE_GROUP_ID` | Optional | Group ID — triggers MailerLite automation email |

## API Endpoints
```
POST /webhooks/payhip            — real Payhip webhook (signature verified)
POST /webhooks/payhip/simulate   — simulator (admin/master, no signature check)
```

## Admin UI (5 tabs)
- **Associations** — link Payhip product keys to master users; set `enrollment_duration_days` per product (0 = unlimited); edit product name inline
- **Logs** — view webhook history with raw JSON payloads
- **Simulator** — send a fake webhook to test the pipeline; shows DB reset_code and email delivery diagnostics
- **Resend Email** — generate a fresh 7-day reset code and resend welcome email to any registered user
- **Settings** — endpoint info and env var status

## Known Pitfalls
- Webhook endpoint is `/webhooks/payhip` (no `/api` prefix). Configure exactly this URL in Payhip dashboard.
- MySQL: Python-level `default=` on Column does NOT apply to raw `text()` SQL — always set `is_active` and `created_at` explicitly in INSERT statements.
- Real Payhip payload puts the product key in `items[0].product_key`, not at the top level. The code checks both `product_link` (top-level) and `items[0].product_key`.
- MailerLite "subscriber joins group" automation only fires when the subscriber is *added* to the group, not on subsequent upserts. Use "Remove from group" to re-trigger during testing.
- MailerLite template variable syntax: `{{ subscriber.fields.reset_code }}` (new builder) or `{$reset_code}` (classic builder). The field key must be exactly `reset_code`.

## Do / Don't
- Do: set `enrollment_duration_days` on each product before going live if subscriptions expire
- Do: associate each Payhip product with a master before going live
- Do: monitor Logs tab after first real purchase
- Don't: manually create users for Payhip purchases — use the webhook or simulator
- Don't: delete the MailerLite subscriber to re-test — just remove from the group
