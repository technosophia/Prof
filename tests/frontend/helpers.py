"""Helpers for frontend API integration tests."""

from __future__ import annotations

import json


def parse_sse_stream(text: str) -> list[dict]:
    """Parse SSE response body into normalized event dictionaries."""
    events: list[dict] = []
    for block in text.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        data_lines = [line[len("data:") :].strip() for line in lines if line.startswith("data:")]
        if not data_lines:
            continue

        payload = "\n".join(data_lines)
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        if isinstance(event, dict) and "type" in event:
            events.append({"type": str(event.get("type")), "content": str(event.get("content", ""))})
    return events


def assert_sse_sequence(events: list[dict], *expected_types: str):
    """Assert that expected event types appear in order."""
    assert events, "Expected at least one SSE event"

    search_start = 0
    for expected in expected_types:
        for idx in range(search_start, len(events)):
            if events[idx].get("type") == expected:
                search_start = idx + 1
                break
        else:
            actual = [event.get("type") for event in events]
            raise AssertionError(f"Could not find event type '{expected}' in order. Got: {actual}")


def reconstruct_response(events: list[dict]) -> str:
    """Concatenate all chunk event content."""
    return "".join(event.get("content", "") for event in events if event.get("type") == "chunk")
