"""Orrfin's MCP server: the concierge's tools for other AI clients, under a personal API key (BUILD_PLAN change 47).

A small JSON-RPC 2.0 endpoint at POST /mcp speaking the Model Context Protocol methods a tool
client needs: `initialize`, `tools/list` and `tools/call`. It is the same tool set as the in-app
concierge, bound to the key's owner, so an MCP client can see and propose exactly what that person
could on the pages, and nothing more:
- authentication is `Authorization: Bearer orf_…` only; cookies are ignored here, so a browser
  session can never be borrowed (and the CSRF guard lets this route through only with a bearer key);
- read tools never change anything; propose tools only store a proposal the person submits in the app;
- every call is logged as an agent run, and calls are capped per person per hour.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select

from app.auth.dependencies import DbSession
from app.db import scope_to_org
from app.models import AgentRun
from app.modules.agents.router import log_run
from app.modules.agents.superagents import tools_for
from app.modules.audit.service import to_jsonable
from app.modules.integrations.api_keys import user_for_key
from app.ports.assistant import call_tool

router = APIRouter(tags=["mcp"])
PROTOCOL_VERSION = "2025-06-18"
CALLS_PER_HOUR = 120
AGENT = "concierge"


def _error(request_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status_code=status)


@router.post("/mcp")
async def mcp(request: Request, db: DbSession) -> Response:
    auth = request.headers.get("authorization", "")
    user = user_for_key(db, auth[7:].strip()) if auth.lower().startswith("bearer ") else None
    if user is None:
        return JSONResponse({"error": "A valid Orrfin API key is required."}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    scope_to_org(db, user.org_id)  # row-level security: this call sees the key owner's org only
    try:
        message = json.loads(await request.body())
    except ValueError:
        return _error(None, -32700, "Parse error.")
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request.")
    request_id, method, params = message.get("id"), message["method"], message.get("params") or {}
    if "id" not in message:
        db.commit()  # a notification (e.g. notifications/initialized): nothing to answer, but key use is recorded
        return Response(status_code=202)

    if method == "initialize":
        result: dict[str, Any] = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "orrfin", "version": "3.0"},
                                  "instructions": "Read and propose only. Proposals are submitted by the person in Orrfin."}
    elif method == "tools/list":
        result = {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.parameters}
                            for t in tools_for(db, user, AGENT)]}
    elif method == "tools/call":
        since = datetime.now(UTC) - timedelta(hours=1)
        used = db.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.user_id == user.id, AgentRun.channel == "mcp", AgentRun.created_at >= since)) or 0
        if used >= CALLS_PER_HOUR:
            return _error(request_id, -32000, f"Limit of {CALLS_PER_HOUR} tool calls an hour reached.", 429)
        name, arguments = params.get("name"), params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, -32602, "tools/call needs a tool name and an arguments object.")
        output = call_tool(tools_for(db, user, AGENT), name, arguments)
        proposal = output.get("proposal") if isinstance(output, dict) else None
        log_run(db, user, AGENT, "mcp", [name], [str(proposal["id"])] if proposal else [],
                "error" if "error" in output else "answered")
        result = {"content": [{"type": "text", "text": json.dumps(to_jsonable(output))}], "isError": "error" in output}
    else:
        return _error(request_id, -32601, f"Method {method!r} is not supported.")
    db.commit()
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
