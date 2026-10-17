"""OpenTelemetry tracing: OTLP/HTTP export, FastAPI + SQLAlchemy auto-instrumentation, 100% sampling."""
import functools
import os

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from sqlalchemy.engine import Engine


@functools.cache
def get_provider() -> TracerProvider:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318").rstrip("/")
    provider = TracerProvider(
        resource=Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "pulseops-api")}),
        sampler=ALWAYS_ON,
    )
    # BatchSpanProcessor exports from a background thread with a 2s timeout and a bounded queue:
    # a dead collector costs log noise and dropped spans, never a failed or slow request.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=2)))
    return provider


def setup_tracing(app: FastAPI, engine: Engine) -> None:
    provider = get_provider()
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls="/metrics")
    # The instrumentor is a process-wide singleton, so it covers one engine (the app has exactly one).
    if not SQLAlchemyInstrumentor().is_instrumented_by_opentelemetry:
        SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)
