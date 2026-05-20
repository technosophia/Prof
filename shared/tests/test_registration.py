from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import app
from shared.common import get_user_manager
from shared.users import PreregisteredEmail, UserTable, WaitlistEntry, WaitlistList
from st_shared.cached import get_db_manager


@pytest.fixture(autouse=True)
def isolate_registration_state(monkeypatch):
    user_manager = get_user_manager()
    db_manager = get_db_manager()
    user_manager._ensure_table_exists()
    user_manager._ensure_preregistered_emails_table()

    class _ConfigStub:
        def __init__(self):
            self._data = {"registration.preregistered_emails": []}

        def get(self, key, default=None):
            return self._data.get(key, default)

        def set(self, key, value):
            self._data[key] = value

    config = _ConfigStub()
    monkeypatch.setattr("shared.users.get_config", lambda: config)

    with db_manager.get_session() as session:
        session.query(PreregisteredEmail).delete()
        session.query(UserTable).filter(UserTable.id.like("test_reg_%")).delete(synchronize_session=False)
        session.query(WaitlistEntry).delete()
        session.query(WaitlistList).delete()
        session.commit()

    yield config

    with db_manager.get_session() as session:
        session.query(PreregisteredEmail).delete()
        session.query(UserTable).filter(UserTable.id.like("test_reg_%")).delete(synchronize_session=False)
        session.query(WaitlistEntry).delete()
        session.query(WaitlistList).delete()
        session.commit()



def _make_csv(header: str, emails: list[str]) -> str:
    lines = [header]
    lines.extend(emails)
    return "\n".join(lines) + "\n"


def test_csv_import_standard_header():
    result = get_user_manager().import_preregistered_emails(
        _make_csv("email", ["alice@example.com", "bob@example.org"]),
        requesting_user_id="admin",
    )

    assert result["imported"] == 2
    assert result["skipped"] == 0
    assert result["invalid"] == []
    assert result["errors"] == []


@pytest.mark.parametrize("header", ["email", "e-mail", "mail", "email address", "e-mail address", "courriel"])
def test_csv_import_email_variants(header: str):
    result = get_user_manager().import_preregistered_emails(_make_csv(header, ["variant@example.com"]))
    assert result["imported"] == 1
    assert result["errors"] == []


@pytest.mark.parametrize("header", ["EMAIL", "E-Mail"])
def test_csv_import_mixed_case_header(header: str):
    result = get_user_manager().import_preregistered_emails(_make_csv(header, ["caps@example.com"]))
    assert result["imported"] == 1
    assert result["errors"] == []


def test_csv_import_invalid_emails():
    result = get_user_manager().import_preregistered_emails(
        _make_csv("email", ["valid@example.com", "bad-email", "also@bad", ""]),
    )

    assert result["imported"] == 1
    assert result["skipped"] == 0
    assert set(result["invalid"]) == {"bad-email", "also@bad"}


def test_csv_import_duplicates():
    user_manager = get_user_manager()
    first = user_manager.import_preregistered_emails(_make_csv("email", ["dup@example.com"]))
    second = user_manager.import_preregistered_emails(_make_csv("email", ["dup@example.com"]))

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["skipped"] == 1
    assert second["errors"] == []


def test_csv_import_no_matching_column():
    result = get_user_manager().import_preregistered_emails("username\nfoo@example.com\n")
    assert result["imported"] == 0
    assert result["errors"] == ["missing_email_column"]


def test_csv_import_empty_file():
    result = get_user_manager().import_preregistered_emails("")
    assert result["imported"] == 0
    assert result["skipped"] == 0
    assert result["invalid"] == []
    assert result["errors"] == []


def test_preregistered_from_db():
    get_user_manager().import_preregistered_emails(_make_csv("email", ["db@example.com"]))
    assert get_user_manager().is_email_preregistered("db@example.com") is True


def test_preregistered_from_config(isolate_registration_state):
    isolate_registration_state.set("registration.preregistered_emails", ["config@example.com"])
    assert get_user_manager().is_email_preregistered("config@example.com") is True


def test_preregistered_case_insensitive(isolate_registration_state):
    get_user_manager().import_preregistered_emails(_make_csv("email", ["alice@example.com"]))
    isolate_registration_state.set("registration.preregistered_emails", ["bob@example.com"])

    assert get_user_manager().is_email_preregistered("Alice@Example.COM") is True
    assert get_user_manager().is_email_preregistered("BOB@EXAMPLE.COM") is True


def test_not_preregistered():
    assert get_user_manager().is_email_preregistered("unknown@example.com") is False


