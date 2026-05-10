# Payhip Webhook Module

## Purpose
Auto-subscription webhook for Payhip that creates users associated with masters based on product keys.

## Webhook Events
- `paid` - One-time purchase
- `subscription.created` - New subscription

## Database Tables

### master_product_keys
Stores associations between master users and Payhip product keys.
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR(36) | Primary key |
| master_id | VARCHAR(36) | Associated master user ID |
| product_key | VARCHAR(64) | Payhip product permalink |
| product_name | VARCHAR(255) | Optional product name |
| is_active | BOOLEAN | Whether association is active |
| created_at | TIMESTAMP | Creation timestamp |

### payhip_webhook_log
Logs all webhook operations.
| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR(36) | Primary key |
| event_type | VARCHAR(32) | Event type (paid, subscription.created) |
| customer_email | VARCHAR(255) | Customer email |
| product_key | VARCHAR(64) | Product key from webhook |
| master_id | VARCHAR(36) | Associated master ID |
| user_id | VARCHAR(36) | Created user ID |
| status | VARCHAR(32) | success, duplicate, error |
| error_message | TEXT | Error details if failed |
| raw_payload | TEXT | Raw JSON payload |
| transaction_id | VARCHAR(64) | Payhip transaction/subscription ID |
| created_at | TIMESTAMP | Event timestamp |

## Environment Variables
- `PAYHIP_API_KEY` - Payhip API key for signature validation

## API Endpoint
```
POST /api/webhooks/payhip
```

## Usage
1. Set `PAYHIP_API_KEY` environment variable
2. Configure Payhip webhook URL to point to `/api/webhooks/payhip`
3. Add master-product associations via admin UI
4. When a purchase is made, a new user is created and associated with the master

## Do / Don't
- Do: Associate each Payhip product with a master user
- Do: Monitor logs for errors
- Don't: Manually create users for Payhip purchases - use the webhook
