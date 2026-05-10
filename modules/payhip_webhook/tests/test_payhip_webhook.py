import hashlib
import hmac
import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestPayhipWebhookSignature:
    """Test webhook signature verification."""

    def test_verify_signature_valid(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        with patch.dict(os.environ, {"PAYHIP_API_KEY": "test_api_key"}):
            manager = PayhipWebhookManager(check_tables=False)
            payload = b'{"type": "paid", "email": "test@example.com"}'
            signature = hmac.new(
                b"test_api_key", payload, hashlib.sha256
            ).hexdigest()

            assert manager.verify_signature(payload, signature) is True

    def test_verify_signature_invalid(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        with patch.dict(os.environ, {"PAYHIP_API_KEY": "test_api_key"}):
            manager = PayhipWebhookManager(check_tables=False)
            payload = b'{"type": "paid", "email": "test@example.com"}'

            assert manager.verify_signature(payload, "invalid_signature") is False

    def test_verify_signature_no_api_key(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        with patch.dict(os.environ, {}, clear=True):
            manager = PayhipWebhookManager(check_tables=False)
            payload = b'{"type": "paid"}'

            assert manager.verify_signature(payload, "any_signature") is False


class TestPayhipWebhookManager:
    """Test webhook manager functionality."""

    @pytest.fixture
    def mock_db(self):
        with patch("modules.payhip_webhook.payhip_webhook.get_db_manager") as mock:
            db_mock = MagicMock()
            mock_session = MagicMock()
            db_mock.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            db_mock.get_session.return_value.__exit__ = MagicMock(return_value=False)
            mock.return_value = db_mock
            yield mock_session

    def test_get_master_by_product_key_found(self, mock_db):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        mock_db.execute.return_value.fetchone.return_value = ("master_123",)

        with patch("modules.payhip_webhook.payhip_webhook.get_db_manager") as mock_get_db:
            mock_get_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)

            manager = PayhipWebhookManager()
            result = manager._get_master_by_product_key("test_product")

            assert result == "master_123"

    def test_get_master_by_product_key_not_found(self, mock_db):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        mock_db.execute.return_value.fetchone.return_value = None

        with patch("modules.payhip_webhook.payhip_webhook.get_db_manager") as mock_get_db:
            mock_get_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)

            manager = PayhipWebhookManager()
            result = manager._get_master_by_product_key("unknown_product")

            assert result is None


class TestWebhookPayloadProcessing:
    """Test webhook payload processing logic."""

    def test_process_paid_event(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        payload = {
            "type": "paid",
            "id": "trans_123",
            "email": "customer@example.com",
            "items": [{"product_key": "test_key"}],
        }

        manager = PayhipWebhookManager(check_tables=False)
        manager._get_master_by_product_key = MagicMock(return_value="master_123")
        manager.check_duplicate = MagicMock(return_value=None)
        manager._send_reset_email = MagicMock(return_value=True)

        with patch.object(manager, "log_event") as mock_log:
            with patch("modules.payhip_webhook.payhip_webhook.UserManager") as mock_user_mgr:
                mock_user_instance = MagicMock()
                mock_user_instance.create_user.return_value = ("user_456", "reset_code_123")
                mock_user_mgr.return_value = mock_user_instance

                status, msg = manager.process_webhook(payload, json.dumps(payload))

                assert status == 200
                assert "created" in msg.lower()
                mock_log.assert_called()
                call_args = mock_log.call_args
                assert call_args.kwargs["status"] == "success"

    def test_process_subscription_created_event(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        payload = {
            "type": "subscription.created",
            "subscription_id": "sub_123",
            "customer_email": "subscriber@example.com",
            "product_link": "sub_key",
        }

        manager = PayhipWebhookManager(check_tables=False)
        manager._get_master_by_product_key = MagicMock(return_value="master_456")
        manager.check_duplicate = MagicMock(return_value=None)
        manager._send_reset_email = MagicMock(return_value=True)

        with patch.object(manager, "log_event") as mock_log:
            with patch("modules.payhip_webhook.payhip_webhook.UserManager") as mock_user_mgr:
                mock_user_instance = MagicMock()
                mock_user_instance.create_user.return_value = ("user_789", "reset_xyz")
                mock_user_mgr.return_value = mock_user_instance

                status, msg = manager.process_webhook(payload, json.dumps(payload))

                assert status == 200
                assert "created" in msg.lower()

    def test_process_unknown_event(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        payload = {"type": "unknown_event", "email": "test@example.com"}

        manager = PayhipWebhookManager(check_tables=False)
        manager.log_event = MagicMock()

        status, msg = manager.process_webhook(payload, json.dumps(payload))

        assert status == 400
        assert "Unsupported" in msg

    def test_process_no_email(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        payload = {"type": "paid", "items": [{"product_key": "test"}]}

        manager = PayhipWebhookManager(check_tables=False)
        manager.log_event = MagicMock()

        status, msg = manager.process_webhook(payload, json.dumps(payload))

        assert status == 400
        assert "email" in msg.lower()

    def test_process_no_master_found(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        payload = {
            "type": "paid",
            "id": "trans_123",
            "email": "customer@example.com",
            "items": [{"product_key": "unknown_key"}],
        }

        manager = PayhipWebhookManager(check_tables=False)
        manager._get_master_by_product_key = MagicMock(return_value=None)
        manager.log_event = MagicMock()

        status, msg = manager.process_webhook(payload, json.dumps(payload))

        assert status == 404
        assert "no master" in msg.lower()

    def test_process_duplicate_ignored(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookManager

        payload = {
            "type": "paid",
            "id": "trans_123",
            "email": "customer@example.com",
            "items": [{"product_key": "test_key"}],
        }

        manager = PayhipWebhookManager(check_tables=False)
        manager._get_master_by_product_key = MagicMock(return_value="master_123")
        manager.check_duplicate = MagicMock(return_value={"user_id": "existing_user", "id": "log_id"})
        manager.log_event = MagicMock()

        status, msg = manager.process_webhook(payload, json.dumps(payload))

        assert status == 200
        assert "duplicate" in msg.lower()


class TestDatabaseTables:
    """Test database table definitions."""

    def test_master_product_key_table_name(self):
        from modules.payhip_webhook.payhip_webhook import MasterProductKeyTable

        assert MasterProductKeyTable.name == "master_product_keys"
        assert "master_id" in [c.name for c in MasterProductKeyTable.columns]
        assert "product_key" in [c.name for c in MasterProductKeyTable.columns]

    def test_webhook_log_table_name(self):
        from modules.payhip_webhook.payhip_webhook import PayhipWebhookLogTable

        assert PayhipWebhookLogTable.name == "payhip_webhook_log"
        assert "event_type" in [c.name for c in PayhipWebhookLogTable.columns]
        assert "customer_email" in [c.name for c in PayhipWebhookLogTable.columns]
        assert "product_key" in [c.name for c in PayhipWebhookLogTable.columns]
        assert "status" in [c.name for c in PayhipWebhookLogTable.columns]
        assert "raw_payload" in [c.name for c in PayhipWebhookLogTable.columns]
