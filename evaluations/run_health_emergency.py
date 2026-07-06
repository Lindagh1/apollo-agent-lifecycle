#!/usr/bin/env python3
"""Run the live Apollo health-emergency regression gate."""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request


BASE_URL = os.getenv(
    "APOLLO_CONSOLE_URL",
    "http://apollo-console:8080",
).rstrip("/")
VERIFY_TLS = os.getenv(
    "APOLLO_VERIFY_TLS",
    "false",
).lower() == "true"


def main() -> int:
    url = (
        f"{BASE_URL}/api/evaluations/"
        "health-emergency-regression"
    )
    context = None

    if url.startswith("https://") and not VERIFY_TLS:
        context = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(
            url,
            timeout=180,
            context=context,
        ) as response:
            payload = json.loads(response.read())
    except urllib.error.URLError as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": str(error),
                    "url": url,
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(payload, indent=2))

    return 0 if payload.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
