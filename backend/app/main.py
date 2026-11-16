"""FastAPI application factory and the /health endpoint (BUILD_PLAN §4, milestone M0).

Business routers (procurement, invoices, review, audit, sync, connectors) are added here
as later steps build them.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.router import router as auth_router
from app.config import get_settings
from app.errors import DomainError
from app.modules.assistant.router import notes_router as assistant_notes_router
from app.modules.assistant.router import router as assistant_router
from app.modules.bank.router import router as bank_router
from app.modules.close.router import router as close_router
from app.modules.connectors.router import router as connectors_router
from app.modules.erp_outbox.router import router as erp_outbox_router
from app.modules.gst.router import router as gst_router
from app.modules.insights.router import router as insights_router
from app.modules.invoices.router import router as invoices_router
from app.modules.payments.router import router as payments_router
from app.modules.procurement.router import router as procurement_router
from app.modules.review.router import router as review_router
from app.modules.rules.router import router as rules_router
from app.modules.workflows.router import router as workflows_router
from app.modules.sync.router import router as sync_router
from app.modules.entities.router import router as entities_router
from app.modules.intake_forms.router import router as intake_forms_router
from app.modules.integrations.router import router as integrations_router
from app.modules.notifications.router import router as notifications_router
from app.mcp_server import router as mcp_router
from app.modules.agents.router import router as agents_router
from app.modules.app_studio.router import router as app_studio_router
from app.modules.team.router import accept_router as team_accept_router
from app.modules.team.router import router as team_router
from app.modules.documents.router import router as documents_router
from app.modules.ordering.router import router as ordering_router
from app.modules.spend.router import router as spend_router
from app.modules.cards.router import router as cards_router
from app.modules.contracts.router import router as contracts_router
from app.modules.sourcing.router import portal_router as sourcing_portal_router
from app.modules.sourcing.router import router as sourcing_router
from app.modules.suppliers.router import portal_router as supplier_portal_router
from app.modules.suppliers.router import router as suppliers_router
from app.modules.workflow_engine.router import router as workflow_engine_router
from app.security.http import install_http_guards


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
        # X-Requested-With is the app's own request marker (security/http.py). It is allowed only
        # for the web app's origin above, which is exactly what makes it proof against forgery.
        allow_headers=["Content-Type", "X-Requested-With"],
    )
    install_http_guards(app, settings)

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
    app.include_router(connectors_router)
    app.include_router(erp_outbox_router)
    app.include_router(insights_router)
    app.include_router(rules_router)
    app.include_router(workflows_router)
    app.include_router(assistant_router)
    app.include_router(assistant_notes_router)
    app.include_router(payments_router)
    app.include_router(bank_router)
    app.include_router(close_router)
    app.include_router(gst_router)
    app.include_router(workflow_engine_router)
    app.include_router(entities_router)
    app.include_router(intake_forms_router)
    app.include_router(notifications_router)
    app.include_router(integrations_router)
    app.include_router(suppliers_router)
    app.include_router(supplier_portal_router)
    app.include_router(sourcing_router)
    app.include_router(sourcing_portal_router)
    app.include_router(contracts_router)
    app.include_router(cards_router)
    app.include_router(agents_router)
    app.include_router(mcp_router)
    app.include_router(spend_router)
    app.include_router(documents_router)
    app.include_router(ordering_router)
    app.include_router(app_studio_router)
    app.include_router(team_router)
    app.include_router(team_accept_router)
    return app


app = create_app()
