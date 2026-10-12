"""Write-capable ERP adapters for the §8 failure tests (PROMPTS Step 14: "make the failure test a reusable
fixture so Steps 16-20 run it for each adapter").

Each case builds a fresh adapter whose HTTP transport can be wrapped (to inject "saved, then timed out"
or a validation error), and says how to count the documents its server really holds. Later steps add
their connectors to CASES; the tests in this folder then cover them without changes.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update

from app.adapters.erpnext_client import ErpnextAdapter
from app.adapters.erpnext_fake import SIMULATED_BASE_URL
from app.adapters.erpnext_sim import FakeFrappeServer
from app.adapters.sim_store import SimStore
from app.config import REPO_ROOT
from app.jobs import drain
from app.models import Job
from app.ports.erp import ErpAdapter
from app.security.outbound import ErpHttp

Wrap = Callable[[httpx.BaseTransport], httpx.BaseTransport]


@dataclass
class WriteCase:
    name: str
    build: Callable[[Wrap], ErpAdapter]
    count: Callable[[ErpAdapter], dict[str, int]]  # {"bills": n, "pos": n} as the ERP itself holds them
    is_bill_write: Callable[[httpx.Request], bool]
    is_po_write: Callable[[httpx.Request], bool]


def _erpnext_build(wrap: Wrap) -> ErpAdapter:
    server = FakeFrappeServer(REPO_ROOT / "seed" / "erpnext", SimStore(None))
    adapter = ErpnextAdapter(ErpHttp(base_url=SIMULATED_BASE_URL, transport=wrap(httpx.MockTransport(server)),
                                     erp_name="ERPNext (simulated)"), label="simulated")
    adapter.server = server
    return adapter


def _erpnext_count(adapter) -> dict[str, int]:
    docs = adapter.server._docs(adapter.server.store.load())
    return {"bills": len(docs.get("Purchase Invoice", {})),
            "pos": sum(1 for d in docs.get("Purchase Order", {}).values() if d.get("orrfin_ref"))}


def _is_post(path: str) -> Callable[[httpx.Request], bool]:
    return lambda r: r.method == "POST" and r.url.path.replace("%20", " ") == path


CASES: dict[str, WriteCase] = {
    "erpnext": WriteCase("erpnext", _erpnext_build, _erpnext_count,
                         _is_post("/api/resource/Purchase Invoice"), _is_post("/api/resource/Purchase Order")),
}


class SavedThenTimedOut(httpx.BaseTransport):
    """The ERP does the work, then the reply is lost — once (§8 "the POST succeeds, then times out")."""

    def __init__(self, inner: httpx.BaseTransport, when: Callable[[httpx.Request], bool]):
        self.inner, self.when, self.fired = inner, when, 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        if self.when(request) and not self.fired:
            self.fired += 1
            raise httpx.ReadTimeout("simulated: saved in the ERP, reply lost", request=request)
        return response


class Rejects(httpx.BaseTransport):
    """The ERP refuses the write with a validation error, like ERPNext's 417."""

    def __init__(self, inner: httpx.BaseTransport, when: Callable[[httpx.Request], bool]):
        self.inner, self.when = inner, when

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.when(request):
            return httpx.Response(417, json={"exc_type": "ValidationError",
                                             "_server_messages": '["{\\"message\\": \\"Item IT-X is disabled\\"}"]'})
        return self.inner.handle_request(request)


def drain_with_retries(db, rounds: int = 6) -> None:
    """Run jobs, including retries the queue scheduled for later (backoff), until nothing is waiting."""
    for _ in range(rounds):
        drain(db)
        moved = db.execute(update(Job).where(Job.status == "queued")
                           .values(run_after=datetime.now(UTC) - timedelta(seconds=1))).rowcount
        db.commit()
        if not moved:
            return
