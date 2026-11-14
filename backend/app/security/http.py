"""Browser-boundary guards for every API request (BUILD_PLAN §9 "Stronger sign-in", v3.0 change 50).

Two things live here:

1. A cross-site request forgery (CSRF) guard. The login session is a cookie, and a browser sends
   cookies with any request to this site, including one started by a page on another website.
   So every request that can change something must prove it came from the Orrfin web app:
   - it carries the header `X-Requested-With: orrfin`. A page on another site cannot add a custom
     header to a cross-site request unless this API's CORS policy allows that header, and it
     does not (app.main allows only Content-Type);
   - if the browser says where the request came from (`Origin`), that address must be the web app.
   The cookie's SameSite=Lax setting is a third, independent layer.

2. Response headers that switch on the browser's own protections.
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.config import Settings

# Methods that only read. Everything else can change data and is checked.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
APP_HEADER = "x-requested-with"
APP_HEADER_VALUE = "orrfin"
MCP_PATH = "/mcp"


def forged_request_reason(method: str, headers: Mapping[str, str], web_origins: Iterable[str]) -> str | None:
    """Why this request cannot be trusted to come from the Orrfin web app, or None if it can."""
    if method.upper() in SAFE_METHODS:
        return None
    if headers.get(APP_HEADER, "").lower() != APP_HEADER_VALUE:
        return "This request did not come from the Orrfin app."
    origin = headers.get("origin")
    # Tools that are not browsers (tests, scripts with an API key) send no Origin; the header
    # check above already covers them. A browser always sends it on a cross-site write.
    if origin is not None and origin.rstrip("/") not in {o.rstrip("/") for o in web_origins}:
        return "This request came from another website."
    return None


def install_http_guards(app: FastAPI, settings: Settings) -> None:
    web_origins = {*settings.cors_origins, settings.public_web_url}

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        reason = forged_request_reason(request.method, request.headers, web_origins)
        if (reason and request.url.path == MCP_PATH and "origin" not in request.headers
                and request.headers.get("authorization", "").lower().startswith("bearer ")):
            # MCP clients are programs with an API key, not browsers. A forged cross-site request cannot
            # carry a bearer key (browsers never add one by themselves), and /mcp ignores cookies.
            reason = None
        response: Response = JSONResponse(status_code=403, content={"detail": reason}) if reason \
            else await call_next(request)

        # The browser must not guess a file's type: an uploaded file is served as what we say it is.
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Other websites cannot put Orrfin inside a frame and trick a click (clickjacking).
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        # Answers hold financial data: never left in a shared or disk cache.
        response.headers.setdefault("Cache-Control", "no-store")
        if settings.session_cookie_secure:
            # Only meaningful on HTTPS (the deployed site); tells the browser never to use plain HTTP.
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
