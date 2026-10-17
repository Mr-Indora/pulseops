"""structlog JSON to stdout; stdlib logging (uvicorn, sqlalchemy) goes through the same pipeline."""
import logging
import sys

import structlog
from opentelemetry import trace


def _add_trace_ids(_logger, _method, event_dict: dict) -> dict:
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging() -> None:
    """Idempotent: replaces only the handler this function installed earlier."""
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        _add_trace_ids,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    ))
    handler._pulseops = True  # type: ignore[attr-defined]
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, "_pulseops", False)] + [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    # The middleware emits the one canonical line per request; uvicorn's access log would duplicate it.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = True
