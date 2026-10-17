from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, orders, products, stats
from app.auth.router import router as auth_router
from app.core.errors import register_handlers
from app.db.session import engine
from app.obs.setup import setup_observability


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="PulseOps API", lifespan=lifespan)
    for router in (auth_router, products.router, orders.router, stats.router, health.router):
        app.include_router(router)
    register_handlers(app)
    setup_observability(app, engine)
    return app


app = create_app()
