"""Tests for enrollment-level expiry: _check_enrollment_expiry, add_enrollment(expires_at),
get_user_enrollments (expired filtering), authenticate_user_with_status (enrollment_expired),
and master notification.

How time is faked
-----------------
shared/users.py does `from datetime import datetime`, so `datetime` in that module is the
class object bound to the name `shared.users.datetime`.  We replace it with a subclass
(FakeDatetime) that overrides `utcnow()`.  All other datetime operations (isinstance checks,
comparisons, isoformat, etc.) continue to work because FakeDatetime IS-A datetime.
"""
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

from shared.users import UserEnrollment, UserManager, UserRole, UserTable


# ---------------------------------------------------------------------------
# Time-travel helper
# ---------------------------------------------------------------------------

class FakeDatetime(datetime):
    """datetime subclass whose utcnow() returns a controlled value."""
    _now: datetime = datetime(2026, 1, 1, 12, 0, 0)

    @classmethod
    def utcnow(cls) -> datetime:
        return cls._now


def fake_now(dt: datetime):
    """Context manager: set FakeDatetime._now to *dt* for the duration of the block."""
    class _CM:
        def __enter__(self_):
            FakeDatetime._now = dt
            return dt
        def __exit__(self_, *_):
            FakeDatetime._now = datetime(2026, 1, 1, 12, 0, 0)
    return _CM()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_enrollment(
    user_id: str,
    master_id: str,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> UserEnrollment:
    e = UserEnrollment()
    e.id = str(uuid.uuid4())
    e.user_id = user_id
    e.master_id = master_id
    e.is_active = is_active
    e.expires_at = expires_at
    e.product_key = "test_product"
    e.enrolled_at = datetime(2026, 1, 1)
    return e


def _make_user(user_id: str, role: str = UserRole.NORMAL.value, email: str = "student@test.com") -> UserTable:
    u = UserTable()
    u.id = user_id
    u.name = "Test User"
    u.email = email
    u.role = role
    u.is_active = True
    u.password_hash = None
    u.registration_status = "approved"
    u.expiration_date = None
    u.user_metadata = {}
    u.reset_code = None
    u.reset_code_expires = None
    u.last_login = None
    return u


class BaseEnrollmentTest:
    """Common setup: singleton reset + fully mocked DB."""

    def setup_method(self):
        UserManager._instance = None
        self.mgr = UserManager()
        self.mgr.db = MagicMock()
        self.mgr.db.is_initialized = MagicMock(return_value=True)
        self.mgr.db._engine = MagicMock()
        self.session = MagicMock()

        class _Ctx:
            def __init__(self_, s):
                self_.s = s
            def __enter__(self_):
                return self_.s
            def __exit__(self_, *_):
                return False

        self.mgr.db.get_session = MagicMock(return_value=_Ctx(self.session))
        self.mgr._ensure_table_exists = MagicMock()
        self.mgr._ensure_enrollment_table_exists = MagicMock()
        self.mgr._ensure_action_log_table = MagicMock()

    def teardown_method(self):
        UserManager._instance = None


# ---------------------------------------------------------------------------
# 1. _check_enrollment_expiry
# ---------------------------------------------------------------------------

class TestCheckEnrollmentExpiry(BaseEnrollmentTest):

    def _setup_enrollments(self, rows):
        q = MagicMock()
        q.filter.return_value = q
        q.all.return_value = rows
        self.session.query.return_value = q

    def test_no_enrollments_returns_none(self):
        """No enrollment records → None (legacy path, not enrollment-expired)."""
        self._setup_enrollments([])
        result = self.mgr._check_enrollment_expiry("user1", "user@x.com")
        assert result is None

    def test_unlimited_enrollment_returns_none(self):
        """Active enrollment with no expires_at is always live."""
        e = _make_enrollment("user1", "master1", expires_at=None)
        self._setup_enrollments([e])
        with fake_now(datetime(2099, 12, 31)):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr._check_enrollment_expiry("user1", "u@x.com")
        assert result is None

    def test_future_expiry_returns_none(self):
        """Enrollment expires in the future → still live."""
        future = datetime(2026, 6, 1)
        e = _make_enrollment("user1", "master1", expires_at=future)
        self._setup_enrollments([e])
        now = datetime(2026, 1, 15)
        with fake_now(now):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr._check_enrollment_expiry("user1", "u@x.com")
        assert result is None

    def test_past_expiry_returns_master_id(self):
        """All enrollments expired → returns the master_id."""
        past = datetime(2025, 12, 1)
        e = _make_enrollment("user1", "master42", expires_at=past)
        self._setup_enrollments([e])
        now = datetime(2026, 1, 15)
        with fake_now(now):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr._check_enrollment_expiry("user1", "u@x.com")
        assert result == "master42"

    def test_mixed_enrollments_live_wins(self):
        """One expired + one live → returns None (user still has access)."""
        past = datetime(2025, 6, 1)
        future = datetime(2026, 12, 1)
        e1 = _make_enrollment("user1", "master_old", expires_at=past)
        e2 = _make_enrollment("user1", "master_new", expires_at=future)
        self._setup_enrollments([e1, e2])
        now = datetime(2026, 1, 15)
        with fake_now(now):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr._check_enrollment_expiry("user1", "u@x.com")
        assert result is None

    def test_expired_at_exact_boundary(self):
        """Expiry at exactly now is considered expired (<=)."""
        boundary = datetime(2026, 1, 15, 12, 0, 0)
        e = _make_enrollment("user1", "master_boundary", expires_at=boundary)
        self._setup_enrollments([e])
        with fake_now(boundary):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr._check_enrollment_expiry("user1", "u@x.com")
        assert result == "master_boundary"


# ---------------------------------------------------------------------------
# 2. get_user_enrollments — expired entries are filtered out
# ---------------------------------------------------------------------------

class TestGetUserEnrollmentsExpiry(BaseEnrollmentTest):

    def test_expired_enrollment_excluded(self):
        """An enrollment whose expires_at is in the past must not appear."""
        user_id = "u1"
        master_id = "m1"
        past = datetime(2025, 6, 1)

        enrollment = _make_enrollment(user_id, master_id, expires_at=past)
        master_user = _make_user(master_id, role=UserRole.MASTER.value, email="master@x.com")
        master_user.name = "Master One"

        q = MagicMock()
        q.join.return_value = q
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = [(enrollment, master_user)]
        self.session.query.return_value = q

        self.mgr.get_user = MagicMock(return_value={"id": user_id, "parent_id": None})

        now = datetime(2026, 1, 15)
        with fake_now(now):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr.get_user_enrollments(user_id)

        assert result == []

    def test_live_enrollment_included(self):
        """An enrollment whose expires_at is in the future must appear."""
        user_id = "u1"
        master_id = "m1"
        future = datetime(2026, 12, 31)

        enrollment = _make_enrollment(user_id, master_id, expires_at=future)
        master_user = _make_user(master_id, role=UserRole.MASTER.value, email="master@x.com")
        master_user.name = "Master One"

        q = MagicMock()
        q.join.return_value = q
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = [(enrollment, master_user)]
        self.session.query.return_value = q

        self.mgr.get_user = MagicMock(return_value={"id": user_id, "parent_id": None})

        now = datetime(2026, 1, 15)
        with fake_now(now):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr.get_user_enrollments(user_id)

        assert len(result) == 1
        assert result[0]["master_id"] == master_id
        assert result[0]["expires_at"] == future.isoformat()

    def test_unlimited_enrollment_always_included(self):
        """expires_at=None means no expiry — always returned."""
        user_id = "u1"
        master_id = "m1"

        enrollment = _make_enrollment(user_id, master_id, expires_at=None)
        master_user = _make_user(master_id, role=UserRole.MASTER.value, email="master@x.com")
        master_user.name = "Master One"

        q = MagicMock()
        q.join.return_value = q
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = [(enrollment, master_user)]
        self.session.query.return_value = q

        self.mgr.get_user = MagicMock(return_value={"id": user_id, "parent_id": None})

        now = datetime(2099, 1, 1)
        with fake_now(now):
            with patch("shared.users.datetime", FakeDatetime):
                result = self.mgr.get_user_enrollments(user_id)

        assert len(result) == 1
        assert result[0]["expires_at"] is None


# ---------------------------------------------------------------------------
# 3. add_enrollment — expires_at stored and reset on reactivation
# ---------------------------------------------------------------------------

class TestAddEnrollmentExpiresAt(BaseEnrollmentTest):

    def test_new_enrollment_stores_expires_at(self):
        """Creating a fresh enrollment persists the provided expires_at."""
        q = MagicMock()
        q.filter_by.return_value = q
        q.first.return_value = None          # no existing record
        self.session.query.return_value = q

        added_obj = []
        self.session.add.side_effect = lambda obj: added_obj.append(obj)

        expires = datetime(2027, 1, 1)
        self.mgr.add_enrollment("user1", "master1", product_key="abc", expires_at=expires)

        assert len(added_obj) == 1
        assert added_obj[0].expires_at == expires

    def test_reactivation_updates_expires_at(self):
        """Re-enrolling an inactive record updates expires_at to the new value."""
        existing = _make_enrollment("user1", "master1", is_active=False, expires_at=datetime(2025, 1, 1))
        q = MagicMock()
        q.filter_by.return_value = q
        q.first.return_value = existing
        self.session.query.return_value = q

        new_expires = datetime(2027, 6, 1)
        self.mgr.add_enrollment("user1", "master1", expires_at=new_expires)

        assert existing.is_active is True
        assert existing.expires_at == new_expires

    def test_update_clears_expires_at_when_none(self):
        """Passing expires_at=None on reactivation removes the expiry (unlimited)."""
        existing = _make_enrollment("user1", "master1", is_active=False, expires_at=datetime(2025, 1, 1))
        q = MagicMock()
        q.filter_by.return_value = q
        q.first.return_value = existing
        self.session.query.return_value = q

        self.mgr.add_enrollment("user1", "master1", expires_at=None)

        assert existing.is_active is True
        assert existing.expires_at is None


# ---------------------------------------------------------------------------
# 4. authenticate_user_with_status — enrollment_expired path
# ---------------------------------------------------------------------------

class TestAuthenticateEnrollmentExpired(BaseEnrollmentTest):
    """authenticate_user_with_status must return 'enrollment_expired' when all
    active enrollments have passed their expires_at, and must call the master
    notification helper."""

    def _make_db_user(self, password_hash="salt$abc", role=UserRole.NORMAL.value):
        u = _make_user("user1", role=role, email="student@x.com")
        u.password_hash = password_hash
        return u

    def test_enrollment_expired_status(self):
        db_user = self._make_db_user()

        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = db_user
        self.session.query.return_value = q

        self.mgr._verify_password = MagicMock(return_value=True)
        self.mgr._check_deadline_expiry = MagicMock(return_value=None)
        self.mgr._check_enrollment_expiry = MagicMock(return_value="master99")
        self.mgr._notify_master_enrollment_expired = MagicMock()
        self.mgr.log_user_action = MagicMock()

        user, status = self.mgr.authenticate_user_with_status("user1", "password")

        assert user is None
        assert status == "enrollment_expired"

    def test_master_is_notified_on_expiry(self):
        """The master notification helper must be called with correct args."""
        db_user = self._make_db_user()

        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = db_user
        self.session.query.return_value = q

        self.mgr._verify_password = MagicMock(return_value=True)
        self.mgr._check_deadline_expiry = MagicMock(return_value=None)
        self.mgr._check_enrollment_expiry = MagicMock(return_value="master99")
        notify = MagicMock()
        self.mgr._notify_master_enrollment_expired = notify
        self.mgr.log_user_action = MagicMock()

        self.mgr.authenticate_user_with_status("user1", "password")

        notify.assert_called_once_with("master99", "student@x.com")

    def test_master_user_bypasses_enrollment_check(self):
        """Masters and admins are not subject to enrollment expiry."""
        db_user = self._make_db_user(role=UserRole.MASTER.value)
        db_user.email = "master@x.com"

        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = db_user
        self.session.query.return_value = q

        self.mgr._verify_password = MagicMock(return_value=True)
        self.mgr._check_deadline_expiry = MagicMock(return_value=None)
        self.mgr._check_enrollment_expiry = MagicMock(return_value="some_master")
        self.mgr._notify_master_enrollment_expired = MagicMock()
        self.mgr.log_user_action = MagicMock()
        self.mgr._user_to_dict = MagicMock(return_value={"id": "user1", "role": "master"})

        user, status = self.mgr.authenticate_user_with_status("user1", "password")

        assert status == "success"
        self.mgr._check_enrollment_expiry.assert_not_called()

    def test_live_enrollment_allows_login(self):
        """A user with a live (non-expired) enrollment logs in normally."""
        db_user = self._make_db_user()

        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = db_user
        self.session.query.return_value = q

        self.mgr._verify_password = MagicMock(return_value=True)
        self.mgr._check_deadline_expiry = MagicMock(return_value=None)
        self.mgr._check_enrollment_expiry = MagicMock(return_value=None)  # live
        self.mgr._notify_master_enrollment_expired = MagicMock()
        self.mgr.log_user_action = MagicMock()
        self.mgr._user_to_dict = MagicMock(return_value={"id": "user1", "role": "normal"})

        user, status = self.mgr.authenticate_user_with_status("user1", "password")

        assert status == "success"
        self.mgr._notify_master_enrollment_expired.assert_not_called()

    def test_wrong_password_does_not_trigger_enrollment_check(self):
        """enrollment check must not be reached when the password is wrong."""
        db_user = self._make_db_user()

        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = db_user
        self.session.query.return_value = q

        self.mgr._verify_password = MagicMock(return_value=False)
        enrollment_check = MagicMock()
        self.mgr._check_enrollment_expiry = enrollment_check
        self.mgr.log_user_action = MagicMock()

        _, status = self.mgr.authenticate_user_with_status("user1", "wrong")

        assert status == "invalid_credentials"
        enrollment_check.assert_not_called()


# ---------------------------------------------------------------------------
# 5. _notify_master_enrollment_expired — email dispatch
# ---------------------------------------------------------------------------

class TestNotifyMasterEnrollmentExpired(BaseEnrollmentTest):

    def test_sends_email_when_configured(self):
        master = {"id": "m1", "email": "master@yoga.com", "name": "Yoga Master"}
        self.mgr.get_user = MagicMock(return_value=master)

        # _notify_master_enrollment_expired does a local import from shared.transactional_email,
        # so we patch the function on that module directly.
        import shared.transactional_email as te
        with patch.object(te, "send_enrollment_expired_alert", return_value=(True, "ok")) as mock_send, \
             patch.object(te, "_is_configured", return_value=True):
            self.mgr._notify_master_enrollment_expired("m1", "student@x.com")
            mock_send.assert_called_once_with(
                master_email="master@yoga.com",
                master_name="Yoga Master",
                student_email="student@x.com",
            )

    def test_skips_when_master_has_no_email(self):
        master = {"id": "m1", "email": None, "name": "No Email Master"}
        self.mgr.get_user = MagicMock(return_value=master)

        import shared.transactional_email as te
        with patch.object(te, "send_enrollment_expired_alert") as mock_send:
            self.mgr._notify_master_enrollment_expired("m1", "student@x.com")
            mock_send.assert_not_called()

    def test_skips_when_master_not_found(self):
        self.mgr.get_user = MagicMock(return_value=None)

        import shared.transactional_email as te
        with patch.object(te, "send_enrollment_expired_alert") as mock_send:
            self.mgr._notify_master_enrollment_expired("m1", "student@x.com")
            mock_send.assert_not_called()
