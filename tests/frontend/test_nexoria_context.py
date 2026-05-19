"""Tests for Nexoria context fulfillment through the frontend API.

This module tests that all context sources (RAG, Memory, Training Program,
Teacher System Prompt) are properly injected when a student chats about
Nexoria-specific topics, and that the LLM responds correctly using that context.

These are HTTP-level integration tests using httpx with ASGI transport.
"""

from __future__ import annotations

import pytest

from tests.frontend.helpers import (
    assert_not_mock_response,
    parse_sse_stream,
    reconstruct_response,
)


pytestmark = [pytest.mark.asyncio, pytest.mark.ollama, pytest.mark.slow]


async def _send_message(client, headers: dict, conv_id: str, message: str) -> str:
    """Send a chat message and return the response text."""
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conv_id, "message": message},
        headers=headers,
    ) as response:
        assert response.status_code == 200, f"Chat stream failed: {response.text}"
        events = parse_sse_stream((await response.aread()).decode("utf-8"))

    response_text = reconstruct_response(events)
    assert response_text, f"No response text for message: {message}"
    assert_not_mock_response(response_text)
    return response_text


async def _get_context(
    client, masq_headers: dict, conv_id: str, message_index: int
) -> dict:
    """Get the context for a specific message index via masquerading."""
    response = await client.get(
        f"/api/conversations/{conv_id}/messages/{message_index}/context",
        headers=masq_headers,
    )
    assert response.status_code == 200, f"Context retrieval failed: {response.text}"
    payload = response.json()
    assert payload.get("found") is True, (
        f"No LLM call found for message index {message_index}"
    )
    return payload


def _extract_context_sources(context_messages: list[dict]) -> dict[str, str]:
    """Extract context sources and their content from context_messages.

    Returns a dict mapping source names to their content.
    """
    return {msg.get("source", ""): msg.get("content", "") for msg in context_messages}


def _assert_context_source_present(
    sources: dict[str, str],
    source_pattern: str,
    description: str,
) -> None:
    """Assert that a context source matching the pattern is present."""
    matching = [s for s in sources.keys() if source_pattern in s]
    assert matching, (
        f"{description}: No context source matching '{source_pattern}' found. "
        f"Available sources: {list(sources.keys())}"
    )


def _assert_context_contains(
    sources: dict[str, str],
    source_pattern: str,
    keywords: list[str],
    description: str,
) -> None:
    """Assert that a context source contains at least one keyword."""
    matching_content = [
        content for source, content in sources.items() if source_pattern in source
    ]
    assert matching_content, (
        f"{description}: No context source matching '{source_pattern}' found. "
        f"Available sources: {list(sources.keys())}"
    )

    combined = " ".join(matching_content)
    found = any(kw in combined for kw in keywords)
    assert found, (
        f"{description}: None of keywords {keywords} found in context. "
        f"Content preview: {combined[:500]}"
    )


def _trigger_memory_analysis(
    student_id: str, trainer_id: str, conversation_id: str
) -> dict:
    """Trigger memory analysis using the driver.

    Memory context is only injected after analysis is triggered.
    This function calls the driver's trigger_memory_analysis action.
    """
    from shared.common import get_driver

    driver = get_driver()
    driver.set_context(
        student_id=student_id,
        trainer_id=trainer_id,
        conversation_id=conversation_id,
    )
    result = driver.do_action("trigger_memory_analysis")
    return result


