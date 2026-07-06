from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
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

MODEL_BASE_URL = os.getenv(
    "MODEL_BASE_URL",
    "http://llama-32-3b-instruct-predictor."
    "my-first-model.svc.cluster.local:8080",
)

MODEL_ID = os.getenv(
    "MODEL_ID",
    "llama-32-3b-instruct",
)

MODEL_TIMEOUT_SECONDS = float(
    os.getenv("MODEL_TIMEOUT_SECONDS", "90")
)

EXPECTED_POLICY_ID = (
    "FED-NOVA-HEALTH-EMERGENCY-2027"
)

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "selectedPolicyId": {
            "type": "string",
        },
        "recommendation": {
            "type": "string",
            "enum": [
                "automatic-voucher",
                "human-review",
            ],
        },
        "humanReviewRequired": {
            "type": "boolean",
        },
        "explanation": {
            "type": "string",
        },
    },
    "required": [
        "selectedPolicyId",
        "recommendation",
        "humanReviewRequired",
        "explanation",
    ],
    "additionalProperties": False,
}


app = FastAPI(
    title="Apollo Operations Console API",
    version="0.4.0",
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


async def call_model_decision(
    case_context: dict[str, Any],
    policies: list[dict[str, Any]],
) -> tuple[dict[str, Any], float, dict[str, Any] | None]:
    """Ask the model for a schema-constrained policy decision."""

    payload = {
        "model": MODEL_ID,
        "temperature": 0,
        "max_tokens": 300,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "policy_decision",
                "strict": True,
                "schema": DECISION_SCHEMA,
            },
        },
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a travel claims policy assistant. "
                    "Select exactly one policy from the supplied list. "
                    "An active event-specific temporary policy overrides "
                    "a general policy. Never invent a policy ID. "
                    "When the selected policy requires human review, "
                    "recommend human-review."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "case": case_context,
                        "policies": policies,
                    }
                ),
            },
        ],
    }

    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(
            timeout=MODEL_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                f"{MODEL_BASE_URL.rstrip('/')}"
                "/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            model_response = response.json()

    except httpx.HTTPStatusError as error:
        response_text = error.response.text[:1000]
        raise RuntimeError(
            "Model rejected the request "
            f"({error.response.status_code}): {response_text}"
        ) from error
    except httpx.HTTPError as error:
        raise RuntimeError(
            f"Model request failed: {error}"
        ) from error

    duration_ms = (
        time.perf_counter() - started
    ) * 1000

    try:
        raw_content = (
            model_response["choices"][0]["message"]
            .get("content", "")
            .strip()
        )
        decision = json.loads(raw_content)
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(
            "Model response did not contain a completion message"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Model returned invalid JSON: {raw_content[:500]}"
        ) from error

    return (
        decision,
        duration_ms,
        model_response.get("usage"),
    )


def policy_is_effective(
    policy: dict[str, Any],
    travel_date: str,
) -> bool:
    """Return True when the policy covers the travel date."""

    effective_from = policy.get("effectiveFrom")
    effective_to = policy.get("effectiveTo")

    if not effective_from or not effective_to:
        return False

    try:
        requested_date = date.fromisoformat(travel_date)
        start_date = date.fromisoformat(effective_from)
        end_date = date.fromisoformat(effective_to)
    except (TypeError, ValueError):
        return False

    return start_date <= requested_date <= end_date


def determine_expected_policy(
    policies: list[dict[str, Any]],
    event_id: str | None,
    travel_date: str,
) -> dict[str, Any] | None:
    """Deterministically select the applicable highest-priority policy."""

    active_policies = [
        policy
        for policy in policies
        if policy_is_effective(policy, travel_date)
    ]

    event_policies = [
        policy
        for policy in active_policies
        if event_id
        and policy.get("eventId") == event_id
    ]

    candidates = event_policies or [
        policy
        for policy in active_policies
        if not policy.get("eventId")
    ]

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda policy: int(
            policy.get("priority", 0)
        ),
    )


