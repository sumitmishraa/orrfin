"""Connector catalogue and adapter registry (BUILD_PLAN §4 "registry picks the org's connected ERP"; ADR 0004, 0006).

`CATALOGUE` lists every ERP Orrfin can plug into: its name and segment, the badge it earns when live
(Live / Sandbox), the keys the founder pastes on the Connectors page, and the hosts Orrfin may call.
`get_adapter(connection)` is the only place credentials are decrypted and an adapter is built.

Every connector has a *simulated* mode (fixtures in the vendor's published API format, answered by an
in-process fake server) and, where a free test system exists, a *live* mode. Only `sync`,
`connectors` and `erp_outbox` call `get_adapter`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import REPO_ROOT, get_settings
from app.ports.erp import ErpAdapter, Label
from app.security.outbound import ErpHttp, HostPolicy, check_base_url
from app.security.secrets import decrypt_credentials

if TYPE_CHECKING:
    from app.models import ErpConnection


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool = False
    help: str = ""
    required: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class ConnectorSpec:
    system: str
    name: str
    segment: str  # who uses it, shown on the card
    live_label: Label  # badge when the live mode is connected ("simulated" = no live mode exists)
    step: int  # PROMPTS step that builds it
    built: bool
    signup: str  # where the founder creates the free account (docs/CONNECT_ERPS.md has the clicks)
    fields: tuple[CredentialField, ...] = ()
    host_policy: HostPolicy = field(default_factory=HostPolicy)
    simulated: Callable[["ErpConnection", Path], ErpAdapter] | None = None
    live: Callable[["ErpConnection", dict[str, str]], ErpAdapter] | None = None
    note: str = ""
    file_based: bool = False  # drafts are import files a person loads (BUSY), downloadable from Orrfin

    @property
    def has_live_mode(self) -> bool:
        return self.live is not None

    @property
    def secret_fields(self) -> set[str]:
        return {f.name for f in self.fields if f.secret}


def sim_state_path(connection: "ErpConnection") -> Path:
    """Where a simulated connection keeps the documents Orrfin wrote to it (synthetic data only)."""
    return REPO_ROOT / get_settings().file_store_dir / "erp-sim" / connection.system / f"{connection.id}.json"


def secret_values(spec: ConnectorSpec, values: dict[str, str]) -> tuple[str, ...]:
    return tuple(v for k, v in values.items() if k in spec.secret_fields and v)


# --- ERPNext (Steps 12-15) ---------------------------------------------------------------------------

def _erpnext_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    from app.adapters.erpnext_fake import FakeErpnextAdapter
    from app.adapters.sim_store import SimStore

    return FakeErpnextAdapter(REPO_ROOT / get_settings().erp_fixtures_dir, SimStore(state))


def _erpnext_live(connection: "ErpConnection", values: dict[str, str]) -> ErpAdapter:
    from app.adapters.erpnext_client import ErpnextAdapter

    spec = CATALOGUE["erpnext"]
    base = check_base_url(values["url"], spec.host_policy)
    token = f"{values['api_key'].strip()}:{values['api_secret'].strip()}"
    http = ErpHttp(base_url=base, headers={"Authorization": f"token {token}", "Accept": "application/json"},
                   secrets=secret_values(spec, values) + (token,), erp_name="ERPNext")
    return ErpnextAdapter(http, label="live", company=values.get("company"))


# --- TallyPrime + BUSY (Step 16) ---------------------------------------------------------------------

TALLY_SIM_URL = "http://localhost:9000"


def _yes(value: str | None, default: bool = True) -> bool:
    return default if not (value or "").strip() else value.strip().lower() in ("yes", "y", "true", "1")


def _tally_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    import httpx

    from app.adapters.sim_store import SimStore
    from app.adapters.tally import TallyAdapter
    from app.adapters.tally_sim import DEMO_COMPANY, FakeTallyServer

    http = ErpHttp(base_url=TALLY_SIM_URL, transport=httpx.MockTransport(FakeTallyServer(SimStore(state))),
                   erp_name="TallyPrime (simulated)")
    return TallyAdapter(http, company=DEMO_COMPANY, label="simulated", educational=False)


def _tally_live(connection: "ErpConnection", values: dict[str, str]) -> ErpAdapter:
    from app.adapters.tally import TallyAdapter

    base = check_base_url(values.get("url") or TALLY_SIM_URL, CATALOGUE["tallyprime"].host_policy)
    http = ErpHttp(base_url=base, erp_name="TallyPrime")
    return TallyAdapter(http, company=values["company"].strip(), label="live",
                        educational=_yes(values.get("educational_mode")))


def _busy_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    from app.adapters.busy import BusyAdapter
    from app.adapters.sim_store import SimStore

    return BusyAdapter(SimStore(state), state.parent / f"{connection.id}-files")


# --- Microsoft: Business Central + F&O (Step 17) ------------------------------------------------------

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _segment(value: str, label: str) -> str:
    """Tenant and environment go into the URL path, so only plain identifiers are accepted."""
    value = (value or "").strip()
    if not _SAFE_SEGMENT.match(value):
        raise LookupError(f"{label} may contain only letters, digits, dots, dashes and underscores.")
    return value


def _bc_adapter(values: dict[str, str], transport, label: Label, secrets: tuple[str, ...]) -> ErpAdapter:
    from app.adapters.business_central import API_HOST, TOKEN_HOST, BusinessCentralAdapter

    tenant = _segment(values["tenant_id"], "Tenant ID")
    environment = _segment(values.get("environment") or "Production", "Environment")
    api = ErpHttp(base_url=f"{API_HOST}/v2.0/{tenant}/{environment}/api/v2.0", transport=transport,
                  secrets=secrets, erp_name="Business Central" + (" (simulated)" if label == "simulated" else ""))
    token = ErpHttp(base_url=TOKEN_HOST, transport=transport, secrets=secrets, erp_name="Microsoft Entra")
    return BusinessCentralAdapter(api, token, tenant=tenant, client_id=values["client_id"].strip(),
                                  client_secret=values["client_secret"].strip(), company_name=values.get("company"),
                                  label=label)


def _bc_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    import httpx

    from app.adapters.business_central_sim import FakeBusinessCentral
    from app.adapters.sim_store import SimStore

    return _bc_adapter({"tenant_id": "simulated", "client_id": "simulated", "client_secret": "simulated"},
                       httpx.MockTransport(FakeBusinessCentral(SimStore(state))), "simulated", ())


def _bc_live(connection: "ErpConnection", values: dict[str, str]) -> ErpAdapter:
    return _bc_adapter(values, None, "live", secret_values(CATALOGUE["business_central"], values))


def _fo_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    import httpx

    from app.adapters.dynamics_fo import DynamicsFoAdapter
    from app.adapters.dynamics_fo_sim import FakeDynamicsFo
    from app.adapters.sim_store import SimStore

    return DynamicsFoAdapter(ErpHttp(base_url="https://orrfin-demo.operations.dynamics.com/data",
                                     transport=httpx.MockTransport(FakeDynamicsFo(SimStore(state))),
                                     erp_name="Dynamics 365 F&O (simulated)"))


# --- SAP: S/4HANA (sandbox read + simulated write) + Business One (Step 18) ---------------------------

SAP_SIM_BASE = "https://orrfin-demo.s4hana.simulated"


def _sap_writes(state: Path) -> ErpHttp:
    import httpx

    from app.adapters.sap_s4_sim import FakeSapS4
    from app.adapters.sim_store import SimStore

    return ErpHttp(base_url=SAP_SIM_BASE, erp_name="SAP S/4HANA (simulated write-back)",
                   transport=httpx.MockTransport(FakeSapS4(SimStore(state), with_reads=False)))


def _sap_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    import httpx

    from app.adapters.sap_s4 import SapS4Adapter
    from app.adapters.sap_s4_sim import FakeSapS4
    from app.adapters.sim_store import SimStore

    http = ErpHttp(base_url=SAP_SIM_BASE, transport=httpx.MockTransport(FakeSapS4(SimStore(state))),
                   erp_name="SAP S/4HANA (simulated)")
    return SapS4Adapter(http, http, label="simulated")


def _sap_sandbox(connection: "ErpConnection", values: dict[str, str]) -> ErpAdapter:
    from app.adapters.sap_s4 import SANDBOX_HOST, SapS4Adapter

    key = values["api_key"].strip()
    read = ErpHttp(base_url=SANDBOX_HOST, headers={"APIKey": key, "Accept": "application/json"}, secrets=(key,),
                   erp_name="SAP API sandbox")
    return SapS4Adapter(read, _sap_writes(sim_state_path(connection)), label="sandbox", top=100)


def _sap_b1_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    import httpx

    from app.adapters.sap_b1 import SapB1Adapter
    from app.adapters.sap_b1_sim import FakeSapB1
    from app.adapters.sim_store import SimStore

    http = ErpHttp(base_url="https://orrfin-demo.b1.simulated/b1s/v1",
                   transport=httpx.MockTransport(FakeSapB1(SimStore(state))), erp_name="SAP Business One (simulated)")
    return SapB1Adapter(http, company_db="SBODEMOIN", user="manager", password="simulated")


# --- Oracle: Fusion + NetSuite (Step 19, both simulated) -----------------------------------------------

def _oracle_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    import httpx

    from app.adapters.oracle_fusion import OracleFusionAdapter
    from app.adapters.oracle_fusion_sim import FakeOracleFusion
    from app.adapters.sim_store import SimStore

    return OracleFusionAdapter(ErpHttp(base_url="https://orrfin-demo.fa.simulated.oraclecloud.com",
                                       transport=httpx.MockTransport(FakeOracleFusion(SimStore(state))),
                                       erp_name="Oracle Fusion (simulated)"))


def _netsuite_simulated(connection: "ErpConnection", state: Path) -> ErpAdapter:
    import httpx

    from app.adapters.netsuite import NetSuiteAdapter
    from app.adapters.netsuite_sim import FakeNetSuite
    from app.adapters.sim_store import SimStore

    return NetSuiteAdapter(ErpHttp(base_url="https://orrfin-demo.suitetalk.api.netsuite.com",
                                   transport=httpx.MockTransport(FakeNetSuite(SimStore(state))),
                                   erp_name="NetSuite (simulated)"))


CATALOGUE: dict[str, ConnectorSpec] = {
    "erpnext": ConnectorSpec(
        system="erpnext", name="ERPNext", segment="Indian SMB and mid-market", live_label="live", step=13, built=True,
        signup="https://frappecloud.com/erpnext (14-day free trial)",
        fields=(
            CredentialField("url", "Site address", help="Your Frappe Cloud site, e.g. https://orrfin-demo.frappe.cloud",
                            placeholder="https://your-site.frappe.cloud"),
            CredentialField("api_key", "API key", help="ERPNext → your user → API Access → Generate Keys"),
            CredentialField("api_secret", "API secret", secret=True, help="Shown once, next to the API key"),
            CredentialField("company", "Company name", required=False,
                            help="Only if the site has more than one company, e.g. Orrfin Demo Pvt Ltd"),
        ),
        host_policy=HostPolicy(patterns=("*.frappe.cloud", "*.erpnext.com", "*.frappe.io"),
                               allow_any_public_https=True),
        simulated=_erpnext_simulated, live=_erpnext_live,
    ),
    "tallyprime": ConnectorSpec(
        system="tallyprime", name="TallyPrime", segment="Most Indian SMBs", live_label="live", step=16, built=True,
        signup="https://tallysolutions.com/download (free Educational mode)",
        fields=(
            CredentialField("url", "Tally address", required=False, placeholder=TALLY_SIM_URL,
                            help="Leave blank for http://localhost:9000 (TallyPrime on this computer)"),
            CredentialField("company", "Company name in TallyPrime", placeholder="Orrfin Demo Pvt Ltd",
                            help="Exactly as shown in TallyPrime; the company must be open"),
            CredentialField("educational_mode", "Educational mode?", required=False, placeholder="yes",
                            help="yes (free mode: vouchers only on some dates) or no (licensed)"),
        ),
        host_policy=HostPolicy(allow_local_http=True),
        simulated=_tally_simulated, live=_tally_live,
        note="Tally runs on this computer; Orrfin talks to it on port 9000."),
    "busy": ConnectorSpec(
        system="busy", name="BUSY", segment="Indian SMB, traders", live_label="simulated", step=16, built=True,
        simulated=_busy_simulated, file_based=True,
        signup="No public API: drafts become an XML import file",
        note="File-based: Orrfin writes an import file that a person loads into BUSY."),
    "business_central": ConnectorSpec(
        system="business_central", name="Microsoft Dynamics 365 Business Central", segment="Mid-market, global and India",
        live_label="live", step=17, built=True,
        signup="https://dynamics.microsoft.com/business-central (30-day trial, work email)",
        fields=(
            CredentialField("tenant_id", "Directory (tenant) ID", help="Entra → App registrations → Orrfin → Overview"),
            CredentialField("client_id", "Application (client) ID", help="Same page as the tenant ID"),
            CredentialField("client_secret", "Client secret value", secret=True,
                            help="Entra → Orrfin → Certificates & secrets → New client secret → copy the Value"),
            CredentialField("environment", "Environment", required=False, placeholder="Production",
                            help="Business Central environment name (blank = Production)"),
            CredentialField("company", "Company name", required=False,
                            help="Only if the environment has more than one company"),
        ),
        host_policy=HostPolicy(patterns=("api.businesscentral.dynamics.com", "login.microsoftonline.com")),
        simulated=_bc_simulated, live=_bc_live),
    "dynamics_fo": ConnectorSpec(
        system="dynamics_fo", name="Microsoft Dynamics 365 Finance & Operations", segment="Large enterprise",
        live_label="simulated", step=17, built=True, signup="Partner or customer environment only",
        simulated=_fo_simulated),
    "sap_s4": ConnectorSpec(
        system="sap_s4", name="SAP S/4HANA Cloud", segment="Large enterprise", live_label="sandbox", step=18,
        built=True, signup="https://api.sap.com (free account → Show API Key)",
        fields=(CredentialField("api_key", "API key", secret=True,
                                help="api.sap.com → log on → your name → Settings → Show API Key"),),
        host_policy=HostPolicy(patterns=("sandbox.api.sap.com",)),
        simulated=_sap_simulated, live=_sap_sandbox,
        note="Sandbox = SAP's own read-only sample data; write-back is simulated."),
    "sap_b1": ConnectorSpec(
        system="sap_b1", name="SAP Business One", segment="Mid-market", live_label="simulated", step=18, built=True,
        signup="Partner demo licence only", simulated=_sap_b1_simulated),
    "oracle_fusion": ConnectorSpec(
        system="oracle_fusion", name="Oracle Fusion Cloud ERP", segment="Large enterprise", live_label="simulated",
        step=19, built=True, signup="Customer pod only", simulated=_oracle_simulated),
    "netsuite": ConnectorSpec(
        system="netsuite", name="Oracle NetSuite", segment="Mid-market, fast-growing companies",
        live_label="simulated", step=19, built=True, signup="Customer sandbox only", simulated=_netsuite_simulated,
        note="Uses NetSuite's own idempotency: drafts are upserted by external ID."),
    "zoho_books": ConnectorSpec(
        system="zoho_books", name="Zoho Books", segment="Indian SMB", live_label="live", step=20, built=False,
        signup="https://www.zoho.com/in/books (free plan)"),
    "odoo": ConnectorSpec(
        system="odoo", name="Odoo", segment="SMB and mid-market", live_label="live", step=20, built=False,
        signup="Nothing to sign up: Odoo runs in Docker on this laptop"),
}

DEFAULT_SYSTEM = "erpnext"


def spec_for(system: str) -> ConnectorSpec:
    try:
        return CATALOGUE[system]
    except KeyError:
        raise LookupError(f"Unknown ERP system '{system}'") from None


def label_for(connection: "ErpConnection") -> Label:
    spec = spec_for(connection.system)
    return spec.live_label if connection.mode == "live" else "simulated"


def get_adapter(connection: "ErpConnection") -> ErpAdapter:
    """Build the adapter for one erp_connections row. Credentials are decrypted here and nowhere else."""
    spec = spec_for(connection.system)
    if not spec.built:
        raise LookupError(f"The {spec.name} connector arrives in Step {spec.step}.")
    if connection.mode == "live":
        if spec.live is None:
            raise LookupError(f"{spec.name} has no live mode in this prototype (no free test system).")
        values: dict[str, Any] = decrypt_credentials(connection.credentials_encrypted)
        missing = [f.label for f in spec.fields if f.required and not str(values.get(f.name) or "").strip()]
        if missing:
            raise LookupError(f"{spec.name}: enter {', '.join(missing)} on the Connectors page first.")
        return spec.live(connection, values)
    if spec.simulated is None:
        raise LookupError(f"{spec.name} has no simulated mode.")
    return spec.simulated(connection, sim_state_path(connection))
