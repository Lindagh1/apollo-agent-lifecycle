from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


FRONTEND_DIRECTORY = (
    Path(__file__).resolve().parent.parent
    / "frontend-dist"
)

BOOKING_MCP_URL = os.getenv(
    "BOOKING_MCP_URL",
    "http://booking-mcp:8080/mcp",
)

DISRUPTION_MCP_URL = os.getenv(
    "DISRUPTION_MCP_URL",
    "http://disruption-mcp:8080/mcp",
)

POLICY_MCP_URL = os.getenv(
    "POLICY_MCP_URL",
    "http://policy-mcp:8080/mcp",
)

EXPECTED_POLICY_ID = (
    "FED-NOVA-HEALTH-EMERGENCY-2027"
)


app = FastAPI(
    title="Apollo Operations Console API",
    version="0.3.0",
)


async def call_mcp_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    """Call one MCP tool and return its JSON payload and latency."""

    started = time.perf_counter()

    async with streamablehttp_client(url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            await session.initialize()

            result = await session.call_tool(
                tool_name,
                arguments=arguments,
            )

            structured_content = getattr(
                result,
                "structuredContent",
                None,
            )

            if isinstance(structured_content, dict):
                duration_ms = (
                    time.perf_counter() - started
                ) * 1000

                return structured_content, duration_ms

            for content in result.content:
                text = getattr(content, "text", None)

                if text:
                    duration_ms = (
                        time.perf_counter() - started
                    ) * 1000

                    return json.loads(text), duration_ms

    raise RuntimeError(
        f"{tool_name} returned no JSON response"
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "apollo-console",
        "version": "0.3.0",
    }


@app.get("/api/incidents/{case_id}")
async def get_incident(
    case_id: str,
) -> dict[str, Any]:
    if case_id != "APOLLO-001":
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    execution: list[dict[str, Any]] = []

    # Step 1: retrieve the booking.
    try:
        booking_result, booking_duration = (
            await call_mcp_tool(
                BOOKING_MCP_URL,
                "get_booking",
                {
                    "booking_reference": case_id,
                },
            )
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"booking-mcp failed: {error}",
        ) from error

    if booking_result.get("status") != "found":
        raise HTTPException(
            status_code=404,
            detail="Booking not found",
        )

    booking = booking_result["booking"]

    execution.append(
        {
            "component": "booking-mcp",
            "tool": "get_booking",
            "status": "healthy",
            "durationMs": round(
                booking_duration,
                2,
            ),
            "arguments": {
                "booking_reference": case_id,
            },
        }
    )

    # Step 2: derive the flight ID from the booking
    # and retrieve the disruption.
    try:
        disruption_result, disruption_duration = (
            await call_mcp_tool(
                DISRUPTION_MCP_URL,
                "get_disruption",
                {
                    "flight_id": booking["flightId"],
                },
            )
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"disruption-mcp failed: {error}",
        ) from error

    if disruption_result.get("status") != "found":
        raise HTTPException(
            status_code=404,
            detail="Disruption not found",
        )

    disruption = disruption_result["disruption"]

    execution.append(
        {
            "component": "disruption-mcp",
            "tool": "get_disruption",
            "status": "healthy",
            "durationMs": round(
                disruption_duration,
                2,
            ),
            "arguments": {
                "flight_id": booking["flightId"],
            },
        }
    )

    # Step 3: build the policy search arguments from
    # the real booking and disruption responses.
    policy_arguments = {
        "airline": booking["airline"],
        "disruption_type": (
            disruption["disruptionType"]
        ),
        "travel_date": booking["travelDate"],
        "event_id": disruption["eventId"],
    }

    try:
        policy_result, policy_duration = (
            await call_mcp_tool(
                POLICY_MCP_URL,
                "search_policies",
                policy_arguments,
            )
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"policy-mcp failed: {error}",
        ) from error

    selected_policy_id = policy_result.get(
        "recommendedPolicyId"
    )

    policies = policy_result.get(
        "policies",
        [],
    )

    selected_policy = next(
        (
            policy
            for policy in policies
            if policy.get("policyId")
            == selected_policy_id
        ),
        {},
    )

    passed = (
        selected_policy_id
        == EXPECTED_POLICY_ID
    )

    execution.append(
        {
            "component": "policy-mcp",
            "tool": "search_policies",
            "status": (
                "healthy"
                if passed
                else "failed"
            ),
            "durationMs": round(
                policy_duration,
                2,
            ),
            "arguments": policy_arguments,
        }
    )

    # These components will be connected later.
    execution.extend(
        [
            {
                "component": "model-decision",
                "status": "not-connected",
                "durationMs": None,
            },
            {
                "component": "case-management-mcp",
                "status": "not-connected",
                "durationMs": None,
            },
        ]
    )

    return {
        "caseId": case_id,
        "airline": "Fedora Air",
        "scenario": disruption.get(
            "eventName",
            "Nova Health Emergency",
        ),
        "travelDate": booking["travelDate"],
        "expectedPolicyId": EXPECTED_POLICY_ID,
        "expectedAction": "human-review",
        "selectedPolicyId": selected_policy_id,
        "actualAction": selected_policy.get(
            "recommendedAction"
        ),
        "decisionSource": "policy-mcp",
        "modelConnected": False,
        "passed": passed,
        "booking": booking,
        "disruption": disruption,
        "execution": execution,
        "policies": policies,
        "retrieval": policy_result,
    }


app.mount(
    "/",
    StaticFiles(
        directory=FRONTEND_DIRECTORY,
        html=True,
    ),
    name="frontend",
)
