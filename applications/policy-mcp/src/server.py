from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


POLICY_DIRECTORY = Path(
    os.getenv("POLICY_DIRECTORY", "/opt/app-root/policies")
)

BUG_MODE = os.getenv("BUG_MODE", "true").lower() == "true"


policy_search_total = Counter(
    "apollo_policy_search_total",
    "Number of policy searches.",
    ["mode", "result"],
)

policy_candidates_returned = Histogram(
    "apollo_policy_candidates_returned",
    "Number of policy candidates returned per search.",
    buckets=(0, 1, 2, 3, 5, 10),
)

policy_search_duration_seconds = Histogram(
    "apollo_policy_search_duration_seconds",
    "Duration of policy searches.",
)


mcp = FastMCP(
    name="Apollo Policy MCP",
    instructions=(
        "Retrieves fictional airline compensation policies for "
        "travel disruption cases."
    ),
    host="0.0.0.0",
    port=8080,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def load_policies() -> list[dict[str, Any]]:
    """Load all policy YAML files mounted in the container."""

    policies: list[dict[str, Any]] = []

    if not POLICY_DIRECTORY.exists():
        return policies

    for policy_file in sorted(POLICY_DIRECTORY.glob("*.yaml")):
        with policy_file.open(encoding="utf-8") as stream:
            policy = yaml.safe_load(stream)

        if not isinstance(policy, dict):
            continue

        policy["_sourceFile"] = policy_file.name
        policies.append(policy)

    return policies


def policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    metadata = policy.get("metadata", {})
    spec = policy.get("spec", {})
    decision = spec.get("decision", {})

    return {
        "policyId": metadata.get("id"),
        "airline": metadata.get("airline"),
        "priority": metadata.get("priority", 0),
        "name": spec.get("name"),
        "disruptionType": spec.get("disruptionType"),
        "eventId": spec.get("eventId"),
        "effectiveFrom": spec.get("effectiveFrom"),
        "effectiveTo": spec.get("effectiveTo"),
        "recommendedAction": decision.get("recommendedAction"),
        "humanReviewRequired": decision.get(
            "humanReviewRequired"
        ),
        "explanation": spec.get("explanation"),
        "sourceFile": policy.get("_sourceFile"),
    }


def is_valid_on(policy: dict[str, Any], travel_date: date) -> bool:
    spec = policy.get("spec", {})

    effective_from = date.fromisoformat(spec["effectiveFrom"])
    effective_to = date.fromisoformat(spec["effectiveTo"])

    return effective_from <= travel_date <= effective_to


@mcp.tool()
def list_policies() -> dict[str, Any]:
    """List all airline policies available to Apollo."""

    policies = [policy_summary(policy) for policy in load_policies()]

    return {
        "count": len(policies),
        "policies": policies,
    }


@mcp.tool()
def get_policy(policy_id: str) -> dict[str, Any]:
    """Retrieve one policy by its unique identifier."""

    for policy in load_policies():
        metadata = policy.get("metadata", {})

        if metadata.get("id") == policy_id:
            return {
                "status": "found",
                "policy": policy_summary(policy),
            }

    return {
        "status": "not_found",
        "policyId": policy_id,
    }


@mcp.tool()
def search_policies(
    airline: str,
    disruption_type: str,
    travel_date: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Search for policies applicable to a disruption case.

    In BUG_MODE, the implementation intentionally ignores validity
    dates, event-specific overrides, and priority ordering.
    """

    started = time.perf_counter()
    policies = load_policies()

    candidates = [
        policy
        for policy in policies
        if policy.get("metadata", {}).get("airline") == airline
        and policy.get("spec", {}).get("disruptionType")
        == disruption_type
    ]

    if BUG_MODE:
        # Intentional production defect:
        # lower-priority general policies are returned first.
        candidates.sort(
            key=lambda policy: policy.get(
                "metadata", {}
            ).get("priority", 0)
        )

    else:
        requested_date = date.fromisoformat(travel_date)

        candidates = [
            policy
            for policy in candidates
            if is_valid_on(policy, requested_date)
        ]

        event_specific = [
            policy
            for policy in candidates
            if policy.get("spec", {}).get("eventId") == event_id
        ]

        if event_specific:
            candidates = event_specific

        candidates.sort(
            key=lambda policy: policy.get(
                "metadata", {}
            ).get("priority", 0),
            reverse=True,
        )

    summaries = [
        policy_summary(policy)
        for policy in candidates
    ]

    result = "found" if summaries else "not_found"

    policy_search_total.labels(
        mode="bug" if BUG_MODE else "corrected",
        result=result,
    ).inc()

    policy_candidates_returned.observe(len(summaries))

    policy_search_duration_seconds.observe(
        time.perf_counter() - started
    )

    recommended_policy_id = (
        summaries[0]["policyId"]
        if summaries
        else None
    )

    return {
        "status": result,
        "bugMode": BUG_MODE,
        "query": {
            "airline": airline,
            "disruptionType": disruption_type,
            "travelDate": travel_date,
            "eventId": event_id,
        },
        "candidateCount": len(summaries),
        "recommendedPolicyId": recommended_policy_id,
        "policies": summaries,
    }


@mcp.custom_route("/healthz", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    policies = load_policies()

    return JSONResponse(
        {
            "status": "ok",
            "service": "policy-mcp",
            "bugMode": BUG_MODE,
            "policyCount": len(policies),
        }
    )


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics(_: Request) -> Response:
    return Response(
        generate_latest(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")