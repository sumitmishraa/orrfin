"""HTTP routes for spend insights: the cube as JSON, CSV or PDF (BUILD_PLAN change 49)."""

from datetime import date

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentUser, DbSession
from app.modules.audit.service import to_jsonable
from app.modules.documents.pdf import build
from app.modules.spend import service

router = APIRouter(prefix="/spend", tags=["spend insights"])


@router.get("")
def spend(user: CurrentUser, db: DbSession, group_by: str = Query("vendor"), start: date | None = None,
          end: date | None = None) -> JSONResponse:
    return JSONResponse(to_jsonable(service.cube(db, user, group_by, start, end)))


@router.get("/export.csv")
def spend_csv(user: CurrentUser, db: DbSession, group_by: str = Query("vendor"), start: date | None = None,
              end: date | None = None) -> Response:
    return Response(service.as_csv(service.cube(db, user, group_by, start, end)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="spend-by-{group_by}.csv"'})


@router.get("/export.pdf")
def spend_pdf(user: CurrentUser, db: DbSession, group_by: str = Query("vendor"), start: date | None = None,
              end: date | None = None) -> Response:
    data = service.cube(db, user, group_by, start, end)
    pdf = build(f"Spend by {group_by.replace('_', ' ')}", f"{start or 'start'} to {end or 'today'}", [],
                [group_by.replace("_", " ").title(), "Currency", "Committed", "Invoiced", "Paid"],
                [[r["group"], r["currency"], f"{r['committed']:,.2f}", f"{r['invoiced']:,.2f}", f"{r['paid']:,.2f}"]
                 for r in data["rows"]], notice=data["notes"][0], source=to_jsonable(data))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="spend-by-{group_by}.pdf"'})
