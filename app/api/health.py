from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        # Transaction-local so the timeout cannot leak into the pooled connection.
        db.execute(select(func.set_config("statement_timeout",
                                          str(get_settings().ready_timeout_ms), True)))
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse({"status": "degraded", "reason": "db"}, status_code=503)
    return {"status": "ok"}
