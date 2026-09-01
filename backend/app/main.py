from fastapi import FastAPI

from app.api.routes import health
from app.api.routes.health import ReadinessProbe


def create_app(*, readiness_probe: ReadinessProbe | None = None) -> FastAPI:
    app = FastAPI(title="Find Me Gamer API", version="1.0.0")
    app.include_router(health.create_router(readiness_probe))
    return app


app = create_app()
