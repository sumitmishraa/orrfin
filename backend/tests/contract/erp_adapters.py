"""Every ERP adapter the shared contract suite runs against (BUILD_PLAN §4 "one shared contract test suite").

Each entry builds a fresh adapter with in-memory state. "<system>-seeded" entries run the *live*
code path end to end: the adapter seeds a blank simulated ERP through its own API calls ("Prepare
demo data"), then the same contract checks run on what it created. Later steps add their connectors
here; nothing else in the suite changes.
"""

from collections.abc import Callable

import httpx

from app.adapters.erpnext_client import ErpnextAdapter
from app.adapters.erpnext_fake import FakeErpnextAdapter, simulated_http
from app.adapters.erpnext_sim import FakeFrappeServer
from app.adapters.sim_store import SimStore
from app.config import REPO_ROOT
from app.ports.erp import ErpAdapter

ERPNEXT_FIXTURES = REPO_ROOT / "seed" / "erpnext"


def erpnext_simulated() -> ErpAdapter:
    return FakeErpnextAdapter(ERPNEXT_FIXTURES)


def erpnext_seeded() -> ErpAdapter:
    server = FakeFrappeServer(None, SimStore(None), empty=True, required_token="key123:secret456")
    http = simulated_http(server, "ERPNext")
    http.client.headers["Authorization"] = "token key123:secret456"
    adapter = ErpnextAdapter(http, label="live")
    adapter.seed_demo_data()
    return adapter


ADAPTERS: dict[str, Callable[[], ErpAdapter]] = {
    "erpnext-simulated": erpnext_simulated,
    "erpnext-seeded": erpnext_seeded,
}


class FlakyTransport(httpx.BaseTransport):
    """Lets the ERP do the work, then loses the reply: "the POST succeeded, then timed out" (§8 failure test)."""

    def __init__(self, inner: httpx.BaseTransport, fail_when: Callable[[httpx.Request], bool]):
        self.inner = inner
        self.fail_when = fail_when
        self.failures = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        if self.fail_when(request) and self.failures == 0:
            self.failures += 1
            raise httpx.ReadTimeout("simulated: the ERP saved the document but the reply was lost", request=request)
        return response
