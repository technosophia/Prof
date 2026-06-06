#!/usr/bin/env python3
"""Send a Tally webhook payload to the local autodiag server for manual testing."""

import argparse
import json
import sys
from pathlib import Path

import requests

TESTS_DIR = Path(__file__).parent
DEFAULT_PAYLOAD = TESTS_DIR / "tally-webhook.json"

DEFAULT_URL = "http://localhost:8001/webhook/tally"


def main():
    parser = argparse.ArgumentParser(description="Simulate a Tally webhook call")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Webhook URL (default: {DEFAULT_URL})")
    parser.add_argument("--secret", required=True, help="WEBHOOK_SECRET value")
    parser.add_argument(
        "--payload",
        default=str(DEFAULT_PAYLOAD),
        help=f"Path to JSON payload file (default: {DEFAULT_PAYLOAD})",
    )
    parser.add_argument(
        "--email",
        help="Override the respondent email in the payload",
    )
    args = parser.parse_args()

    payload_path = Path(args.payload)
    if not payload_path.exists():
        print(f"ERROR: payload file not found: {payload_path}", file=sys.stderr)
        sys.exit(1)

    with open(payload_path) as f:
        payload = json.load(f)

    if args.email:
        for field in payload.get("data", {}).get("fields", []):
            if field.get("type") == "INPUT_EMAIL":
                print(f"  Overriding email: {field['value']} → {args.email}")
                field["value"] = args.email

    full_url = f"{args.url}?secret={args.secret}"
    print(f"POST {full_url}")
    print(f"Payload: {payload_path}")
    print()

    try:
        resp = requests.post(full_url, json=payload, timeout=30)
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Could not connect to {args.url}", file=sys.stderr)
        print("Is the autodiag server running?", file=sys.stderr)
        sys.exit(1)

    print(f"HTTP {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception:
        print(resp.text)

    sys.exit(0 if resp.ok else 1)


if __name__ == "__main__":
    main()
