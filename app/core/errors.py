from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.reliability.policy import map_db_error

_DB_MESSAGES = {
    "db_unavailable": "Database is unavailable.",
    "db_pool_timeout": "Database is busy, please retry.",
    "internal_error": "Internal server error.",
}
_HTTP_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _response(request: Request, status: int, code: str, message: str, headers=None):
    error = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
    }
    return JSONResponse({"error": error}, status_code=status, headers=headers)


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return _response(request, exc.status_code, code, str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return _response(request, 422, "validation_error", detail)

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError):
        status, code = map_db_error(exc)
        return _response(request, status, code, _DB_MESSAGES[code])

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak the stack trace; observability (Part 5) records the real error.
        return _response(request, 500, "internal_error", _DB_MESSAGES["internal_error"])
