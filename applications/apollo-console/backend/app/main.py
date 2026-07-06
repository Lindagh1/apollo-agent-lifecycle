from __future__ import annotations

import json
import os
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

POLICY_MCP_URL = os.getenv(
    "POLICY_MCP_URL",
    "http://policy-mcp:8080/mcp",
)

EXPECTED_POLICY_ID = "FED-NOVA-HEALTH-EMERGENCY-2027"


app = FastAPI(
    title="Apollo Operations Console API",
    version="0.2.0",
)


async def search_policies() -> dict[str, Any]:
    async with streamablehttp_client(POLICY_MCP_URL) as (
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
                "search_policies",
                arguments={
                    "airline": "fedora-air",
                    "disruption_type": "health",
                    "travel_date": "2027-01-15",
                    "event_id": "nova-health-emergency",
                },
            )

            for content in result.content:
                text = getattr(content, "text", None)

                if text:
                    return json.loads(text)

    raise RuntimeError(
        "policy-mcp returned no JSON response"
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "apollo-console",
        "version": "0.2.0",
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

    try:
        retrieval = await search_policies()
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"policy-mcp call failed: {error}",
        ) from error

    selected_policy_id = retrieval.get(
        "recommendedPolicyId"
    )

    policies = retrieval.get("policies", [])

    selected_policy = next(
        (
            policy
            for policy in policies
            if policy.get("policyId")
            == selected_policy_id
        ),
        {},
    )

    return {
        "caseId": case_id,
        "airline": "Fedora Air",
        "scenario": "Nova Health Emergency",
        "travelDate": "2027-01-15",
        "expectedPolicyId": EXPECTED_POLICY_ID,
        "expectedAction": "human-review",
        "selectedPolicyId": selected_policy_id,
        "actualAction": selected_policy.get(
            "recommendedAction"
        ),
        "passed": (
            selected_policy_id
            == EXPECTED_POLICY_ID
        ),
        "execution": [
            {
                "component": "booking-mcp",
                "status": "healthy",
            },
            {
                "component": "disruption-mcp",
                "status": "healthy",
            },
            {
                "component": "policy-mcp",
                "status": (
                    "healthy"
                    if selected_policy_id
                    == EXPECTED_POLICY_ID
                    else "failed"
                ),
            },
            {
                "component": "model-decision",
                "status": "not-connected",
            },
            {
                "component": "case-management-mcp",
                "status": "not-connected",
            },
        ],
        "retrieval": retrieval,
        "policies": policies,
    }


app.mount(
    "/",
    StaticFiles(
        directory=FRONTEND_DIRECTORY,
        html=True,
    ),
    name="frontend",
)
