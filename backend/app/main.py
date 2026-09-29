"""FastAPI application factory and the /health endpoint (BUILD_PLAN §4, milestone M0).

Business routers (procurement, invoices, review, audit, sync) are added here
as later steps build them.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    # Credentials are allowed because Step 3 uses a server-side session cookie.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        # Liveness only: answers even if Postgres is down, so a restart loop
        # can't be caused by a database blip.
        return HealthResponse(status="ok")

    return app


app = create_app()