def validate_model_decision(
    decision: dict[str, Any],
    policies: list[dict[str, Any]],
    expected_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply deterministic controls after the model recommendation."""

    reasons: list[str] = []
    selected_policy_id = decision.get(
        "selectedPolicyId"
    )

    selected_policy = next(
        (
            policy
            for policy in policies
            if policy.get("policyId")
            == selected_policy_id
        ),
        None,
    )

    if selected_policy is None:
        reasons.append(
            "The model selected a policy that was not retrieved."
        )

    if expected_policy is None:
        reasons.append(
            "No uniquely applicable policy could be determined."
        )
    elif (
        selected_policy_id
        != expected_policy.get("policyId")
    ):
        reasons.append(
            "The model did not select the applicable "
            "highest-priority policy."
        )

    if selected_policy is not None:
        expected_recommendation = selected_policy.get(
            "recommendedAction"
        )
        expected_human_review = bool(
            selected_policy.get("humanReviewRequired")
        )

        if (
            decision.get("recommendation")
            != expected_recommendation
        ):
            reasons.append(
                "The recommendation does not match the selected policy."
            )

        if bool(
            decision.get("humanReviewRequired")
        ) != expected_human_review:
            reasons.append(
                "The human-review flag does not match the selected policy."
            )

    final_policy = expected_policy or selected_policy
    final_policy_id = (
        final_policy.get("policyId")
        if final_policy
        else None
    )
    human_review_required = (
        bool(final_policy.get("humanReviewRequired"))
        if final_policy
        else True
    )
    final_action = (
        "human-review"
        if human_review_required or reasons
        else final_policy.get("recommendedAction")
        if final_policy
        else "human-review"
    )

    return {
        "status": "blocked" if reasons else "passed",
        "finalPolicyId": final_policy_id,
        "finalAction": final_action,
        "humanReviewRequired": (
            human_review_required or bool(reasons)
        ),
        "automaticActionAllowed": (
            not human_review_required
            and not reasons
            and final_action != "human-review"
        ),
        "reasons": reasons,
        "summary": (
            "Model decision accepted. Human review is required."
            if not reasons and human_review_required
            else "Model decision accepted by deterministic validation."
            if not reasons
            else "Unsafe or inconsistent model output was blocked."
        ),
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "apollo-console",
        "version": "0.4.0",
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
            "detail": "Booking context retrieved",
            "durationMs": round(
                booking_duration,
                2,
            ),
            "arguments": {
                "booking_reference": case_id,
            },
        }
    )

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
            "detail": "Health emergency identified",
            "durationMs": round(
                disruption_duration,
                2,
            ),
            "arguments": {
                "flight_id": booking["flightId"],
            },
        }
    )

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

    policies = policy_result.get("policies", [])
    stable_policy_id = policy_result.get(
        "recommendedPolicyId"
    )
    stable_policy = next(
        (
            policy
            for policy in policies
            if policy.get("policyId")
            == stable_policy_id
        ),
        {},
    )

    expected_policy = determine_expected_policy(
        policies,
        disruption.get("eventId"),
        booking["travelDate"],
    )
    expected_policy_id = (
        expected_policy.get("policyId")
        if expected_policy
        else EXPECTED_POLICY_ID
    )
    stable_passed = (
        stable_policy_id == expected_policy_id
    )

    execution.append(
        {
            "component": "policy-mcp",
            "tool": "search_policies",
            "status": (
                "healthy"
                if stable_passed
                else "failed"
            ),
            "detail": (
                "Applicable override ranked first"
                if stable_passed
                else "General policy ranked before emergency override"
            ),
            "durationMs": round(
                policy_duration,
                2,
            ),
            "arguments": policy_arguments,
        }
    )

    case_context = {
        "caseId": case_id,
        "airline": booking["airline"],
        "travelDate": booking["travelDate"],
        "flightId": booking["flightId"],
        "requestedAmount": booking.get(
            "requestedAmount"
        ),
        "disruptionType": disruption.get(
            "disruptionType"
        ),
        "eventId": disruption.get("eventId"),
        "eventName": disruption.get("eventName"),
        "flightStatus": disruption.get("status"),
    }

    model_error: str | None = None
    model_decision: dict[str, Any] | None = None
    model_usage: dict[str, Any] | None = None
    validation: dict[str, Any]

    try:
        (
            model_decision,
            model_duration,
            model_usage,
        ) = await call_model_decision(
            case_context,
            policies,
        )

        execution.append(
            {
                "component": "model-decision",
                "tool": "chat-completions",
                "status": "healthy",
                "detail": "Structured policy recommendation produced",
                "durationMs": round(
                    model_duration,
                    2,
                ),
            }
        )

        validation = validate_model_decision(
            model_decision,
            policies,
            expected_policy,
        )

    except Exception as error:
        model_error = str(error)
        execution.append(
            {
                "component": "model-decision",
                "tool": "chat-completions",
                "status": "failed",
                "detail": "Model decision unavailable",
                "durationMs": None,
            }
        )
        validation = {
            "status": "blocked",
            "finalPolicyId": expected_policy_id,
            "finalAction": "human-review",
            "humanReviewRequired": True,
            "automaticActionAllowed": False,
            "reasons": [
                "The model decision was unavailable or invalid."
            ],
            "summary": (
                "Automatic processing was blocked and the case "
                "was routed to human review."
            ),
        }

    execution.append(
        {
            "component": "deterministic-validation",
            "status": (
                "healthy"
                if validation["status"] == "passed"
                else "blocked"
            ),
            "detail": validation["summary"],
            "durationMs": None,
        }
    )

    execution.append(
        {
            "component": "case-management-mcp",
            "status": "not-connected",
            "detail": "Human-review queue integration is next",
            "durationMs": None,
        }
    )

    candidate_passed = (
        model_decision is not None
        and validation["status"] == "passed"
        and validation["finalPolicyId"]
        == expected_policy_id
    )

    return {
        "caseId": case_id,
        "airline": "Fedora Air",
        "scenario": disruption.get(
            "eventName",
            "Nova Health Emergency",
        ),
        "travelDate": booking["travelDate"],
        "expectedPolicyId": expected_policy_id,
        "expectedAction": (
            expected_policy.get("recommendedAction")
            if expected_policy
            else "human-review"
        ),
        "selectedPolicyId": stable_policy_id,
        "actualAction": stable_policy.get(
            "recommendedAction"
        ),
        "passed": stable_passed,
        "productionDecision": {
            "release": "stable-v1",
            "source": "policy-mcp recommendation",
            "selectedPolicyId": stable_policy_id,
            "recommendation": stable_policy.get(
                "recommendedAction"
            ),
            "humanReviewRequired": bool(
                stable_policy.get("humanReviewRequired")
            ),
            "passed": stable_passed,
        },
        "candidateDecision": {
            "release": "candidate-v2",
            "model": MODEL_ID,
            "selectedPolicyId": (
                model_decision.get("selectedPolicyId")
                if model_decision
                else None
            ),
            "recommendation": (
                model_decision.get("recommendation")
                if model_decision
                else None
            ),
            "humanReviewRequired": (
                model_decision.get("humanReviewRequired")
                if model_decision
                else None
            ),
            "explanation": (
                model_decision.get("explanation")
                if model_decision
                else None
            ),
            "passed": candidate_passed,
            "error": model_error,
            "usage": model_usage,
        },
        "validation": validation,
        "decisionSource": "stable and candidate comparison",
        "modelConnected": model_decision is not None,
        "booking": booking,
        "disruption": disruption,
        "execution": execution,
        "policies": policies,
        "retrieval": policy_result,
    }


@app.get("/api/model-test")
async def model_test() -> dict[str, Any]:
    """Test the same schema-constrained model path used by the incident."""

    policies = [
        {
            "policyId": "FED-HEALTH-GENERAL-2027",
            "priority": 10,
            "eventId": None,
            "effectiveFrom": "2027-01-01",
            "effectiveTo": "2027-12-31",
            "recommendedAction": "automatic-voucher",
            "humanReviewRequired": False,
        },
        {
            "policyId": "FED-NOVA-HEALTH-EMERGENCY-2027",
            "priority": 100,
            "eventId": "nova-health-emergency",
            "effectiveFrom": "2027-01-10",
            "effectiveTo": "2027-02-10",
            "recommendedAction": "human-review",
            "humanReviewRequired": True,
        },
    ]

    case_context = {
        "caseId": "APOLLO-001",
        "airline": "fedora-air",
        "travelDate": "2027-01-15",
        "disruptionType": "health",
        "eventId": "nova-health-emergency",
    }

    try:
        decision, duration_ms, usage = (
            await call_model_decision(
                case_context,
                policies,
            )
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Model call failed: {error}",
        ) from error

    expected_policy = determine_expected_policy(
        policies,
        case_context["eventId"],
        case_context["travelDate"],
    )

    return {
        "model": MODEL_ID,
        "modelBaseUrl": MODEL_BASE_URL,
        "validJson": True,
        "decision": decision,
        "validation": validate_model_decision(
            decision,
            policies,
            expected_policy,
        ),
        "durationMs": round(duration_ms, 2),
        "usage": usage,
    }


app.mount(
    "/",
    StaticFiles(
        directory=FRONTEND_DIRECTORY,
        html=True,
    ),
    name="frontend",
)
