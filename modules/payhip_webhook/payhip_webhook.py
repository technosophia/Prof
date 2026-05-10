"""Payhip Webhook module for auto-subscription user creation."""

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Column, DateTime, String, Text, Boolean, Table, MetaData, text
from sqlalchemy.orm import Session

from core.database import get_db_manager
from core.logging import log
from shared.users import UserManager, UserRole


def _get_metadata() -> MetaData:
    """Get SQLAlchemy metadata."""
    return MetaData()


metadata = _get_metadata()


MasterProductKeyTable = Table(
    "master_product_keys",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("master_id", String(36), nullable=False, index=True),
    Column("product_key", String(64), nullable=False, unique=True),
    Column("product_name", String(255), nullable=True),
    Column("is_active", Boolean, default=True),
    Column("created_at", DateTime, default=datetime.utcnow),
)


PayhipWebhookLogTable = Table(
    "payhip_webhook_log",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("event_type", String(32), nullable=False, index=True),
    Column("customer_email", String(255), nullable=False),
    Column("product_key", String(64), nullable=False),
    Column("master_id", String(36), nullable=True),
    Column("user_id", String(36), nullable=True),
    Column("status", String(32), nullable=False, index=True),
    Column("error_message", Text, nullable=True),
    Column("raw_payload", Text, nullable=True),
    Column("transaction_id", String(64), nullable=True),
    Column("created_at", DateTime, default=datetime.utcnow, index=True),
)


def ensure_tables():
    """Ensure all tables exist."""
    db = get_db_manager()
    MasterProductKeyTable.create(bind=db._engine, checkfirst=True)
    PayhipWebhookLogTable.create(bind=db._engine, checkfirst=True)


