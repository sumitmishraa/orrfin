"""A simulated TallyPrime HTTP server, served in-process through httpx.MockTransport (PROMPTS Step 16; ADR 0006).

Answers the same XML the real TallyPrime does on port 9000 (tally_xml.py): collection exports of Company,
Ledger, StockItem, Unit and Voucher, and "Import Data" for masters and vouchers. Like Tally it refuses
vouchers whose party ledger or stock items don't exist, duplicate voucher numbers of the same type, and
masters that already exist, replying HTTP 200 with ERRORS > 0 and LINEERROR text (Tally's way).
`empty=True` is a fresh company with no demo data, which is how the live seeder is tested.
"""

from typing import Any

import httpx

from app.adapters import tally_xml as tx
from app.adapters.sim_store import SimStore
from app.adapters.tally import render_masters, render_vouchers
from app.erp_demo.canonical import dataset

DEMO_COMPANY = "Orrfin Demo Pvt Ltd"
KINDS = ("LEDGER", "STOCKITEM", "UNIT", "VOUCHER")
# A ledger every new Tally company has (predefined), so an empty company is not completely empty.
PREDEFINED_LEDGERS = [{"NAME": "Cash", "PARENT": "Cash-in-Hand"}]


def _voucher_key(obj: dict[str, Any]) -> str:
    return f"{obj.get('VOUCHERTYPENAME')}|{obj.get('VOUCHERNUMBER')}"


class FakeTallyServer:
    def __init__(self, store: SimStore, *, company: str = DEMO_COMPANY, empty: bool = False):
        self.store = store
        self.company = company
        self.empty = empty

    # --- state: base objects + Orrfin's writes, each with a rising ALTERID like Tally ----------------
    def _base(self) -> dict[str, dict[str, dict[str, Any]]]:
        objects: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in KINDS}
        rendered = [] if self.empty else render_masters(dataset()) + render_vouchers(dataset())
        for led in PREDEFINED_LEDGERS:
            objects["LEDGER"][led["NAME"]] = dict(led)
        for alter_id, (kind, obj) in enumerate(rendered, start=1):
            key = _voucher_key(obj) if kind == "VOUCHER" else obj["NAME"]
            objects[kind][key] = {**obj, "ALTERID": str(alter_id)}
        return objects

    def _objects(self, state: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
        objects = self._base()
        for kind, overlay in state.get("objects", {}).items():
            objects.setdefault(kind, {}).update(overlay)
        return objects

    # --- HTTP ----------------------------------------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content
        try:
            if b"Import Data" in body:
                return self._import(body)
            company, kind = tx.parse_export_request(body)
        except Exception:
            return httpx.Response(200, content=tx.import_reply(0, ["Could not understand the request XML"]))
        if kind.upper() == "COMPANY":
            return httpx.Response(200, content=tx.export_reply("COMPANY", [{"NAME": self.company}]))
        if company and company.lower() != self.company.lower():
            return httpx.Response(200, content=tx.export_reply(kind.upper(), []))
        objects = self._objects(self.store.load()).get(kind.upper(), {})
        return httpx.Response(200, content=tx.export_reply(kind.upper(), list(objects.values())))

    def _import(self, body: bytes) -> httpx.Response:
        company, _report, incoming = tx.parse_import(body)
        if company.lower() != self.company.lower():
            return httpx.Response(200, content=tx.import_reply(0, [f"Company '{company}' is not loaded"]))
        state = self.store.load()
        objects = self._objects(state)
        overlay = state.setdefault("objects", {})
        counter = state.setdefault("counters", {})
        created, errors = 0, []
        for kind, obj in incoming:
            problem = self._validate(kind, obj, objects)
            if problem:
                errors.append(problem)
                continue
            counter["alter"] = counter.get("alter", 1000) + 1
            obj = {**obj, "ALTERID": str(counter["alter"])}
            key = _voucher_key(obj) if kind == "VOUCHER" else obj["NAME"]
            objects.setdefault(kind, {})[key] = obj
            overlay.setdefault(kind, {})[key] = obj
            created += 1
        if created:
            self.store.save(state)
        return httpx.Response(200, content=tx.import_reply(created, errors, counter.get("alter")))

    def _validate(self, kind: str, obj: dict[str, Any], objects) -> str | None:
        if kind in ("LEDGER", "STOCKITEM", "UNIT"):
            if obj.get("NAME") in objects.get(kind, {}):
                return f"{kind.title()} '{obj.get('NAME')}' already exists"
            if kind == "STOCKITEM" and obj.get("BASEUNITS") not in objects.get("UNIT", {}):
                return f"Unit '{obj.get('BASEUNITS')}' does not exist"
            return None
        if kind != "VOUCHER":
            return f"Unsupported object {kind}"
        if _voucher_key(obj) in objects["VOUCHER"]:
            return f"Voucher number '{obj.get('VOUCHERNUMBER')}' already exists"
        if obj.get("PARTYLEDGERNAME") not in objects["LEDGER"]:
            return f"Ledger '{obj.get('PARTYLEDGERNAME')}' does not exist"
        for line in obj.get("INVENTORY") or []:
            if line.get("STOCKITEMNAME") not in objects["STOCKITEM"]:
                return f"Stock Item '{line.get('STOCKITEMNAME')}' does not exist"
            if line.get("PURCHASELEDGER") and line["PURCHASELEDGER"] not in objects["LEDGER"]:
                return f"Ledger '{line['PURCHASELEDGER']}' does not exist"
        for led in obj.get("LEDGERS") or []:
            if led.get("LEDGERNAME") not in objects["LEDGER"]:
                return f"Ledger '{led.get('LEDGERNAME')}' does not exist"
        return None
