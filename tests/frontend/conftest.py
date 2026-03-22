"""Fixtures for FastAPI frontend API integration tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
import requests

from core.logging import log
from shared.common import get_user_manager


def pytest_configure(config):
    """Override asyncio_mode for this directory.

    The root pyproject.toml sets asyncio_mode=strict which causes pytest-asyncio
    to hijack tests marked with pytest.mark.anyio, running them as [asyncio]
    parametrized tests with broken session-fixture lifecycle.
    Setting auto here makes pytest-asyncio treat async test functions normally,
    leaving pytest-anyio in control as intended.
    """
    config.option.__dict__.setdefault("asyncio_mode", "auto")
    # Force override even if already set by pyproject.toml
    try:
        config._inicache["asyncio_mode"] = "auto"
    except AttributeError:
        pass


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


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
    raw = json.loads(
        (Path(__file__).resolve().parents[1] / "initial_users.json").read_text(
            encoding="utf-8"
        )
    )
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


@pytest.fixture(scope="session", autouse=True)
def setup_nexoria_formation():
    """Set Nexoria training program and memory backend for master1 trainer.

    This allows tests to verify that the training program and memory context
    are properly injected when students (with master1 as trainer) chat about
    Nexoria topics.
    """
    try:
        from modules.trainer.manager import get_trainer_manager

        tm = get_trainer_manager()
        formation_path = "scenarios:modules/benchmarker/scenarios/nexoria_program.md"
        success = tm.set_formation_dir("master1", formation_path)
        if success:
            log("debug", f"[SETUP] Nexoria formation set for master1: {formation_path}")
        else:
            log("warning", f"[SETUP] Failed to set Nexoria formation for master1")
    except Exception as e:
        log("warning", f"[SETUP] Could not set Nexoria formation: {e}")

    try:
        from shared.common import get_driver

        driver = get_driver()
        driver.set_context(trainer_id="master1")
        driver.switch_option("memory_backend", "memory")
        log("debug", "[SETUP] Memory backend set to 'memory'")
    except Exception as e:
        log("warning", f"[SETUP] Could not set memory backend: {e}")


@pytest.fixture
def login(client):
    async def _login(user_id: str, password: str) -> str:
        response = await client.post(
            "/api/auth/login", json={"user_id": user_id, "password": password}
        )
        assert response.status_code == 200, (
            f"Login failed for {user_id}: {response.text}"
        )
        return response.json()["access_token"]

    return _login


@pytest.fixture
def auth_headers(login):
    async def _auth_headers(user_id: str, password: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {await login(user_id, password)}"}

    return _auth_headers


@pytest.fixture
def create_conversation(client):
    async def _create_conversation(
        headers: dict[str, str], title: str = "test conversation"
    ) -> str:
        response = await client.post(
            "/api/conversations", json={"title": title}, headers=headers
        )
        assert response.status_code == 200, response.text
        conversation_id = response.json()["id"]
        log(
            "debug",
            f"Created conversation {conversation_id} for frontend API integration test",
        )
        return conversation_id

    return _create_conversation


@pytest.fixture(autouse=True)
def enforce_ollama_for_marked_tests(request):
    if "ollama" not in request.keywords:
        yield
        return

    from shared.common import get_llm_manager

    llm_manager = get_llm_manager()
    available = {item["id"]: item for item in llm_manager.get_available_llms()}
    ollama = available.get("ollama_qwen")
    if not ollama or not ollama.get("available"):
        pytest.skip("ollama_qwen is not available in this environment")

    if not llm_manager.set_current_llm("ollama_qwen"):
        pytest.skip("Could not select ollama_qwen for integration test")

    try:
        health = requests.get("http://localhost:11434/api/tags", timeout=2)
        if health.status_code != 200:
            pytest.skip("Ollama runtime is not reachable (health check failed)")
    except Exception:
        pytest.skip("Ollama runtime is not reachable")

    previous_force = os.environ.get("FORCE_LLM")
    os.environ["FORCE_LLM"] = "ollama_qwen"
    try:
        yield
    finally:
        if previous_force is None:
            os.environ.pop("FORCE_LLM", None)
        else:
            os.environ["FORCE_LLM"] = previous_force


@pytest.fixture
def issue_reset_code():
    user_manager = get_user_manager()

    def _issue_reset_code(user_id: str, requesting_user_id: str | None = None) -> str:
        reset_code = user_manager.generate_reset_code(
            user_id, requesting_user_id=requesting_user_id
        )
        assert reset_code, f"Could not generate reset code for {user_id}"
        return reset_code

    return _issue_reset_code
