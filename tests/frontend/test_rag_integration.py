from __future__ import annotations

import pytest

from tests.frontend.helpers import assert_not_mock_response, parse_sse_stream, reconstruct_response

pytestmark = [pytest.mark.asyncio, pytest.mark.ollama, pytest.mark.slow]


async def test_rag_voss_index_threshold(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "rag-voss-index")

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "What is the voss_index in DepotDB and what happens when it exceeds the threshold?"},
        headers=headers,
    ) as response:
        answer = reconstruct_response(parse_sse_stream((await response.aread()).decode("utf-8")))

    assert_not_mock_response(answer)
    assert "0.85" in answer or "85" in answer
    assert len((await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()) == 2


async def test_rag_routeforge_nxg(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "rag-routeforge")

    async with client.stream(
        "POST", "/api/chat/stream", json={"conversation_id": conv_id, "message": "What is RouteForge and what file format does it use?"}, headers=headers
    ) as response:
        answer = reconstruct_response(parse_sse_stream((await response.aread()).decode("utf-8")))

    assert_not_mock_response(answer)
    assert "nxg" in answer.lower()
    assert len((await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()) == 2


async def test_rag_voss_review_trigger(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "rag-review")

    async with client.stream(
        "POST", "/api/chat/stream", json={"conversation_id": conv_id, "message": "When is a Voss Review triggered at Nexoria?"}, headers=headers
    ) as response:
        answer = reconstruct_response(parse_sse_stream((await response.aread()).decode("utf-8")))

    assert_not_mock_response(answer)
    assert "400" in answer
    assert len((await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()) == 2


async def test_rag_tuesday_sync(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "rag-tuesday")

    async with client.stream(
        "POST", "/api/chat/stream", json={"conversation_id": conv_id, "message": "How does the Tuesday Sync captain rotation work?"}, headers=headers
    ) as response:
        answer = reconstruct_response(parse_sse_stream((await response.aread()).decode("utf-8")))

    assert_not_mock_response(answer)
    assert "tuesday" in answer.lower()
    assert "alphabet" in answer.lower() or "rotation" in answer.lower()
    assert len((await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()) == 2
