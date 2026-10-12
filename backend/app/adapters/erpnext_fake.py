"""Simulated ERPNext: the real ERPNext adapter talking to the in-process Frappe server (BUILD_PLAN §3, §4;
PROMPTS Steps 4 and 12).

`FakeErpnextAdapter(fixtures_dir)` serves seed/erpnext/*.json as if it were an ERPNext site. Since
Step 12 it is the live adapter's own HTTP code with `erpnext_sim.FakeFrappeServer` behind it, so the
simulated connector, the tests and the live connector share every line except the transport.
Writes (draft bills and POs) go to `store`, which defaults to memory; the registry passes a file
store so drafts survive a worker restart.
"""

from pathlib import Path

import httpx

from app.adapters.erpnext_client import ErpnextAdapter
from app.adapters.erpnext_sim import FakeFrappeServer
from app.adapters.sim_store import SimStore
from app.security.outbound import ErpHttp

SIMULATED_BASE_URL = "https://erpnext.simulated.orrfin.local"


def simulated_http(server: FakeFrappeServer, erp_name: str = "ERPNext (simulated)") -> ErpHttp:
    return ErpHttp(base_url=SIMULATED_BASE_URL, transport=httpx.MockTransport(server), erp_name=erp_name)


class FakeErpnextAdapter(ErpnextAdapter):
    def __init__(self, fixtures_dir: Path, store: SimStore | None = None):
        self.server = FakeFrappeServer(fixtures_dir, store or SimStore(None))
        super().__init__(simulated_http(self.server), label="simulated")
