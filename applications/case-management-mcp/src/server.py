from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


DATABASE_PATH = Path(
    os.getenv(
        "CASE_DATABASE_PATH",
        "/opt/app-root/state/cases.db",
    )
)

review_requests_total = Counter(
    "apollo_human_review_requests_total",
    "Number of human-review requests.",
    ["result", "queue"],
)

reviewer_decisions_total = Counter(
    "apollo_reviewer_decisions_total",
    "Number of recorded reviewer decisions.",
    ["decision"],
)

case_operation_duration_seconds = Histogram(
    "apollo_case_operation_duration_seconds",
    "Duration of case-management operations.",
    ["operation"],
)

mcp = FastMCP(
    name="Apollo Case Management MCP",
    instructions=(
        "Creates and tracks fictional human-review tasks for "
        "Apollo travel claims. It never performs payments."
    ),
    host="0.0.0.0",
    port=8080,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=10.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_cases (
            case_id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            reason TEXT NOT NULL,
            queue_name TEXT NOT NULL,
            status TEXT NOT NULL,
            automatic_action_blocked INTEGER NOT NULL,
            reviewer TEXT,
            reviewer_decision TEXT,
            reviewer_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


@contextmanager
def database():
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()


def row_to_case(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "caseId": row["case_id"],
        "policyId": row["policy_id"],
        "recommendation": row["recommendation"],
        "reason": row["reason"],
        "queue": row["queue_name"],
        "status": row["status"],
        "automaticActionBlocked": bool(
            row["automatic_action_blocked"]
        ),
        "reviewer": row["reviewer"],
        "reviewerDecision": row["reviewer_decision"],
        "reviewerNotes": row["reviewer_notes"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@mcp.tool()
def request_human_review(
    case_id: str,
    policy_id: str,
    reason: str,
    queue: str = "health-emergency-review",
    recommendation: str = "human-review",
) -> dict[str, Any]:
    """Create an idempotent human-review task for a case."""

    started = time.perf_counter()
    now = utc_now()

    with database() as connection:
        existing = connection.execute(
            "SELECT * FROM review_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()

        if existing is None:
            connection.execute(
                """
                INSERT INTO review_cases (
                    case_id,
                    policy_id,
                    recommendation,
                    reason,
                    queue_name,
                    status,
                    automatic_action_blocked,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    policy_id,
                    recommendation,
                    reason,
                    queue,
                    "pending-human-review",
                    1,
                    now,
                    now,
                ),
            )
            connection.commit()
            result = "created"
        elif existing["status"] == "pending-human-review":
            connection.execute(
                """
                UPDATE review_cases
                SET policy_id = ?,
                    recommendation = ?,
                    reason = ?,
                    queue_name = ?,
                    automatic_action_blocked = 1,
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    policy_id,
                    recommendation,
                    reason,
                    queue,
                    now,
                    case_id,
                ),
            )
            connection.commit()
            result = "existing"
        else:
            result = "already-reviewed"

        row = connection.execute(
            "SELECT * FROM review_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()

    review_requests_total.labels(
        result=result,
        queue=queue,
    ).inc()
    case_operation_duration_seconds.labels(
        operation="request_human_review"
    ).observe(time.perf_counter() - started)

    return {
        "result": result,
        "case": row_to_case(row),
    }


@mcp.tool()
def get_case_status(case_id: str) -> dict[str, Any]:
    """Return the current human-review status for a case."""

    started = time.perf_counter()

    with database() as connection:
        row = connection.execute(
            "SELECT * FROM review_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()

    case_operation_duration_seconds.labels(
        operation="get_case_status"
    ).observe(time.perf_counter() - started)

    if row is None:
        return {
            "status": "not-found",
            "caseId": case_id,
        }

    return {
        "status": "found",
        "case": row_to_case(row),
    }


@mcp.tool()
def record_reviewer_decision(
    case_id: str,
    reviewer: str,
    decision: str,
    notes: str = "",
) -> dict[str, Any]:
    """Record a fictional human reviewer decision for a queued case."""

    allowed_decisions = {
        "approve": "reviewer-approved",
        "reject": "reviewer-rejected",
        "request-more-information": "awaiting-more-information",
    }

    if decision not in allowed_decisions:
        return {
            "status": "invalid-decision",
            "allowedDecisions": sorted(
                allowed_decisions
            ),
        }

    started = time.perf_counter()
    now = utc_now()

    with database() as connection:
        existing = connection.execute(
            "SELECT * FROM review_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()

        if existing is None:
            return {
                "status": "not-found",
                "caseId": case_id,
            }

        connection.execute(
            """
            UPDATE review_cases
            SET status = ?,
                reviewer = ?,
                reviewer_decision = ?,
                reviewer_notes = ?,
                updated_at = ?
            WHERE case_id = ?
            """,
            (
                allowed_decisions[decision],
                reviewer,
                decision,
                notes,
                now,
                case_id,
            ),
        )
        connection.commit()

        row = connection.execute(
            "SELECT * FROM review_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()

    reviewer_decisions_total.labels(
        decision=decision
    ).inc()
    case_operation_duration_seconds.labels(
        operation="record_reviewer_decision"
    ).observe(time.perf_counter() - started)

    return {
        "status": "recorded",
        "case": row_to_case(row),
    }


@mcp.custom_route("/healthz", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    with database() as connection:
        case_count = connection.execute(
            "SELECT COUNT(*) FROM review_cases"
        ).fetchone()[0]

    return JSONResponse(
        {
            "status": "ok",
            "service": "case-management-mcp",
            "caseCount": case_count,
            "storage": "ephemeral-sqlite",
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
