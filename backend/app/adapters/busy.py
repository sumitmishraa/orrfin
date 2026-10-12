"""BUSY adapter: simulated and file-based (BUILD_PLAN §8 "an ERP that cannot hold a draft at all (BUSY) gets a
generated import file that a human imports"; docs/ERP_CONNECTORS.md BUSY row; PROMPTS Step 16).

BUSY has no public API: integrations go through its XML / Excel voucher import. So:
- reads come from the canonical dataset in BUSY's terms (party accounts, "Purchase Order", "Material Received");
- a "draft bill" or "draft PO" is an XML import file written under the connection's simulated folder and
  downloadable from the invoice / request page; a person loads it with BUSY's import;
- the lookup is an index keyed by vendor + supplier invoice no. (bills) and the idempotency key (POs), kept in
  the simulated store, so a retry finds the file it already wrote instead of writing a second one.
The file layout is BUSY-style XML; check it against the template of the BUSY version in use before a pilot.
"""

import re
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from app.adapters.sim_store import SimStore
from app.erp_demo.canonical import Dataset, dataset
from app.ports.erp import (
    Capabilities,
    CheckStep,
    ConnectionCheck,
    Created,
    DraftBill,
    DraftPo,
    ErpPoLine,
    ErpPurchaseOrder,
    ErpReceipt,
    ErpReceiptLine,
    ErpVendor,
    SeedReport,
)

SAFE_NAME = re.compile(r"^ORF-[A-Z0-9-]{6,40}$")


def _vendor_ref(vendor) -> str:
    return f"BUSY-{vendor.key}"  # BUSY account code


class BusyAdapter:
    def __init__(self, store: SimStore, files_dir: Path, data: Dataset | None = None):
        self.store = store
        self.files_dir = files_dir
        self.data = data or dataset()

    def capabilities(self) -> Capabilities:
        return Capabilities(label="simulated",
                            draft_bill_means="an XML import file for a Purchase voucher, loaded into BUSY by a person",
                            draft_po_means="an XML import file for a Purchase Order, loaded into BUSY by a person")

    def test_connection(self) -> ConnectionCheck:
        return ConnectionCheck(ok=True, steps=[CheckStep(
            name="File-based", ok=True, detail="BUSY has no API; Orrfin writes import files you load into BUSY.")])

    # --- reads -----------------------------------------------------------------------------------
    def list_vendors(self) -> list[ErpVendor]:
        return [ErpVendor(erp_ref=_vendor_ref(v), name=v.name, gstin=v.gstin, state_code=v.state_code,
                          modified=v.modified) for v in self.data.vendors]

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        return [ErpPurchaseOrder(
            erp_ref=po.number, vendor_ref=_vendor_ref(po.vendor), po_date=po.po_date, schedule_date=po.schedule_date,
            status=po.status, currency="INR", net_total=po.net_total, tax_total=po.tax_total,
            grand_total=po.grand_total, orrfin_ref=None, modified=po.modified, po_number=po.number,
            lines=[ErpPoLine(erp_ref=f"{po.number}/{i}", line_no=i, item_code=l.item_code, description=l.item_name,
                             hsn=l.hsn, uom=l.uom, qty=l.qty, rate=l.rate, amount=l.amount, tax_rate=l.tax_rate)
                   for i, l in enumerate(po.lines, start=1)]) for po in self.data.purchase_orders]

    def list_receipts(self) -> list[ErpReceipt]:
        receipts = []
        for po in self.data.purchase_orders:
            for r in po.receipts:
                receipts.append(ErpReceipt(
                    erp_ref=r.number, vendor_ref=_vendor_ref(po.vendor), posting_date=r.posting_date,
                    status="Material Received", modified=r.modified,
                    lines=[ErpReceiptLine(erp_ref=f"{r.number}/{i + 1}", item_code=po.lines[i].item_code,
                                          qty_received=q, po_ref=po.number, po_line_ref=f"{po.number}/{i + 1}")
                           for i, q in r.quantities.items()]))
        return receipts

    # --- drafts = import files -------------------------------------------------------------------
    def import_file_path(self, name: str) -> Path:
        """Where the import file for an Orrfin draft lives. Only Orrfin's own names are accepted (no path tricks)."""
        if not SAFE_NAME.match(name):
            raise ValueError("Not an Orrfin import file name")
        return self.files_dir / f"{name}.xml"

    def _write(self, name: str, root: Element) -> None:
        path = self.import_file_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tostring(root, encoding="utf-8", xml_declaration=True))

    @staticmethod
    def _voucher(vch_type: str, number: str, when, party: str, narration: str) -> tuple[Element, Element, Element]:
        root = Element("BusyData")
        voucher = SubElement(SubElement(root, "Vouchers"), "Voucher",
                             {"Type": vch_type, "Series": "Main", "VchNo": number, "Date": when.strftime("%d-%m-%Y")})
        SubElement(voucher, "Party").text = party
        SubElement(voucher, "Narration").text = narration
        return root, voucher, SubElement(voucher, "Items")

    def create_draft_bill(self, bill: DraftBill) -> Created:
        state = self.store.load()
        name = f"ORF-{bill.idempotency_key[:10].upper()}"
        root, voucher, items = self._voucher("Purchase", name, bill.invoice_date, bill.vendor_ref,
                                             f"orrfin:{bill.idempotency_key} | Supplier invoice {bill.supplier_invoice_no}")
        SubElement(voucher, "SupplierInvoiceNo").text = bill.supplier_invoice_no
        SubElement(voucher, "OrderRef").text = bill.po_ref or ""
        for line in bill.lines:
            SubElement(items, "Item", {"Code": line.item_code, "Qty": str(line.qty), "Unit": line.uom or "",
                                       "Price": str(line.rate), "Amount": str(line.amount)})
        taxes = SubElement(voucher, "Taxes")
        for head, amount in (("CGST", bill.cgst), ("SGST", bill.sgst), ("IGST", bill.igst)):
            if amount:
                SubElement(taxes, "Tax", {"Type": head, "Amount": str(amount)})
        self._write(name, root)
        state.setdefault("bills", {})[f"{bill.vendor_ref}|{bill.supplier_invoice_no.strip()}"] = name
        self.store.save(state)
        return Created(erp_doc_name=name, import_file=f"{name}.xml")

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        return self.store.load().get("bills", {}).get(f"{vendor_ref}|{supplier_invoice_no.strip()}")

    def create_draft_po(self, po: DraftPo) -> Created:
        state = self.store.load()
        name = f"ORF-PO-{po.idempotency_key[:10].upper()}"
        root, voucher, items = self._voucher("Purchase Order", name, po.po_date, po.vendor_ref,
                                             f"orrfin:{po.idempotency_key} | {po.request_number}")
        SubElement(voucher, "DueDate").text = po.schedule_date.strftime("%d-%m-%Y")
        for line in po.lines:
            SubElement(items, "Item", {"Code": line.item_code, "Qty": str(line.qty), "Unit": line.uom or "",
                                       "Price": str(line.rate), "Amount": str(line.amount)})
        self._write(name, root)
        state.setdefault("pos", {})[po.idempotency_key] = name
        self.store.save(state)
        return Created(erp_doc_name=name, import_file=f"{name}.xml")

    def find_po(self, orrfin_key: str) -> str | None:
        return self.store.load().get("pos", {}).get(orrfin_key)

    def seed_demo_data(self) -> SeedReport:
        return SeedReport(created={}, existing={},
                          notes=["BUSY is simulated: its demo data comes from the canonical dataset."])
