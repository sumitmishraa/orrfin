"""Connector catalogue and adapter registry (BUILD_PLAN §4 "registry picks the org's connected ERP"; ADR 0004, 0006).

`CATALOGUE` lists every ERP Orrfin can plug into: its name and segment, the badge it earns when live
(Live / Sandbox), the keys the founder pastes on the Connectors page, and the hosts Orrfin may call.
`get_adapter(connection)` is the only place credentials are decrypted and an adapter is built.

Every connector has a *simulated* mode (fixtures in the vendor's published API format, answered by an
in-process fake server) and, where a free test system exists, a *live* mode. Only `sync`,
`connectors` and `erp_outbox` call `get_adapter`.
"""

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
        system="tallyprime", name="TallyPrime", segment="Most Indian SMBs", live_label="live", step=16, built=False,
        signup="https://tallysolutions.com/download (free Educational mode)"),
    "busy": ConnectorSpec(
        system="busy", name="BUSY", segment="Indian SMB, traders", live_label="simulated", step=16, built=False,
        signup="No public API: drafts become an XML import file",
        note="File-based: Orrfin writes an import file that a person loads into BUSY."),
    "business_central": ConnectorSpec(
        system="business_central", name="Microsoft Dynamics 365 Business Central", segment="Mid-market, global and India",
        live_label="live", step=17, built=False,
        signup="https://dynamics.microsoft.com/business-central (30-day trial, work email)"),
    "dynamics_fo": ConnectorSpec(
        system="dynamics_fo", name="Microsoft Dynamics 365 Finance & Operations", segment="Large enterprise",
        live_label="simulated", step=17, built=False, signup="Partner or customer environment only"),
    "sap_s4": ConnectorSpec(
        system="sap_s4", name="SAP S/4HANA Cloud", segment="Large enterprise", live_label="sandbox", step=18,
        built=False, signup="https://api.sap.com (free account → Show API Key)"),
    "sap_b1": ConnectorSpec(
        system="sap_b1", name="SAP Business One", segment="Mid-market", live_label="simulated", step=18, built=False,
        signup="Partner demo licence only"),
    "oracle_fusion": ConnectorSpec(
        system="oracle_fusion", name="Oracle Fusion Cloud ERP", segment="Large enterprise", live_label="simulated",
        step=19, built=False, signup="Customer pod only"),
    "netsuite": ConnectorSpec(
        system="netsuite", name="Oracle NetSuite", segment="Mid-market, fast-growing companies",
        live_label="simulated", step=19, built=False, signup="Customer sandbox only"),
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
