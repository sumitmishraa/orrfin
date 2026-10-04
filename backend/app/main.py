"""FastAPI application factory and the /health endpoint (BUILD_PLAN §4, milestone M0).

Business routers (procurement, invoices, review, audit, sync) are added here
as later steps build them.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.router import router as auth_router
from app.config import get_settings
from app.errors import DomainError
from app.modules.invoices.router import router as invoices_router
from app.modules.procurement.router import router as procurement_router
from app.modules.review.router import router as review_router
from app.modules.sync.router import router as sync_router


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

    @app.exception_handler(DomainError)
    def domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        # A refused business action: same status code and plain-English reason as the rule.
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    app.include_router(auth_router)
    app.include_router(procurement_router)
    app.include_router(sync_router)
    app.include_router(invoices_router)
    app.include_router(review_router)
    return app


app = create_app()
