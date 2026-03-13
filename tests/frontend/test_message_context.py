from __future__ import annotations

import pytest

from tests.frontend.helpers import parse_sse_stream

pytestmark = [pytest.mark.asyncio, pytest.mark.ollama]


async def test_message_context_forbidden_for_normal_user(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "context-forbidden")

    response = await client.get(f"/api/conversations/{conv_id}/messages/1/context", headers=headers)
    assert response.status_code == 403


async def test_message_context_via_masquerading_power_user(client, auth_headers, users, create_conversation):
    normal_headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    master_headers = await auth_headers("master1", users["master1"]["password"])
    conv_id = await create_conversation(normal_headers, "context")

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "Explain Nexoria in one line"},
        headers=normal_headers,
    ) as response:
        _ = parse_sse_stream((await response.aread()).decode("utf-8"))

    masquerade = await client.post("/api/auth/masquerade", json={"target_user_id": "normal1_m1"}, headers=master_headers)
    masq_headers = {"Authorization": f"Bearer {masquerade.json()['access_token']}"}

    payload = (await client.get(f"/api/conversations/{conv_id}/messages/1/context", headers=masq_headers)).json()
    assert payload["found"] is True
    assert payload["input_tokens"] > 0
    assert payload["output_tokens"] > 0
    assert payload["total_tokens"] > 0
    assert payload["model"]
    assert payload["llm_type"]
    assert payload["messages"]


async def test_message_context_index_edge_cases(client, auth_headers, users, create_conversation):
    normal_headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    master_headers = await auth_headers("master1", users["master1"]["password"])
    conv_id = await create_conversation(normal_headers, "context-index")

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "hello"},
        headers=normal_headers,
    ) as response:
        _ = parse_sse_stream((await response.aread()).decode("utf-8"))

    masq = await client.post("/api/auth/masquerade", json={"target_user_id": "normal1_m1"}, headers=master_headers)
    masq_headers = {"Authorization": f"Bearer {masq.json()['access_token']}"}

    at_user_message = await client.get(f"/api/conversations/{conv_id}/messages/0/context", headers=masq_headers)
    assert at_user_message.status_code == 200

    out_of_range = await client.get(f"/api/conversations/{conv_id}/messages/999/context", headers=masq_headers)
    assert out_of_range.json()["found"] is False

    missing = await client.get("/api/conversations/missing-conversation/messages/1/context", headers=masq_headers)
    assert missing.status_code == 404
