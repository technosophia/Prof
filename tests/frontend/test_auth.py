from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from jose import jwt
import pytest

pytestmark = pytest.mark.asyncio


async def test_login_success(client, users):
    response = await client.post(
        "/api/auth/login",
        json={"user_id": "normal1_m1", "password": users["normal1_m1"]["password"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["id"] == "normal1_m1"
    assert data["user"]["role"] == "normal"


async def test_login_wrong_password(client):
    response = await client.post(
        "/api/auth/login", json={"user_id": "normal1_m1", "password": "wrong"}
    )
    assert response.status_code == 401


async def test_login_unknown_user(client):
    response = await client.post(
        "/api/auth/login", json={"user_id": "ghost", "password": "none"}
    )
    assert response.status_code == 401


async def test_login_missing_fields(client):
    response = await client.post("/api/auth/login", json={"user_id": "normal1_m1"})
    assert response.status_code == 422


async def test_me_with_valid_token(client, auth_headers, users):
    response = await client.get(
        "/api/auth/me",
        headers=await auth_headers("normal1_m1", users["normal1_m1"]["password"]),
    )
    assert response.status_code == 200
    assert response.json()["id"] == "normal1_m1"


async def test_me_without_header(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_me_with_malformed_token(client):
    response = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer badly.formed.token"}
    )
    assert response.status_code == 401


async def test_me_with_expired_token(client):
    payload = {
        "sub": "normal1_m1",
        "role": "normal",
        "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")
    response = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


async def test_masquerade_targets_by_role(client, auth_headers, users):
    normal_targets = await client.get(
        "/api/auth/masquerade-targets",
        headers=await auth_headers("normal1_m1", users["normal1_m1"]["password"]),
    )
    assert normal_targets.status_code == 200
    assert normal_targets.json() == []

    master_targets = await client.get(
        "/api/auth/masquerade-targets",
        headers=await auth_headers("master1", users["master1"]["password"]),
    )
    assert master_targets.status_code == 200
    master_ids = {item["id"] for item in master_targets.json()}
    assert {"normal1_m1", "normal2_m1"}.issubset(master_ids)
    assert "normal1_m2" not in master_ids

    admin_targets = await client.get(
        "/api/auth/masquerade-targets",
        headers=await auth_headers("admin", users["admin"]["password"]),
    )
    assert admin_targets.status_code == 200
    admin_ids = {item["id"] for item in admin_targets.json()}
    assert "normal1_m2" in admin_ids
    assert "normal1_m1" in admin_ids


async def test_masquerade_lifecycle(client, auth_headers, users):
    master_headers = await auth_headers("master1", users["master1"]["password"])
    response = await client.post(
        "/api/auth/masquerade",
        json={"target_user_id": "normal1_m1"},
        headers=master_headers,
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    payload = jwt.get_unverified_claims(token)
    assert payload["sub"] == "normal1_m1"
    assert payload["masquerader_id"] == "master1"

    me_response = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["id"] == "normal1_m1"
    assert me_response.json()["masquerader_id"] == "master1"

    targets_response = await client.get(
        "/api/auth/masquerade-targets", headers={"Authorization": f"Bearer {token}"}
    )
    assert targets_response.status_code == 200
    assert "master1" not in {item["id"] for item in targets_response.json()}

    switch_back_response = await client.post(
        "/api/auth/masquerade",
        json={"target_user_id": "master1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert switch_back_response.status_code == 200

    switched_payload = jwt.get_unverified_claims(
        switch_back_response.json()["access_token"]
    )
    assert switched_payload["sub"] == "master1"
    assert switched_payload.get("masquerader_id") == "master1"


async def test_masquerade_forbidden_cases(client, auth_headers, users):
    master_headers = await auth_headers("master1", users["master1"]["password"])
    cross_tree = await client.post(
        "/api/auth/masquerade",
        json={"target_user_id": "normal1_m2"},
        headers=master_headers,
    )
    assert cross_tree.status_code == 403

    normal_headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    as_normal = await client.post(
        "/api/auth/masquerade",
        json={"target_user_id": "normal2_m1"},
        headers=normal_headers,
    )
    assert as_normal.status_code == 403


async def test_init_password_success(client, issue_reset_code):
    code = issue_reset_code("normal2_m2", requesting_user_id="admin")
    response = await client.post(
        "/api/auth/init-password",
        json={
            "user_id": "normal2_m2",
            "reset_code": code,
            "new_password": "normal2-new-pass",
        },
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_init_password_invalid_code(client):
    response = await client.post(
        "/api/auth/init-password",
        json={
            "user_id": "normal2_m2",
            "reset_code": "invalid",
            "new_password": "some-pass",
        },
    )
    assert response.status_code == 400


async def test_request_password_reset_success(client):
    response = await client.post(
        "/api/auth/request-password-reset",
        json={"user_id": "normal1_m1"},
    )
    assert response.status_code == 200
    assert response.json()["reset_code"]


async def test_request_password_reset_unknown_user(client):
    response = await client.post(
        "/api/auth/request-password-reset",
        json={"user_id": "nonexistent_user"},
    )
    assert response.status_code == 200
    assert "reset_code" not in response.json()
