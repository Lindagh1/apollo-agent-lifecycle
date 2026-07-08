from __future__ import annotations

import functools
import inspect
import os
from collections.abc import Callable
from typing import Any, TypeVar, cast

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


F = TypeVar("F", bound=Callable[..., Any])
_CONFIGURED = False


def _safe_attribute(value: Any) -> str | int | float | bool:
    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def configure_telemetry(app: FastAPI) -> None:
    global _CONFIGURED

    if _CONFIGURED:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

    if not endpoint:
        return

    service_name = os.getenv(
        "OTEL_SERVICE_NAME",
        "apollo-console",
    )

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "apollo",
            "deployment.environment": os.getenv(
                "OTEL_DEPLOYMENT_ENVIRONMENT",
                "apollo-dev",
            ),
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint)
        )
    )
    trace.set_tracer_provider(provider)

    @app.middleware("http")
    async def add_trace_id_header(request, call_next):
        response = await call_next(request)
        span_context = trace.get_current_span().get_span_context()

        if span_context.is_valid:
            response.headers["X-Trace-Id"] = (
                f"{span_context.trace_id:032x}"
            )

        return response

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    _CONFIGURED = True


def instrument_async_function(
    function: F,
    span_prefix: str,
    name_argument: str | None = None,
) -> F:
    signature = inspect.signature(function)

    @functools.wraps(function)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind_partial(*args, **kwargs)
        dynamic_name = (
            bound.arguments.get(name_argument)
            if name_argument
            else None
        )
        span_name = (
            f"{span_prefix}.{dynamic_name}"
            if dynamic_name
            else span_prefix
        )

        tracer = trace.get_tracer("apollo-agent-lifecycle")

        with tracer.start_as_current_span(span_name) as span:
            for key, value in bound.arguments.items():
                if key in {
                    "arguments",
                    "booking",
                    "disruption",
                    "policies",
                }:
                    continue

                span.set_attribute(
                    f"apollo.{key}",
                    _safe_attribute(value),
                )

            try:
                result = await function(*args, **kwargs)
                span.set_status(trace.Status(trace.StatusCode.OK))
                return result
            except Exception as error:
                span.record_exception(error)
                span.set_status(
                    trace.Status(
                        trace.StatusCode.ERROR,
                        str(error),
                    )
                )
                raise

    return cast(F, wrapper)


def instrument_sync_function(
    function: F,
    span_name: str,
) -> F:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = trace.get_tracer("apollo-agent-lifecycle")

        with tracer.start_as_current_span(span_name) as span:
            try:
                result = function(*args, **kwargs)
                span.set_status(trace.Status(trace.StatusCode.OK))
                return result
            except Exception as error:
                span.record_exception(error)
                span.set_status(
                    trace.Status(
                        trace.StatusCode.ERROR,
                        str(error),
                    )
                )
                raise

    return cast(F, wrapper)
