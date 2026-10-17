"""Single entry point wiring logs, metrics, /metrics and traces (Contract 4.6)."""
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.engine import Engine

from app.obs.logging import configure_logging
from app.obs.metrics import bind_engine
from app.obs.middleware import ObsMiddleware
from app.obs.tracing import setup_tracing


async def metrics_endpoint() -> Response:
    # async on purpose: runs on the event loop, so a saturated worker threadpool
    # (the S3 scenario) cannot starve Prometheus scrapes.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def setup_observability(app: FastAPI, engine: Engine) -> None:
    if getattr(app.state, "obs_ready", False):
        return
    configure_logging()
    bind_engine(engine)
    app.add_middleware(ObsMiddleware)
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)
    setup_tracing(app, engine)  # last, so the OTel middleware wraps ours and logs carry trace_id
    app.state.obs_ready = True
