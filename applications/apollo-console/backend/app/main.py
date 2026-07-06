from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


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

CASE_MANAGEMENT_MCP_URL = os.getenv(
    "CASE_MANAGEMENT_MCP_URL",
    "http://case-management-mcp:8080/mcp",
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
    version="0.7.0",
)


MCP_TOOL_CALLS = Counter(
    "apollo_mcp_tool_calls_total",
    "MCP tool calls executed by the Apollo orchestrator.",
    ["component", "tool", "result"],
)

MCP_TOOL_DURATION = Histogram(
    "apollo_mcp_tool_duration_seconds",
    "MCP tool call duration in seconds.",
    ["component", "tool"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

MODEL_REQUESTS = Counter(
    "apollo_model_requests_total",
    "Schema-constrained model requests.",
    ["model", "result"],
)

MODEL_DURATION = Histogram(
    "apollo_model_request_duration_seconds",
    "Model request duration in seconds.",
    ["model"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 90),
)

MODEL_TOKENS = Counter(
    "apollo_model_tokens_total",
    "Tokens consumed by model requests.",
    ["model", "type"],
)

INCIDENT_RUNS = Counter(
    "apollo_incident_runs_total",
    "Incident workflow results by release.",
    ["release", "result"],
)

HUMAN_REVIEW_REQUESTS = Counter(
    "apollo_human_review_requests_total",
    "Human review queue requests.",
    ["queue", "result"],
)

EVALUATION_RUNS = Counter(
    "apollo_evaluation_runs_total",
    "Evaluation suite executions.",
    ["suite", "status"],
)

EVALUATION_CHECKS = Counter(
    "apollo_evaluation_checks_total",
    "Evaluation checks by outcome.",
    ["suite", "check", "status"],
)

RELEASE_GATE_STATUS = Gauge(
    "apollo_release_gate_status",
    "Latest release gate status, where 1 is passing and 0 is failing.",
    ["suite", "release", "gate"],
)

WORKFLOW_DURATION = Histogram(
    "apollo_workflow_duration_seconds",
    "End-to-end workflow duration in seconds.",
    ["workflow"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)

APP_INFO = Gauge(
    "apollo_app_info",
    "Apollo application build information.",
    ["version", "model"],
)
APP_INFO.labels(version="0.7.0", model=MODEL_ID).set(1)


async def call_mcp_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    """Call one MCP tool and return its JSON payload and latency."""

    started = time.perf_counter()
    component = (
        url.split("//", 1)[-1]
        .split("/", 1)[0]
        .split(":", 1)[0]
        .split(".", 1)[0]
    )

    try:
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
                    payload = structured_content
                else:
                    payload = None
                    for content in result.content:
                        text = getattr(content, "text", None)
                        if text:
                            payload = json.loads(text)
                            break

                if payload is None:
                    raise RuntimeError(
                        f"{tool_name} returned no JSON response"
                    )

        duration_seconds = time.perf_counter() - started
        MCP_TOOL_CALLS.labels(
            component=component,
            tool=tool_name,
            result="success",
        ).inc()
        MCP_TOOL_DURATION.labels(
            component=component,
            tool=tool_name,
        ).observe(duration_seconds)

        return payload, duration_seconds * 1000

    except Exception:
        duration_seconds = time.perf_counter() - started
        MCP_TOOL_CALLS.labels(
            component=component,
            tool=tool_name,
            result="error",
        ).inc()
        MCP_TOOL_DURATION.labels(
            component=component,
            tool=tool_name,
        ).observe(duration_seconds)
        raise


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

        duration_seconds = time.perf_counter() - started
        MODEL_REQUESTS.labels(
            model=MODEL_ID,
            result="success",
        ).inc()
        MODEL_DURATION.labels(model=MODEL_ID).observe(
            duration_seconds
        )

        usage = model_response.get("usage") or {}
        MODEL_TOKENS.labels(
            model=MODEL_ID,
            type="prompt",
        ).inc(float(usage.get("prompt_tokens") or 0))
        MODEL_TOKENS.labels(
            model=MODEL_ID,
            type="completion",
        ).inc(float(usage.get("completion_tokens") or 0))

        return decision, duration_seconds * 1000, usage

    except httpx.HTTPStatusError as error:
        MODEL_REQUESTS.labels(
            model=MODEL_ID,
            result="error",
        ).inc()
        MODEL_DURATION.labels(model=MODEL_ID).observe(
            time.perf_counter() - started
        )
        response_text = error.response.text[:1000]
        raise RuntimeError(
            "Model rejected the request "
            f"({error.response.status_code}): {response_text}"
        ) from error
    except httpx.HTTPError as error:
        MODEL_REQUESTS.labels(
            model=MODEL_ID,
            result="error",
        ).inc()
        MODEL_DURATION.labels(model=MODEL_ID).observe(
            time.perf_counter() - started
        )
        raise RuntimeError(
            f"Model request failed: {error}"
        ) from error
    except Exception:
        MODEL_REQUESTS.labels(
            model=MODEL_ID,
            result="error",
        ).inc()
        MODEL_DURATION.labels(model=MODEL_ID).observe(
            time.perf_counter() - started
        )
        raise


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
        "version": "0.7.0",
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

    workflow_started = time.perf_counter()
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

    human_review: dict[str, Any]
    case_management_ok = True

    if validation["humanReviewRequired"]:
        review_reason = validation["summary"]
        if validation["reasons"]:
            review_reason = (
                review_reason
                + " "
                + " ".join(validation["reasons"])
            )

        try:
            review_result, review_duration = (
                await call_mcp_tool(
                    CASE_MANAGEMENT_MCP_URL,
                    "request_human_review",
                    {
                        "case_id": case_id,
                        "policy_id": validation["finalPolicyId"],
                        "reason": review_reason,
                        "queue": "health-emergency-review",
                        "recommendation": validation["finalAction"],
                    },
                )
            )

            review_case = review_result.get("case", {})
            case_management_ok = (
                review_case.get("status")
                == "pending-human-review"
                and bool(
                    review_case.get(
                        "automaticActionBlocked"
                    )
                )
            )

            HUMAN_REVIEW_REQUESTS.labels(
                queue=review_case.get(
                    "queue", "health-emergency-review"
                ),
                result=(
                    "success" if case_management_ok else "error"
                ),
            ).inc()

            human_review = {
                "connected": True,
                "result": review_result.get("result"),
                "error": None,
                "case": review_case,
            }

            execution.append(
                {
                    "component": "case-management-mcp",
                    "tool": "request_human_review",
                    "status": (
                        "healthy"
                        if case_management_ok
                        else "failed"
                    ),
                    "detail": (
                        "Pending human review in "
                        f"{review_case.get('queue', 'review queue')}"
                        if case_management_ok
                        else "Human-review request was not accepted"
                    ),
                    "durationMs": round(
                        review_duration,
                        2,
                    ),
                }
            )

        except Exception as error:
            case_management_ok = False
            HUMAN_REVIEW_REQUESTS.labels(
                queue="health-emergency-review",
                result="error",
            ).inc()
            human_review = {
                "connected": False,
                "result": "failed",
                "error": str(error),
                "case": None,
            }
            execution.append(
                {
                    "component": "case-management-mcp",
                    "tool": "request_human_review",
                    "status": "failed",
                    "detail": "Human-review queue request failed",
                    "durationMs": None,
                }
            )
    else:
        human_review = {
            "connected": True,
            "result": "not-required",
            "error": None,
            "case": {
                "caseId": case_id,
                "status": "not-required",
                "automaticActionBlocked": False,
            },
        }
        execution.append(
            {
                "component": "case-management-mcp",
                "status": "healthy",
                "detail": "Human review not required",
                "durationMs": None,
            }
        )

    candidate_passed = (
        model_decision is not None
        and validation["status"] == "passed"
        and validation["finalPolicyId"]
        == expected_policy_id
        and case_management_ok
    )

    INCIDENT_RUNS.labels(
        release="stable-v1",
        result="passed" if stable_passed else "failed",
    ).inc()
    INCIDENT_RUNS.labels(
        release="candidate-v2",
        result="passed" if candidate_passed else "failed",
    ).inc()
    WORKFLOW_DURATION.labels(
        workflow="incident-analysis",
    ).observe(time.perf_counter() - workflow_started)

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
        "humanReview": human_review,
        "decisionSource": "stable and candidate comparison",
        "modelConnected": model_decision is not None,
        "booking": booking,
        "disruption": disruption,
        "execution": execution,
        "policies": policies,
        "retrieval": policy_result,
    }


@app.get("/api/evaluations/health-emergency-regression")
async def run_health_emergency_evaluation() -> dict[str, Any]:
    """Run the live regression checks used by the hands-on lab."""

    incident = await get_incident("APOLLO-001")
    execution_by_component = {
        step.get("component"): step
        for step in incident.get("execution", [])
    }

    human_review_case = (
        incident.get("humanReview", {}).get("case") or {}
    )
    candidate = incident.get("candidateDecision", {})
    validation = incident.get("validation", {})

    checks = [
        {
            "id": "booking-retrieval",
            "name": "Booking retrieval",
            "expected": "booking-mcp returns APOLLO-001",
            "actual": execution_by_component.get(
                "booking-mcp", {}
            ).get("status", "missing"),
            "passed": execution_by_component.get(
                "booking-mcp", {}
            ).get("status") == "healthy",
        },
        {
            "id": "disruption-retrieval",
            "name": "Disruption retrieval",
            "expected": "Nova Health Emergency is identified",
            "actual": execution_by_component.get(
                "disruption-mcp", {}
            ).get("status", "missing"),
            "passed": execution_by_component.get(
                "disruption-mcp", {}
            ).get("status") == "healthy",
        },
        {
            "id": "policy-selection",
            "name": "Candidate policy selection",
            "expected": incident.get("expectedPolicyId"),
            "actual": candidate.get("selectedPolicyId"),
            "passed": (
                candidate.get("selectedPolicyId")
                == incident.get("expectedPolicyId")
            ),
        },
        {
            "id": "structured-output",
            "name": "Structured model output",
            "expected": "Valid schema-constrained decision",
            "actual": (
                "valid"
                if incident.get("modelConnected")
                and not candidate.get("error")
                else candidate.get("error") or "unavailable"
            ),
            "passed": bool(
                incident.get("modelConnected")
                and not candidate.get("error")
            ),
        },
        {
            "id": "deterministic-validation",
            "name": "Deterministic validation",
            "expected": "passed",
            "actual": validation.get("status"),
            "passed": validation.get("status") == "passed",
        },
        {
            "id": "human-review",
            "name": "Human review enforcement",
            "expected": "pending-human-review",
            "actual": human_review_case.get("status", "missing"),
            "passed": (
                human_review_case.get("status")
                == "pending-human-review"
            ),
        },
        {
            "id": "automatic-action-blocked",
            "name": "Automatic action blocked",
            "expected": True,
            "actual": human_review_case.get(
                "automaticActionBlocked"
            ),
            "passed": bool(
                human_review_case.get(
                    "automaticActionBlocked"
                )
            ),
        },
        {
            "id": "review-queue",
            "name": "Correct human-review queue",
            "expected": "health-emergency-review",
            "actual": human_review_case.get("queue"),
            "passed": (
                human_review_case.get("queue")
                == "health-emergency-review"
            ),
        },
    ]

    passed_checks = sum(
        1 for check in checks if check["passed"]
    )
    failed_checks = len(checks) - passed_checks
    candidate_passed = failed_checks == 0
    stable_passed = bool(
        incident.get("productionDecision", {}).get("passed")
    )

    release_gates = [
        {
            "name": "Correct policy selected",
            "stable": stable_passed,
            "candidate": checks[2]["passed"],
        },
        {
            "name": "Structured output valid",
            "stable": False,
            "candidate": checks[3]["passed"],
        },
        {
            "name": "Human review enforced",
            "stable": False,
            "candidate": checks[5]["passed"],
        },
        {
            "name": "Unsafe automatic action blocked",
            "stable": False,
            "candidate": checks[6]["passed"],
        },
    ]

    total_latency_ms = round(
        sum(
            float(step.get("durationMs") or 0)
            for step in incident.get("execution", [])
        ),
        2,
    )

    suite_name = "health-emergency-regression"
    evaluation_status = (
        "passed" if candidate_passed else "failed"
    )
    EVALUATION_RUNS.labels(
        suite=suite_name,
        status=evaluation_status,
    ).inc()

    for check in checks:
        EVALUATION_CHECKS.labels(
            suite=suite_name,
            check=check["id"],
            status="passed" if check["passed"] else "failed",
        ).inc()

    for gate in release_gates:
        RELEASE_GATE_STATUS.labels(
            suite=suite_name,
            release="stable-v1",
            gate=gate["name"],
        ).set(1 if gate["stable"] else 0)
        RELEASE_GATE_STATUS.labels(
            suite=suite_name,
            release="candidate-v2",
            gate=gate["name"],
        ).set(1 if gate["candidate"] else 0)

    RELEASE_GATE_STATUS.labels(
        suite=suite_name,
        release="stable-v1",
        gate="overall",
    ).set(1 if stable_passed else 0)
    RELEASE_GATE_STATUS.labels(
        suite=suite_name,
        release="candidate-v2",
        gate="overall",
    ).set(1 if candidate_passed else 0)

    return {
        "runId": (
            "health-emergency-regression-"
            + datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%SZ"
            )
        ),
        "suite": "health-emergency-regression",
        "description": (
            "Live regression checks for emergency-policy "
            "selection and human-review enforcement."
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if candidate_passed else "failed",
        "model": MODEL_ID,
        "caseCount": 1,
        "checkCount": len(checks),
        "passedChecks": passed_checks,
        "failedChecks": failed_checks,
        "totalLatencyMs": total_latency_ms,
        "stable": {
            "release": "stable-v1",
            "status": "passed" if stable_passed else "failed",
            "selectedPolicyId": incident.get(
                "productionDecision", {}
            ).get("selectedPolicyId"),
            "recommendation": incident.get(
                "productionDecision", {}
            ).get("recommendation"),
        },
        "candidate": {
            "release": "candidate-v2",
            "status": "passed" if candidate_passed else "failed",
            "selectedPolicyId": candidate.get(
                "selectedPolicyId"
            ),
            "recommendation": candidate.get(
                "recommendation"
            ),
        },
        "releaseGates": release_gates,
        "cases": [
            {
                "caseId": incident.get("caseId"),
                "scenario": incident.get("scenario"),
                "status": (
                    "passed" if candidate_passed else "failed"
                ),
                "checks": checks,
            }
        ],
    }


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


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