class TestNexoriaContextFulfillment:
    """Test suite for Nexoria context injection verification."""

    async def test_context_sources_injected_for_nexoria_topics(
        self, client, auth_headers, users, create_conversation
    ):
        """Verify all 4 context sources are injected when chatting about Nexoria."""
        normal_headers = await auth_headers(
            "normal1_m1", users["normal1_m1"]["password"]
        )
        master_headers = await auth_headers("master1", users["master1"]["password"])

        conv_id = await create_conversation(normal_headers, "nexoria-context-sources")

        await _send_message(
            client,
            normal_headers,
            conv_id,
            "I just started at Nexoria and I'm in Phase 2 of the Zephyr Protocol. "
            "Can you explain what RouteForge is and how it relates to the NXG format?",
        )

        await _send_message(
            client,
            normal_headers,
            conv_id,
            "What is the voss_index in DepotDB? What happens when it goes above 0.85?",
        )

        _trigger_memory_analysis("normal1_m1", "master1", conv_id)

        await _send_message(
            client,
            normal_headers,
            conv_id,
            "Tell me more about the FleetOS system.",
        )

        masq_response = await client.post(
            "/api/auth/masquerade",
            json={"target_user_id": "normal1_m1"},
            headers=master_headers,
        )
        assert masq_response.status_code == 200, (
            f"Masquerade failed: {masq_response.text}"
        )
        masq_headers = {
            "Authorization": f"Bearer {masq_response.json()['access_token']}"
        }

        payload = await _get_context(client, masq_headers, conv_id, message_index=5)

        context_messages = payload.get("context_messages", [])
        assert context_messages, "No context messages found - context injection failed"

        sources = _extract_context_sources(context_messages)

        _assert_context_source_present(sources, "rag_context_callback", "RAG context")
        _assert_context_source_present(sources, "memory", "Memory context")
        _assert_context_source_present(
            sources, "training_program", "Training Program context"
        )
        _assert_context_source_present(
            sources, "teacher_system_prompt", "Teacher System Prompt context"
        )

    async def test_rag_context_contains_nexoria_keywords(
        self, client, auth_headers, users, create_conversation
    ):
        """Verify RAG context contains Nexoria-specific keywords that LLM cannot know."""
        normal_headers = await auth_headers(
            "normal1_m1", users["normal1_m1"]["password"]
        )
        master_headers = await auth_headers("master1", users["master1"]["password"])

        conv_id = await create_conversation(normal_headers, "nexoria-rag-keywords")

        await _send_message(
            client,
            normal_headers,
            conv_id,
            "Explain what RouteForge is and what NXG format is used for.",
        )

        masq_response = await client.post(
            "/api/auth/masquerade",
            json={"target_user_id": "normal1_m1"},
            headers=master_headers,
        )
        masq_headers = {
            "Authorization": f"Bearer {masq_response.json()['access_token']}"
        }

        payload = await _get_context(client, masq_headers, conv_id, message_index=1)

        context_messages = payload.get("context_messages", [])
        sources = _extract_context_sources(context_messages)

        _assert_context_contains(
            sources,
            "rag_context_callback",
            ["RouteForge", "NXG", "Nexoria", "FleetOS"],
            "RAG Nexoria keywords",
        )

    async def test_llm_response_uses_rag_context(
        self, client, auth_headers, users, create_conversation
    ):
        """Verify LLM response correctly mentions Nexoria concepts from RAG."""
        normal_headers = await auth_headers(
            "normal1_m1", users["normal1_m1"]["password"]
        )

        conv_id = await create_conversation(normal_headers, "nexoria-llm-response")

        response_text = await _send_message(
            client,
            normal_headers,
            conv_id,
            "What is RouteForge at Nexoria? Keep it brief.",
        )

        assert "RouteForge" in response_text, (
            f"LLM response should mention RouteForge from RAG context. "
            f"Got: {response_text[:300]}"
        )

    async def test_multi_turn_context_consistency(
        self, client, auth_headers, users, create_conversation
    ):
        """Verify context is properly maintained across multiple turns."""
        normal_headers = await auth_headers(
            "normal1_m1", users["normal1_m1"]["password"]
        )
        master_headers = await auth_headers("master1", users["master1"]["password"])

        conv_id = await create_conversation(normal_headers, "nexoria-multi-turn")

        await _send_message(
            client, normal_headers, conv_id, "What is the voss_index metric in DepotDB?"
        )

        response1 = await _send_message(
            client, normal_headers, conv_id, "And what triggers a Voss Review?"
        )

        assert "voss_index" in response1.lower() or "Voss Review" in response1, (
            f"Second response should maintain context from first. Got: {response1[:300]}"
        )

        masq_response = await client.post(
            "/api/auth/masquerade",
            json={"target_user_id": "normal1_m1"},
            headers=master_headers,
        )
        masq_headers = {
            "Authorization": f"Bearer {masq_response.json()['access_token']}"
        }

        payload = await _get_context(client, masq_headers, conv_id, message_index=3)

        context_messages = payload.get("context_messages", [])
        sources = _extract_context_sources(context_messages)

        rag_count = sum(1 for s in sources.keys() if "rag_context_callback" in s)
        assert rag_count > 0, "RAG context should be present in multi-turn conversation"


class TestActiveMasterTrainingProgram:
    """Tests that active_master_id correctly routes the training program context."""

    async def test_training_program_uses_active_master(
        self, client, auth_headers, users, normal1m1_enrolled_under_both_masters
    ):
        """After selecting a different master, inject_training_program returns that master's program."""
        from modules.trainer.context_callbacks import inject_training_program
        from modules.trainer.manager import get_trainer_manager

        headers = await auth_headers("normal1_m1", users["normal1_m1"]["password"])

        # Configure master2 with the same test scenario program used for master1
        tm = get_trainer_manager()
        formation_path = "scenarios:modules/benchmarker/scenarios/nexoria_program.md"
        tm.set_formation_dir("master2", formation_path)

        # Switch active training to master2
        response = await client.post(
            "/api/auth/select-training", json={"master_id": "master2"}, headers=headers
        )
        assert response.status_code == 200

        # Verify the context callback now uses master2's program
        result = inject_training_program("normal1_m1", [])
        assert result is not None
        formatted, role, position = result
        assert "No training program has been configured for this coach." not in formatted
        assert role == "system"
        assert position == "top"
