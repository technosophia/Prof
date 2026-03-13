from __future__ import annotations

import pytest

from tests.frontend.helpers import parse_sse_stream

pytestmark = pytest.mark.asyncio


async def test_conversation_crud_lifecycle(client, auth_headers, users):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])

    initial = await client.get("/api/conversations", headers=headers)
    assert initial.status_code == 200

    create_response = await client.post("/api/conversations", json={"title": "my title"}, headers=headers)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["id"]
    assert created["title"] == "my title"
    assert created["message_count"] == 0

    listed = await client.get("/api/conversations", headers=headers)
    assert listed.status_code == 200
    assert created["id"] in {conversation["id"] for conversation in listed.json()}

    rename_response = await client.patch(
        f"/api/conversations/{created['id']}", json={"title": "renamed"}, headers=headers
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["title"] == "renamed"

    delete_response = await client.delete(f"/api/conversations/{created['id']}", headers=headers)
    assert delete_response.status_code == 200

    deleted_messages = await client.get(f"/api/conversations/{created['id']}/messages", headers=headers)
    assert deleted_messages.status_code == 404


async def test_conversation_access_control(client, auth_headers, users, create_conversation):
    owner_headers = await auth_headers("normal2_m1", users["normal2_m1"]["password"])
    intruder_headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conversation_id = await create_conversation(owner_headers, "private")

    assert (await client.get(f"/api/conversations/{conversation_id}/messages", headers=intruder_headers)).status_code == 404
    assert (await client.delete(f"/api/conversations/{conversation_id}", headers=intruder_headers)).status_code == 404
    assert (
        await client.patch(
            f"/api/conversations/{conversation_id}",
            json={"title": "cannot rename"},
            headers=intruder_headers,
        )
    ).status_code == 404


@pytest.mark.ollama
async def test_stats_endpoint_scope_and_updates(client, auth_headers, users, create_conversation):
    normal_headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    master_headers = await auth_headers("master1", users["master1"]["password"])
    admin_headers = await auth_headers("admin", users["admin"]["password"])

    assert (await client.get("/api/conversations/stats/users", headers=normal_headers)).status_code == 403

    master_stats = await client.get("/api/conversations/stats/users", headers=master_headers)
    assert master_stats.status_code == 200
    master_ids = {item["user_id"] for item in master_stats.json()}
    assert {"master1", "normal1_m1", "normal2_m1"}.issubset(master_ids)
    assert "master2" not in master_ids

    admin_stats = await client.get("/api/conversations/stats/users", headers=admin_headers)
    assert admin_stats.status_code == 200
    assert "master2" in {item["user_id"] for item in admin_stats.json()}

    conv_id = await create_conversation(normal_headers, "stats-update")
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "hello"},
        headers=normal_headers,
    ) as stream_response:
        _ = parse_sse_stream((await stream_response.aread()).decode("utf-8"))

    updated_master_stats = await client.get("/api/conversations/stats/users", headers=master_headers)
    normal1_stats = next(item for item in updated_master_stats.json() if item["user_id"] == "normal1_m1")
    assert normal1_stats["conversation_count"] >= 1
    assert normal1_stats["total_messages"] >= 2


@pytest.mark.ollama
async def test_message_list_after_chat(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "message-list")

    assert (await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json() == []

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "Say hello in one sentence"},
        headers=headers,
    ) as stream_response:
        _ = parse_sse_stream((await stream_response.aread()).decode("utf-8"))

    payload = (await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()
    assert len(payload) == 2
    assert payload[0]["role"] == "user"
    assert payload[1]["role"] == "assistant"
