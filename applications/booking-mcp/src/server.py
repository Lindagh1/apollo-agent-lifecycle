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


BOOKING_FILE = Path(
    os.getenv(
        "BOOKING_FILE",
        "/opt/app-root/data/bookings.yaml",
    )
)

booking_requests_total = Counter(
    "apollo_booking_requests_total",
    "Number of booking lookup requests.",
    ["result"],
)

booking_request_duration_seconds = Histogram(
    "apollo_booking_request_duration_seconds",
    "Duration of booking lookup requests.",
)

mcp = FastMCP(
    name="Apollo Booking MCP",
    instructions=(
        "Retrieves fictional passenger booking information "
        "for Apollo travel disruption cases."
    ),
    host="0.0.0.0",
    port=8080,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def load_bookings() -> list[dict[str, Any]]:
    if not BOOKING_FILE.exists():
        return []

    with BOOKING_FILE.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}

    bookings = payload.get("bookings", [])

    if not isinstance(bookings, list):
        return []

    return bookings


@mcp.tool()
def get_booking(
    booking_reference: str,
) -> dict[str, Any]:
    """Retrieve a booking by its booking reference."""

    started = time.perf_counter()

    for booking in load_bookings():
        if booking.get("bookingReference") == booking_reference:
            booking_requests_total.labels(
                result="found",
            ).inc()

            booking_request_duration_seconds.observe(
                time.perf_counter() - started
            )

            return {
                "status": "found",
                "booking": booking,
            }

    booking_requests_total.labels(
        result="not_found",
    ).inc()

    booking_request_duration_seconds.observe(
        time.perf_counter() - started
    )

    return {
        "status": "not_found",
        "bookingReference": booking_reference,
    }


@mcp.tool()
def list_bookings(
    airline: str | None = None,
) -> dict[str, Any]:
    """List bookings, optionally filtered by airline."""

    bookings = load_bookings()

    if airline:
        bookings = [
            booking
            for booking in bookings
            if booking.get("airline") == airline
        ]

    return {
        "count": len(bookings),
        "bookings": bookings,
    }


@mcp.custom_route("/healthz", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    bookings = load_bookings()

    return JSONResponse(
        {
            "status": "ok",
            "service": "booking-mcp",
            "bookingCount": len(bookings),
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
