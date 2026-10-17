"""Error contract, no database needed: handlers are mounted on a bare FastAPI app."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import AppError, register_handlers


class Body(BaseModel):
    n: int


def _client() -> TestClient:
    app = FastAPI()
    register_handlers(app)

    @app.get("/app-error")
    def app_error():
        raise AppError("insufficient_stock", "nope", 409)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internals")

    @app.post("/body")
    def body(b: Body):
        return b

    return TestClient(app, raise_server_exceptions=False)


def test_app_error_body():
    r = _client().get("/app-error")
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "insufficient_stock", "message": "nope",
                                  "request_id": None}}


def test_unhandled_error_is_generic_500():
    r = _client().get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret internals" not in r.text and "Traceback" not in r.text


def test_validation_and_404_use_error_body():
    c = _client()
    assert c.post("/body", json={"n": "x"}).json()["error"]["code"] == "validation_error"
    assert c.get("/missing").json()["error"]["code"] == "not_found"