def test_register_preregistered_email():
    get_user_manager().import_preregistered_emails(_make_csv("email", ["approved@example.com"]))

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "approved@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
                "suggested_id": "test_reg_approved",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["id"] == "test_reg_approved"


def test_register_unknown_email():
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "pending@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
                "suggested_id": "test_reg_pending",
            },
        )

    assert response.status_code == 202
    assert response.json() == {"status": "pending"}


def test_register_password_mismatch():
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "mismatch@example.com",
                "password": "strongpass123",
                "confirm_password": "different123",
                "suggested_id": "test_reg_mismatch",
            },
        )

    assert response.status_code == 400


def test_register_duplicate_user_id():
    get_user_manager().import_preregistered_emails(_make_csv("email", ["first@example.com", "second@example.com"]))

    with TestClient(app) as client:
        first = client.post(
            "/api/auth/register",
            json={
                "email": "first@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
                "suggested_id": "test_reg_duplicate",
            },
        )
        assert first.status_code == 200

        second = client.post(
            "/api/auth/register",
            json={
                "email": "second@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
                "suggested_id": "test_reg_duplicate",
            },
        )

    assert second.status_code == 409
    assert second.json()["detail"] == "user_id_conflict"


def test_register_then_login_approved():
    get_user_manager().import_preregistered_emails(_make_csv("email", ["flow@example.com"]))

    with TestClient(app) as client:
        register = client.post(
            "/api/auth/register",
            json={
                "email": "flow@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
                "suggested_id": "test_reg_flow",
            },
        )
        assert register.status_code == 200
        token = register.json()["access_token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["id"] == "test_reg_flow"


def test_register_then_login_pending():
    with TestClient(app) as client:
        register = client.post(
            "/api/auth/register",
            json={
                "email": "pending-flow@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
                "suggested_id": "test_reg_pending_flow",
            },
        )
        assert register.status_code == 202

        login = client.post(
            "/api/auth/login",
            json={"user_id": "test_reg_pending_flow", "password": "strongpass123"},
        )

    assert login.status_code == 403
    assert login.json()["detail"] == "pending_approval"


def test_login_approved_user():
    user_manager = get_user_manager()
    user_manager.create_user(
        name="test_reg_existing",
        role="normal",
        email="existing@example.com",
        parent_id=None,
        password="existingpass123",
        user_id="test_reg_existing",
        allow_orphan_normal=True,
        registration_status="approved",
    )

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"user_id": "test_reg_existing", "password": "existingpass123"},
        )

    assert login.status_code == 200
    assert login.json()["access_token"]


def test_register_preregistered_sets_default_deadline_metadata():
    get_user_manager().add_preregistered_email("deadline@example.com")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "deadline@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
                "suggested_id": "test_reg_deadline",
            },
        )

    assert response.status_code == 200
    user = get_user_manager().get_user("test_reg_deadline")
    metadata = user.get("metadata", {})
    assert metadata.get("preregistered") is True
    assert metadata.get("preregistered_deadline_months") == 6
    assert metadata.get("preregistered_deadline_at")


def test_deadline_expired_revokes_credentials_with_custom_message():
    get_user_manager().create_user(
        name="test_reg_expired",
        role="normal",
        email="expired@example.com",
        parent_id=None,
        password="expiredpass123",
        user_id="test_reg_expired",
        allow_orphan_normal=True,
        registration_status="approved",
        user_metadata={
            "preregistered_deadline_at": "2000-01-01T00:00:00",
            "preregistered_expiry_message": "Custom deadline reached.",
        },
    )

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"user_id": "test_reg_expired", "password": "expiredpass123"},
        )

    assert login.status_code == 403
    assert login.json()["detail"] == "deadline_expired::Custom deadline reached."
    user = get_user_manager().get_user("test_reg_expired")
    assert user["is_active"] is False


def test_waitlist_endpoint_creates_pending_user():
    user_manager = get_user_manager()
    user_manager.create_waitlist_list("Default", created_by="admin")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/waitlist",
            json={"email": "waitlist@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "pending"}

    entries = user_manager.get_waitlist_entries(status="pending")
    assert entries
    assert any(e["email"] == "waitlist@example.com" for e in entries)


def test_deadline_set_at_creation_for_normal_users():
    """Normal users created via the UI get expiration_date set at creation time."""
    get_user_manager().create_user(
        name="test_reg_retroactive",
        role="normal",
        email="retroactive@example.com",
        parent_id="master1",
        password="retroactive-pass123",
        user_id="test_reg_retroactive",
        registration_status="approved",
    )

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"user_id": "test_reg_retroactive", "password": "retroactive-pass123"},
        )
    assert login.status_code == 200

    user = get_user_manager().get_user("test_reg_retroactive")
    assert user.get("expiration_date") is not None
