"""Fixtures for FastAPI frontend API integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from core.logging import log
from shared.common import get_user_manager


@pytest.fixture(scope="session")
def api_app():
    from api import app

    return app


@pytest.fixture
async def client(api_app):
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def users() -> dict[str, dict]:
    raw = json.loads((Path(__file__).resolve().parents[1] / "initial_users.json").read_text(encoding="utf-8"))
    by_id = {u["id"]: u for u in raw["users"]}

    for user_id, user in by_id.items():
        role = user.get("role")
        if user_id == "admin":
            user["password"] = "admin123"
        elif role == "master":
            user["password"] = "master123"
        else:
            user["password"] = "normal123"
    return by_id


@pytest.fixture(scope="session", autouse=True)
def ensure_test_passwords(users):
    user_manager = get_user_manager()
    for user_id, user in users.items():
        user_manager.set_password(user_id, user["password"], requesting_user_id="admin")


@pytest.fixture
def login(client):
    async def _login(user_id: str, password: str) -> str:
        response = await client.post("/api/auth/login", json={"user_id": user_id, "password": password})
        assert response.status_code == 200, f"Login failed for {user_id}: {response.text}"
        return response.json()["access_token"]

    return _login


@pytest.fixture
def auth_headers(login):
    async def _auth_headers(user_id: str, password: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {await login(user_id, password)}"}

    return _auth_headers


@pytest.fixture
def create_conversation(client):
    async def _create_conversation(headers: dict[str, str], title: str = "test conversation") -> str:
        response = await client.post("/api/conversations", json={"title": title}, headers=headers)
        assert response.status_code == 200, response.text
        conversation_id = response.json()["id"]
        log("debug", f"Created conversation {conversation_id} for frontend API integration test")
        return conversation_id

    return _create_conversation


@pytest.fixture
def issue_reset_code():
    user_manager = get_user_manager()

    def _issue_reset_code(user_id: str, requesting_user_id: str | None = None) -> str:
        reset_code = user_manager.generate_reset_code(user_id, requesting_user_id=requesting_user_id)
        assert reset_code, f"Could not generate reset code for {user_id}"
        return reset_code

    return _issue_reset_code
