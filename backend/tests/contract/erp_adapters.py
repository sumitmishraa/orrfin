"""Every ERP adapter the shared contract suite runs against (BUILD_PLAN §4 "one shared contract test suite").

Each entry builds a fresh adapter with in-memory state. "<system>-seeded" entries run the *live*
code path end to end: the adapter seeds a blank simulated ERP through its own API calls ("Prepare
demo data"), then the same contract checks run on what it created. Later steps add their connectors
here; nothing else in the suite changes.
"""

import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from app.adapters.erpnext_client import ErpnextAdapter
from app.adapters.erpnext_fake import FakeErpnextAdapter, simulated_http
from app.adapters.busy import BusyAdapter
from app.adapters.erpnext_sim import FakeFrappeServer
from app.adapters.sim_store import SimStore
from app.adapters.tally import TallyAdapter
from app.adapters.tally_sim import DEMO_COMPANY, FakeTallyServer
from app.config import REPO_ROOT
from app.ports.erp import ErpAdapter
from app.security.outbound import ErpHttp

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


def _tally(server: FakeTallyServer, label: str, educational: bool = False) -> TallyAdapter:
    http = ErpHttp(base_url="http://localhost:9000", transport=httpx.MockTransport(server), erp_name="TallyPrime")
    return TallyAdapter(http, company=DEMO_COMPANY, label=label, educational=educational)


def tally_simulated() -> ErpAdapter:
    return _tally(FakeTallyServer(SimStore(None)), "simulated")


def tally_seeded() -> ErpAdapter:
    adapter = _tally(FakeTallyServer(SimStore(None), empty=True), "live", educational=True)
    adapter.seed_demo_data()
    return adapter


def _bc(server, label: str):
    from app.adapters.business_central import API_HOST, TOKEN_HOST, BusinessCentralAdapter

    transport = httpx.MockTransport(server)
    return BusinessCentralAdapter(
        ErpHttp(base_url=f"{API_HOST}/v2.0/t1/Production/api/v2.0", transport=transport, erp_name="Business Central"),
        ErpHttp(base_url=TOKEN_HOST, transport=transport, erp_name="Microsoft Entra"),
        tenant="t1", client_id="c1", client_secret="bc-secret-123456", company_name=None, label=label)


def bc_simulated() -> ErpAdapter:
    from app.adapters.business_central_sim import FakeBusinessCentral

    return _bc(FakeBusinessCentral(SimStore(None)), "simulated")


def bc_seeded() -> ErpAdapter:
    from app.adapters.business_central_sim import FakeBusinessCentral

    adapter = _bc(FakeBusinessCentral(SimStore(None), empty=True, client_secret="bc-secret-123456"), "live")
    adapter.seed_demo_data()
    adapter.contract_gaps = {"closed_status", "receipts", "tax"}  # see business_central.py docstring
    return adapter


def fo_simulated() -> ErpAdapter:
    from app.adapters.dynamics_fo import DynamicsFoAdapter
    from app.adapters.dynamics_fo_sim import FakeDynamicsFo

    return DynamicsFoAdapter(ErpHttp(base_url="https://orrfin-demo.operations.dynamics.com/data",
                                     transport=httpx.MockTransport(FakeDynamicsFo(SimStore(None))), erp_name="F&O"))


def sap_s4_simulated() -> ErpAdapter:
    from app.adapters.sap_s4 import SapS4Adapter
    from app.adapters.sap_s4_sim import FakeSapS4

    http = ErpHttp(base_url="https://sap.test", transport=httpx.MockTransport(FakeSapS4(SimStore(None))),
                   erp_name="SAP S/4HANA")
    return SapS4Adapter(http, http, label="simulated")


def sap_s4_sandbox() -> ErpAdapter:
    """Sandbox mode: reads need the APIKey header; writes land in a separate simulated store."""
    from app.adapters.sap_s4 import SapS4Adapter
    from app.adapters.sap_s4_sim import FakeSapS4

    read = ErpHttp(base_url="https://sandbox.sap.test", headers={"APIKey": "sap-key-123456"},
                   transport=httpx.MockTransport(FakeSapS4(SimStore(None), api_key="sap-key-123456")),
                   erp_name="SAP API sandbox")
    write = ErpHttp(base_url="https://writes.sap.test",
                    transport=httpx.MockTransport(FakeSapS4(SimStore(None), with_reads=False)), erp_name="SAP writes")
    return SapS4Adapter(read, write, label="sandbox", top=100)


