from datetime import datetime, timedelta, timezone

from shared.common import get_user_manager, get_driver
from st_shared.cached import get_db_manager
from modules.feedback.feedback_core import (
    EXPECTED_SERVICES,
    check_services,
    submit_feedback,
    get_feedback_rows,
    clear_feedback,
    time_ago,
)
from modules.feedback.feedback_db import ensure_tables


class TestSharedAPIContract:
    def test_imports(self):
        assert callable(get_db_manager)
        assert callable(get_user_manager)
        assert callable(get_driver)


class TestServicesIntrospection:
    def test_expected_services_present(self):
        from core.service import get_global_services

        services = get_global_services()
        status = check_services(services)
        missing = [name for name, ok in status.items() if not ok]
        assert not missing

    def test_expected_services_shape(self):
        assert "db_manager" in EXPECTED_SERVICES
        assert "user_manager" in EXPECTED_SERVICES


class TestFeedbackCore:
    def _first_user_id(self):
        users = get_user_manager().get_all_users_dict()
        return next(iter(users.keys()))

    def test_time_ago(self):
        now = datetime(2024, 1, 2, tzinfo=timezone.utc)
        assert time_ago(now - timedelta(seconds=10), now=now) == "just now"
        assert time_ago(now - timedelta(minutes=3), now=now) == "3 minutes ago"
        assert time_ago(now - timedelta(hours=2), now=now) == "2 hours ago"
        assert time_ago(now - timedelta(days=4), now=now) == "4 days ago"

    def test_crud_feedback(self):
        db = get_db_manager()
        ensure_tables(db)
        user_id = self._first_user_id()

        feedback_id = submit_feedback(
            db,
            user_id=user_id,
            feedback_type="app",
            sentiment="neutral",
            rating=5,
            comment="Great",
        )
        assert isinstance(feedback_id, str)

        rows = get_feedback_rows(db, get_user_manager(), limit=10)
        assert any(row["id"] == feedback_id for row in rows)

        deleted = clear_feedback(db)
        assert deleted >= 1

    def test_invalid_rating_fails_loudly(self):
        db = get_db_manager()
        user_id = self._first_user_id()
        try:
            submit_feedback(db, user_id=user_id, feedback_type="app", rating=9)
            assert False, "Expected ValueError"
        except ValueError:
            assert True
