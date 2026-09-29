"""FakeErpnextAdapter: serves seed/erpnext/*.json as if it were ERPNext (BUILD_PLAN §3, PROMPTS Step 4).

Used until the live Frappe Cloud trial starts (Step 11). The fixtures are shaped like
ERPNext REST replies, and they go through the same translation functions as the live
adapter, so switching over changes the transport only.
"""

from pathlib import Path
from typing import Any

from app.adapters.erpnext import (
    is_submitted,
    load_erpnext_json,
    purchase_order_to_record,
    purchase_receipt_to_record,
    supplier_to_vendor,
)
from app.ports.erp import ErpPurchaseOrder, ErpReceipt, ErpVendor


class FakeErpnextAdapter:
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = fixtures_dir

    def _docs(self, filename: str) -> list[dict[str, Any]]:
        payload = load_erpnext_json((self.fixtures_dir / filename).read_text(encoding="utf-8"))
        return payload["data"]

    def list_vendors(self) -> list[ErpVendor]:
        # Suppliers are masters (never submitted), so "disabled" is the filter, not docstatus.
        return [supplier_to_vendor(d) for d in self._docs("suppliers.json") if not d.get("disabled")]

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        return [purchase_order_to_record(d) for d in self._docs("purchase_orders.json") if is_submitted(d)]

    def list_receipts(self) -> list[ErpReceipt]:
        return [purchase_receipt_to_record(d) for d in self._docs("purchase_receipts.json") if is_submitted(d)]