def sap_b1_simulated() -> ErpAdapter:
    from app.adapters.sap_b1 import SapB1Adapter
    from app.adapters.sap_b1_sim import FakeSapB1

    http = ErpHttp(base_url="https://b1.test/b1s/v1", transport=httpx.MockTransport(FakeSapB1(SimStore(None))),
                   erp_name="SAP Business One")
    return SapB1Adapter(http, company_db="SBODEMOIN", user="manager", password="x")


def oracle_simulated() -> ErpAdapter:
    from app.adapters.oracle_fusion import OracleFusionAdapter
    from app.adapters.oracle_fusion_sim import FakeOracleFusion

    return OracleFusionAdapter(ErpHttp(base_url="https://oracle.test", erp_name="Oracle Fusion",
                                       transport=httpx.MockTransport(FakeOracleFusion(SimStore(None)))))


def netsuite_simulated() -> ErpAdapter:
    from app.adapters.netsuite import NetSuiteAdapter
    from app.adapters.netsuite_sim import FakeNetSuite

    return NetSuiteAdapter(ErpHttp(base_url="https://netsuite.test", erp_name="NetSuite",
                                   transport=httpx.MockTransport(FakeNetSuite(SimStore(None)))))


def _zoho(server, label: str, refresh: str):
    from app.adapters.zoho_books import ACCOUNTS_HOST, API_BASE, ZohoBooksAdapter
    from app.adapters.zoho_books_sim import ORG_ID

    transport = httpx.MockTransport(server)
    return ZohoBooksAdapter(ErpHttp(base_url=API_BASE, transport=transport, erp_name="Zoho Books"),
                            ErpHttp(base_url=ACCOUNTS_HOST, transport=transport, erp_name="Zoho Accounts"),
                            client_id="c1", client_secret="zoho-secret-1234", refresh_token=refresh,
                            organization_id=ORG_ID, label=label, bill_drafts_checked=label != "live")


def zoho_simulated() -> ErpAdapter:
    from app.adapters.zoho_books_sim import REFRESH, FakeZohoBooks

    return _zoho(FakeZohoBooks(SimStore(None)), "simulated", REFRESH)


def zoho_seeded() -> ErpAdapter:
    from app.adapters.zoho_books_sim import REFRESH, FakeZohoBooks

    adapter = _zoho(FakeZohoBooks(SimStore(None), empty=True, client_secret="zoho-secret-1234"), "live", REFRESH)
    adapter.seed_demo_data()
    adapter.contract_gaps = {"receipts", "tax"}  # see zoho_books.py docstring
    return adapter


def _odoo(server, label: str):
    from app.adapters.odoo import OdooAdapter

    return OdooAdapter(ErpHttp(base_url="http://localhost:8069", headers={"Authorization": "bearer odoo-key-123456"},
                               transport=httpx.MockTransport(server), erp_name="Odoo"), label=label)


def odoo_simulated() -> ErpAdapter:
    from app.adapters.odoo_sim import FakeOdoo

    return _odoo(FakeOdoo(SimStore(None)), "simulated")


def odoo_seeded() -> ErpAdapter:
    from app.adapters.odoo_sim import FakeOdoo

    adapter = _odoo(FakeOdoo(SimStore(None), empty=True, api_key="odoo-key-123456"), "live")
    adapter.seed_demo_data()
    return adapter


def busy_simulated() -> ErpAdapter:
    return BusyAdapter(SimStore(None), Path(tempfile.mkdtemp(prefix="orrfin-busy-")))


ADAPTERS: dict[str, Callable[[], ErpAdapter]] = {
    "erpnext-simulated": erpnext_simulated,
    "erpnext-seeded": erpnext_seeded,
    "tally-simulated": tally_simulated,
    "tally-seeded": tally_seeded,
    "busy-simulated": busy_simulated,
    "bc-simulated": bc_simulated,
    "bc-seeded": bc_seeded,
    "fo-simulated": fo_simulated,
    "sap-s4-simulated": sap_s4_simulated,
    "sap-s4-sandbox": sap_s4_sandbox,
    "sap-b1-simulated": sap_b1_simulated,
    "oracle-simulated": oracle_simulated,
    "netsuite-simulated": netsuite_simulated,
    "zoho-simulated": zoho_simulated,
    "zoho-seeded": zoho_seeded,
    "odoo-simulated": odoo_simulated,
    "odoo-seeded": odoo_seeded,
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
