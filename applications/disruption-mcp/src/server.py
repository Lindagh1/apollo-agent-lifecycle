from __future__ import annotations

import os
import time
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


DISRUPTION_FILE = Path(
    os.getenv(
        "DISRUPTION_FILE",
        "/opt/app-root/data/disruptions.yaml",
    )
)

disruption_requests_total = Counter(
    "apollo_disruption_requests_total",
    "Number of disruption lookup requests.",
    ["result"],
)

disruption_request_duration_seconds = Histogram(
    "apollo_disruption_request_duration_seconds",
    "Duration of disruption lookup requests.",
)

mcp = FastMCP(
    name="Apollo Disruption MCP",
    instructions=(
        "Retrieves fictional airline disruption information "
        "for Apollo travel cases."
    ),
    host="0.0.0.0",
    port=8080,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def load_disruptions() -> list[dict[str, Any]]:
    if not DISRUPTION_FILE.exists():
        return []

    with DISRUPTION_FILE.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}

    disruptions = payload.get("disruptions", [])

    if not isinstance(disruptions, list):
        return []

    return disruptions


@mcp.tool()
def get_disruption(
    flight_id: str,
) -> dict[str, Any]:
    """Retrieve disruption information for a flight."""

    started = time.perf_counter()

    for disruption in load_disruptions():
        if disruption.get("flightId") == flight_id:
            disruption_requests_total.labels(
                result="found",
            ).inc()

            disruption_request_duration_seconds.observe(
                time.perf_counter() - started
            )

            return {
                "status": "found",
                "disruption": disruption,
            }

    disruption_requests_total.labels(
        result="not_found",
    ).inc()

    disruption_request_duration_seconds.observe(
        time.perf_counter() - started
    )

    return {
        "status": "not_found",
        "flightId": flight_id,
    }


@mcp.tool()
def list_disruptions(
    airline: str | None = None,
    disruption_type: str | None = None,
) -> dict[str, Any]:
    """List disruptions with optional filters."""

    disruptions = load_disruptions()

    if airline:
        disruptions = [
            disruption
            for disruption in disruptions
            if disruption.get("airline") == airline
        ]

    if disruption_type:
        disruptions = [
            disruption
            for disruption in disruptions
            if disruption.get("disruptionType")
            == disruption_type
        ]

    return {
        "count": len(disruptions),
        "disruptions": disruptions,
    }


@mcp.custom_route("/healthz", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    disruptions = load_disruptions()

    return JSONResponse(
        {
            "status": "ok",
            "service": "disruption-mcp",
            "disruptionCount": len(disruptions),
        }
    )


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics(_: Request) -> Response:
    return Response(
        generate_latest(),
        headers={
            "Content-Type": CONTENT_TYPE_LATEST,
        },
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
