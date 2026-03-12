from __future__ import annotations

import pytest

from tests.frontend.helpers import (
    assert_not_mock_response,
    assert_sse_sequence,
    parse_sse_stream,
    reconstruct_response,
)

pytestmark = [pytest.mark.anyio, pytest.mark.ollama]


async def test_stream_event_sequence(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "test stream")

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "Say hello"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        events = parse_sse_stream((await response.aread()).decode("utf-8"))

    assert_sse_sequence(events, "start", "chunk", "done")
    response_text = reconstruct_response(events)
    assert response_text
    assert_not_mock_response(response_text)


async def test_stream_persists_messages(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "persist")
    prompt = "Give a short greeting"

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": prompt},
        headers=headers,
    ) as response:
        assistant_text = reconstruct_response(parse_sse_stream((await response.aread()).decode("utf-8")))
        assert_not_mock_response(assistant_text)

    payload = (await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()
    assert len(payload) == 2
    assert payload[0]["content"] == prompt
    assert payload[1]["content"] == assistant_text


async def test_stream_access_control(client, auth_headers, users, create_conversation):
    owner_headers = await auth_headers("normal2_m1", users["normal2_m1"]["password"])
    intruder_headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(owner_headers, "private stream")

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "hello"},
        headers=intruder_headers,
    ) as response:
        assert response.status_code == 404


async def test_regenerate_replaces_last_assistant_message(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "regen")

    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": "Explain recursion in one sentence"},
        headers=headers,
    ) as response:
        _ = parse_sse_stream((await response.aread()).decode("utf-8"))

    async with client.stream(
        "POST",
        "/api/chat/regenerate-stream",
        json={"conversation_id": conv_id},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        regen_events = parse_sse_stream((await response.aread()).decode("utf-8"))

    assert_sse_sequence(regen_events, "start", "chunk", "done")
    regenerated_text = reconstruct_response(regen_events)
    assert regenerated_text
    assert_not_mock_response(regenerated_text)
    payload = (await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()
    assert len(payload) == 2


async def test_regenerate_errors(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    other_headers = await auth_headers("normal2_m1", users["normal2_m1"]["password"])
    empty_conv = await create_conversation(headers, "empty")

    async with client.stream(
        "POST",
        "/api/chat/regenerate-stream",
        json={"conversation_id": empty_conv},
        headers=headers,
    ) as response:
        assert response.status_code == 400

    foreign_conv = await create_conversation(other_headers, "foreign")
    async with client.stream(
        "POST",
        "/api/chat/regenerate-stream",
        json={"conversation_id": foreign_conv},
        headers=headers,
    ) as response:
        assert response.status_code == 404


async def test_multi_turn_chat(client, auth_headers, users, create_conversation):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    conv_id = await create_conversation(headers, "multi")

    for prompt in ["Say hi", "Now summarize your greeting", "Continue with one more detail"]:
        async with client.stream(
            "POST",
            "/api/chat/stream",
            json={"conversation_id": conv_id, "message": prompt},
            headers=headers,
        ) as response:
            response_text = reconstruct_response(parse_sse_stream((await response.aread()).decode("utf-8")))
            assert response_text
            assert_not_mock_response(response_text)

    assert len((await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).json()) == 6


async def test_stream_invalid_conversation_id(client, auth_headers, users):
    headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": "does-not-exist", "message": "hello"},
        headers=headers,
    ) as response:
        assert response.status_code == 404