class PayhipWebhookManager:
    """Manager for Payhip webhook operations."""

    def __init__(self, check_tables: bool = True):
        if check_tables:
            ensure_tables()

    def _get_master_by_product_key(self, product_key: str) -> Optional[str]:
        """Get master_id associated with a product_key."""
        db = get_db_manager()
        with db.get_session() as session:
            result = session.execute(
                text(f"SELECT master_id FROM master_product_keys "
                f"WHERE product_key = :product_key AND is_active = TRUE"),
                {"product_key": product_key}
            ).fetchone()
            return result[0] if result else None

    def add_product_association(
        self, master_id: str, product_key: str, product_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Add association between a master and a product key."""
        db = get_db_manager()

        with db.get_session() as session:
            existing = session.execute(
                text(f"SELECT id FROM master_product_keys "
                f"WHERE product_key = :product_key"),
                {"product_key": product_key}
            ).fetchone()

            if existing:
                return False, f"Product key '{product_key}' already associated"

            user_manager = UserManager()
            master = user_manager.get_user(master_id)
            if not master or master.get("role") != UserRole.MASTER.value:
                return False, "Master user not found or not a master"

            assoc_id = str(uuid.uuid4())
            session.execute(
                text("INSERT INTO master_product_keys "
                     "(id, master_id, product_key, product_name, is_active) "
                     "VALUES (:id, :master_id, :product_key, :product_name, 1)"),
                {"id": assoc_id, "master_id": master_id, "product_key": product_key, "product_name": product_name}
            )
            session.commit()
            return True, "Association created"

    def remove_product_association(self, association_id: str) -> bool:
        """Remove a product association."""
        db = get_db_manager()
        with db.get_session() as session:
            result = session.execute(
                text(f"DELETE FROM master_product_keys WHERE id = :id"),
                {"id": association_id}
            )
            session.commit()
            return result.rowcount > 0

    def get_all_associations(self) -> List[Dict[str, Any]]:
        """Get all master-product associations."""
        db = get_db_manager()
        with db.get_session() as session:
            results = session.execute(
                text(f"SELECT a.id, a.master_id, a.product_key, a.product_name, a.is_active, a.created_at, u.name as master_name "
                f"FROM master_product_keys a "
                f"LEFT JOIN users u ON a.master_id = u.id "
                f"ORDER BY a.created_at DESC")
            ).fetchall()

            return [
                {
                    "id": r[0],
                    "master_id": r[1],
                    "product_key": r[2],
                    "product_name": r[3],
                    "is_active": r[4],
                    "created_at": r[5].isoformat() if r[5] and hasattr(r[5], "isoformat") else r[5],
                    "master_name": r[6],
                }
                for r in results
            ]

    def log_event(
        self,
        event_type: str,
        customer_email: str,
        product_key: str,
        status: str,
        master_id: Optional[str] = None,
        user_id: Optional[str] = None,
        error_message: Optional[str] = None,
        raw_payload: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> None:
        """Log a webhook event."""
        db = get_db_manager()
        log_id = str(uuid.uuid4())

        with db.get_session() as session:
            session.execute(
                text(
                    "INSERT INTO payhip_webhook_log "
                    "(id, event_type, customer_email, product_key, master_id, user_id, "
                    " status, error_message, raw_payload, transaction_id, created_at) "
                    "VALUES (:id, :event_type, :customer_email, :product_key, :master_id, :user_id, "
                    "        :status, :error_message, :raw_payload, :transaction_id, :created_at)"
                ),
                {
                    "id": log_id,
                    "event_type": event_type,
                    "customer_email": customer_email,
                    "product_key": product_key,
                    "master_id": master_id,
                    "user_id": user_id,
                    "status": status,
                    "error_message": error_message,
                    "raw_payload": raw_payload,
                    "transaction_id": transaction_id,
                    "created_at": datetime.utcnow(),
                }
            )
            session.commit()

    def get_logs(
        self,
        status: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get webhook logs with optional filters."""
        db = get_db_manager()

        query = f"SELECT * FROM payhip_webhook_log WHERE 1=1"
        params = {}

        if status:
            query += " AND status = :status"
            params["status"] = status
        if event_type:
            query += " AND event_type = :event_type"
            params["event_type"] = event_type

        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit

        with db.get_session() as session:
            results = session.execute(text(query), params).fetchall()

            return [
                {
                    "id": r[0],
                    "event_type": r[1],
                    "customer_email": r[2],
                    "product_key": r[3],
                    "master_id": r[4],
                    "user_id": r[5],
                    "status": r[6],
                    "error_message": r[7],
                    "raw_payload": r[8],
                    "transaction_id": r[9],
                    "created_at": r[10].isoformat() if r[10] and hasattr(r[10], "isoformat") else r[10],
                }
                for r in results
            ]

    def check_duplicate(
        self, customer_email: str, product_key: str, event_type: str
    ) -> Optional[Dict[str, Any]]:
        """Check if this exact purchase already exists."""
        db = get_db_manager()
        with db.get_session() as session:
            result = session.execute(
                text(f"SELECT id, user_id, status FROM payhip_webhook_log "
                f"WHERE customer_email = :email AND product_key = :product_key AND event_type = :event_type AND status = 'success' "
                f"ORDER BY created_at DESC LIMIT 1"),
                {"email": customer_email, "product_key": product_key, "event_type": event_type}
            ).fetchone()

            if result:
                return {"id": result[0], "user_id": result[1], "status": result[2]}
            return None

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify Payhip webhook signature.

        Payhip signs requests with HMAC-SHA256 using the API key as the secret.
        The signature is sent in the X-Payhip-Signature header.
        """
        api_key = os.getenv("PAYHIP_API_KEY")
        if not api_key:
            log("error", "PAYHIP_API_KEY not configured")
            return False

        expected = hmac.new(
            api_key.encode("utf-8"),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    def _unique_username(self, user_manager, base: str) -> str:
        """Return a username that doesn't conflict with existing names."""
        candidate = base
        counter = 1
        while user_manager.get_user_by_name(candidate):
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate

    def process_webhook(self, payload: Dict[str, Any], raw_payload: str, force: bool = False) -> Tuple[int, str]:
        """Process a Payhip webhook and create user if needed.

        Returns:
            Tuple of (HTTP status code, message)
        """
        event_type = payload.get("type")
        if event_type not in ("paid", "subscription.created"):
            self.log_event(
                event_type="unknown",
                customer_email=payload.get("email", ""),
                product_key=payload.get("product_link", ""),
                status="error",
                error_message=f"Unknown event type: {event_type}",
                raw_payload=raw_payload,
            )
            return 400, f"Unsupported event type: {event_type}"

        customer_email = payload.get("email") or payload.get("customer_email")
        if not customer_email:
            self.log_event(
                event_type=event_type,
                customer_email="",
                product_key="",
                status="error",
                error_message="No email in payload",
                raw_payload=raw_payload,
            )
            return 400, "No email in payload"

        product_key = payload.get("product_link") or payload.get("items", [{}])[0].get("product_key", "")
        if not product_key:
            self.log_event(
                event_type=event_type,
                customer_email=customer_email,
                product_key="",
                status="error",
                error_message="No product_key in payload",
                raw_payload=raw_payload,
            )
            return 400, "No product_key in payload"

        transaction_id = payload.get("id") or payload.get("subscription_id")

        master_id = self._get_master_by_product_key(product_key)
        if not master_id:
            self.log_event(
                event_type=event_type,
                customer_email=customer_email,
                product_key=product_key,
                status="error",
                error_message=f"No master associated with product_key: {product_key}",
                raw_payload=raw_payload,
                transaction_id=transaction_id,
            )
            return 404, f"No master found for product: {product_key}"

        if not force:
            duplicate = self.check_duplicate(customer_email, product_key, event_type)
            if duplicate:
                self.log_event(
                    event_type=event_type,
                    customer_email=customer_email,
                    product_key=product_key,
                    master_id=master_id,
                    user_id=duplicate.get("user_id"),
                    status="duplicate",
                    raw_payload=raw_payload,
                    transaction_id=transaction_id,
                )
                log("info", f"Duplicate webhook: {customer_email} / {product_key}")
                return 200, "Duplicate ignored"

        try:
            user_manager = UserManager()

            # Check if this email is already a registered user
            existing_user = user_manager.get_user_by_email(customer_email)

            if existing_user:
                user_id = existing_user["id"]
                user_manager.add_enrollment(user_id, master_id, product_key=product_key)
                log("info", f"Added enrollment for existing user {user_id} under master {master_id}")
                action = "Enrollment added"
            else:
                base_name = customer_email.split("@")[0]
                user_name = self._unique_username(user_manager, base_name)
                master = user_manager.get_user(master_id)
                master_lang = (master.get("profile") or {}).get("language", "en") if master else "en"
                user_id, reset_code = user_manager.create_user(
                    name=user_name,
                    role=UserRole.NORMAL.value,
                    email=customer_email,
                    parent_id=master_id,
                    registration_status="approved",
                    profile={"language": master_lang},
                    user_metadata={"created_via": "payhip_webhook"},
                )
                user_manager.add_enrollment(user_id, master_id, product_key=product_key)
                # Pre-set active training so the user lands in the right context immediately
                user_manager.set_active_master(user_id, master_id)

                if reset_code:
                    self._send_welcome_email(customer_email, user_name, reset_code)

                log("info", f"Created user {user_id} ({user_name}) for {customer_email} under master {master_id}")
                action = f"User created (id={user_id}, username={user_name})"

            self.log_event(
                event_type=event_type,
                customer_email=customer_email,
                product_key=product_key,
                master_id=master_id,
                user_id=user_id,
                status="success",
                raw_payload=raw_payload,
                transaction_id=transaction_id,
            )

            return 200, action

        except Exception as e:
            error_msg = str(e)
            log("error", f"Webhook processing error: {error_msg}")

            self.log_event(
                event_type=event_type,
                customer_email=customer_email,
                product_key=product_key,
                master_id=master_id,
                status="error",
                error_message=error_msg,
                raw_payload=raw_payload,
                transaction_id=transaction_id,
            )
            return 500, f"Error processing webhook: {error_msg}"

    def _send_welcome_email(self, email: str, name: str, reset_code: str) -> bool:
        """Send welcome email with reset code via MailerLite."""
        from shared.mailer_lite import notify_account_approved

        notify_account_approved(email, name)
        # The reset_code is stored in the DB — the user can obtain it via the
        # "Forgot Password" flow. Log it here so an admin can retrieve it if needed.
        log("info", f"[WEBHOOK] New user created for {email}. Reset code stored in DB (use Forgot Password to receive it).")
        return True


_payhip_webhook_manager: Optional[PayhipWebhookManager] = None


def get_payhip_webhook_manager() -> PayhipWebhookManager:
    global _payhip_webhook_manager
    if _payhip_webhook_manager is None:
        _payhip_webhook_manager = PayhipWebhookManager()
    return _payhip_webhook_manager


