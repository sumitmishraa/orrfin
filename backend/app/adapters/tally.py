"""TallyPrime adapter (BUILD_PLAN §4, §8 per-ERP table; docs/ERP_CONNECTORS.md Tally rows; PROMPTS Step 16).

Tally runs on the customer's PC and answers XML on http://localhost:9000 (tally_xml.py). Mapping:
- vendor        = ledger under "Sundry Creditors" (GSTIN from PARTYGSTIN / LEDGSTREGDETAILS);
- purchase order = "Purchase Order" voucher (not optional); its VOUCHERNUMBER is the PO number;
- goods receipt  = "Receipt Note" voucher whose inventory lines carry ORDERNO = the PO number;
- draft bill     = **Optional** "Purchase" voucher (ISOPTIONAL Yes: no effect on the books until a person
                   regularises it); lookup = party ledger + REFERENCE (Supplier Invoice No.);
- draft PO       = Optional "Purchase Order" voucher; lookup = `orrfin:<key>` in the narration.
Tally has no duplicate-reference setting, so the lookup is the only net (said on the Connectors page).

Tally has no "last modified" timestamp; its ALTERID rises on every change, so `modified` is derived from it.
Tally has no PO status field either: Orrfin derives open / to bill from receipts, and the demo marks a closed
PO with "Status: Closed" in its narration. In Educational mode Tally accepts only some dates (1st, 2nd, 31st;
unverified for TallyPrime), so demo vouchers are moved to the 1st (POs, bills) and 2nd (receipts).
"""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.adapters import tally_xml as tx
from app.erp_demo.canonical import IST, Dataset, dataset
from app.ports.erp import (
    Capabilities,
    CheckStep,
    ConnectionCheck,
    Created,
    DraftBill,
    DraftPo,
    ErpError,
    ErpPoLine,
    ErpPurchaseOrder,
    ErpReceipt,
    ErpReceiptLine,
    ErpRejected,
    ErpVendor,
    Label,
    SeedReport,
)
from app.security.outbound import ErpHttp

CREDITORS = "Sundry Creditors"
PURCHASE_LEDGER = "Purchase"
TAX_LEDGERS = {"cgst": "Input CGST", "sgst": "Input SGST", "igst": "Input IGST"}
ALTER_EPOCH = datetime(2026, 1, 1, tzinfo=IST)
ORRFIN_TAG = re.compile(r"orrfin:([0-9a-f]{64})")
VOUCHER_FETCH = ["DATE", "VOUCHERNUMBER", "VOUCHERTYPENAME", "PARTYLEDGERNAME", "REFERENCE", "NARRATION",
                 "ISOPTIONAL", "ALTERID", "ALLINVENTORYENTRIES", "LEDGERENTRIES"]
CENT = Decimal("0.01")


def tally_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def edu_date(value: date, day: int, educational: bool) -> date:
    return value.replace(day=day) if educational else value


def parse_date(text: str | None) -> date | None:
    text = (text or "").strip()
    for fmt in ("%Y%m%d", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _modified(obj: dict[str, Any]) -> datetime:
    return ALTER_EPOCH + timedelta(minutes=int(tx.number(obj.get("ALTERID"))))


def _unit(qty_text: str) -> str | None:
    parts = (qty_text or "").split()
    return parts[-1] if len(parts) > 1 else None


def _qty(line: dict[str, Any]) -> Decimal:
    return abs(tx.number(line.get("ACTUALQTY") or line.get("BILLEDQTY")))


# --- Canonical dataset → Tally objects (simulated fixtures and live seeding) --------------------------------

def render_masters(data: Dataset) -> list[tuple[str, dict[str, Any]]]:
    lines = {line.item_code: line for po in data.purchase_orders for line in po.lines}
    objects: list[tuple[str, dict[str, Any]]] = []
    for uom in sorted({line.uom for line in lines.values()}):
        objects.append(("UNIT", {"NAME": uom, "ISSIMPLEUNIT": "Yes"}))
    for code, line in lines.items():
        objects.append(("STOCKITEM", {"NAME": code, "PARENT": "Primary", "BASEUNITS": line.uom,
                                      "DESCRIPTION": line.item_name, "HSNCODE": line.hsn}))
    objects.append(("LEDGER", {"NAME": PURCHASE_LEDGER, "PARENT": "Purchase Accounts"}))
    for name in TAX_LEDGERS.values():
        objects.append(("LEDGER", {"NAME": name, "PARENT": "Duties & Taxes"}))
    for vendor in data.vendors:
        objects.append(("LEDGER", {"NAME": vendor.name, "PARENT": CREDITORS, "PARTYGSTIN": vendor.gstin,
                                   "GSTREGISTRATIONTYPE": "Regular"}))
    return objects


def _tax_ledgers(cgst: Decimal, sgst: Decimal, igst: Decimal) -> list[dict[str, str]]:
    rows = []
    for key, amount in (("cgst", cgst), ("sgst", sgst), ("igst", igst)):
        if amount:
            rows.append({"LEDGERNAME": TAX_LEDGERS[key], "ISDEEMEDPOSITIVE": "Yes", "AMOUNT": f"-{amount}"})
    return rows


def _inventory(code: str, uom: str, qty: Decimal, rate: Decimal, amount: Decimal, order_no: str | None,
               due: date | None = None, purchase_ledger: str | None = None) -> dict[str, Any]:
    line = {"STOCKITEMNAME": code, "RATE": f"{rate}/{uom}", "ACTUALQTY": f" {qty} {uom}",
            "BILLEDQTY": f" {qty} {uom}", "AMOUNT": f"-{amount}", "ISDEEMEDPOSITIVE": "Yes", "ORDERNO": order_no}
    if due:
        line["ORDERDUEDATE"] = tally_date(due)
    if purchase_ledger:
        line["PURCHASELEDGER"] = purchase_ledger
    return line


def render_vouchers(data: Dataset, educational: bool = False) -> list[tuple[str, dict[str, Any]]]:
    objects: list[tuple[str, dict[str, Any]]] = []
    for po in data.purchase_orders:
        objects.append(("VOUCHER", {
            "VOUCHERTYPENAME": "Purchase Order", "VOUCHERNUMBER": po.number,
            "DATE": tally_date(edu_date(po.po_date, 1, educational)), "PARTYLEDGERNAME": po.vendor.name,
            "NARRATION": "Status: Closed" if po.closed else "", "ISOPTIONAL": "No",
            "INVENTORY": [_inventory(l.item_code, l.uom, l.qty, l.rate, l.amount, po.number, po.schedule_date)
                          for l in po.lines],
            "LEDGERS": [{"LEDGERNAME": po.vendor.name, "ISDEEMEDPOSITIVE": "No", "AMOUNT": str(po.grand_total)},
                        *_tax_ledgers(po.cgst, po.sgst, po.igst)],
        }))
        for receipt in po.receipts:
            objects.append(("VOUCHER", {
                "VOUCHERTYPENAME": "Receipt Note", "VOUCHERNUMBER": receipt.number,
                "DATE": tally_date(edu_date(receipt.posting_date, 2, educational)),
                "PARTYLEDGERNAME": po.vendor.name, "NARRATION": "", "ISOPTIONAL": "No",
                "INVENTORY": [_inventory(po.lines[i].item_code, po.lines[i].uom, qty, po.lines[i].rate,
                                         (qty * po.lines[i].rate).quantize(CENT), po.number)
                              for i, qty in receipt.quantities.items()],
                "LEDGERS": [],
            }))
    return objects


# --- Tally objects → Orrfin records -------------------------------------------------------------------

def ledger_to_vendor(obj: dict[str, Any]) -> ErpVendor:
    gstin = (obj.get("PARTYGSTIN") or "").strip().upper() or None
    return ErpVendor(erp_ref=obj["NAME"], name=obj["NAME"], gstin=gstin, state_code=gstin[:2] if gstin else None,
                     modified=_modified(obj))


def _received(receipts: list[dict[str, Any]]) -> dict[tuple[str, str], Decimal]:
    got: dict[tuple[str, str], Decimal] = {}
    for vch in receipts:
        for line in vch.get("INVENTORY") or []:
            key = (line.get("ORDERNO") or "", line.get("STOCKITEMNAME") or "")
            got[key] = got.get(key, Decimal("0")) + _qty(line)
    return got


def voucher_to_po(vch: dict[str, Any], received: dict[tuple[str, str], Decimal]) -> ErpPurchaseOrder:
    number = vch["VOUCHERNUMBER"]
    inventory = vch.get("INVENTORY") or []
    net = sum((abs(tx.number(line.get("AMOUNT"))) for line in inventory), Decimal("0"))
    tax = sum((abs(tx.number(led.get("AMOUNT"))) for led in vch.get("LEDGERS") or []
               if led.get("LEDGERNAME") in TAX_LEDGERS.values()), Decimal("0"))
    rate = (tax * 100 / net).quantize(CENT) if net else Decimal("0")
    lines, all_received = [], True
    for i, line in enumerate(inventory, start=1):
        qty = _qty(line)
        if received.get((number, line.get("STOCKITEMNAME") or ""), Decimal("0")) < qty:
            all_received = False
        lines.append(ErpPoLine(erp_ref=f"{number}#{i}", line_no=i, item_code=line["STOCKITEMNAME"],
                               description=line["STOCKITEMNAME"], hsn=None, uom=_unit(line.get("ACTUALQTY") or ""),
                               qty=qty, rate=tx.number(line.get("RATE")), amount=abs(tx.number(line.get("AMOUNT"))),
                               tax_rate=rate))
    narration = vch.get("NARRATION") or ""
    status = "closed" if "Status: Closed" in narration else ("to_bill" if all_received and lines else "open")
    tag = ORRFIN_TAG.search(narration)
    return ErpPurchaseOrder(
        erp_ref=number, vendor_ref=vch.get("PARTYLEDGERNAME") or "", po_date=parse_date(vch.get("DATE")),
        schedule_date=parse_date(inventory[0].get("ORDERDUEDATE")) if inventory else None, status=status,
        currency="INR", net_total=net, tax_total=tax, grand_total=net + tax,
        orrfin_ref=tag.group(1) if tag else None, modified=_modified(vch), lines=lines, po_number=number)


def voucher_to_receipt(vch: dict[str, Any], po_lines: dict[tuple[str, str], str]) -> ErpReceipt:
    number = vch["VOUCHERNUMBER"]
    lines = []
    for i, line in enumerate(vch.get("INVENTORY") or [], start=1):
        order = line.get("ORDERNO") or None
        lines.append(ErpReceiptLine(erp_ref=f"{number}#{i}", item_code=line["STOCKITEMNAME"], qty_received=_qty(line),
                                    po_ref=order, po_line_ref=po_lines.get((order or "", line["STOCKITEMNAME"]))))
    return ErpReceipt(erp_ref=number, vendor_ref=vch.get("PARTYLEDGERNAME") or "",
                      posting_date=parse_date(vch.get("DATE")), status="received", modified=_modified(vch), lines=lines)


# --- The adapter -------------------------------------------------------------------------------------

class TallyAdapter:
    def __init__(self, http: ErpHttp, *, company: str, label: Label, educational: bool = True):
        self.http = http
        self.company = company
        self.label = label
        self.educational = educational

    def _post(self, body: bytes) -> bytes:
        return self.http.request("POST", "/", content=body, headers={"Content-Type": "text/xml"}).content

    def _export(self, kind: str, fetch: list[str]) -> list[dict[str, Any]]:
        reply = self._post(tx.export_request(self.company, kind.capitalize(), fetch))
        try:
            return tx.parse_export(reply, kind)
        except Exception:  # malformed XML from Tally: a refusal, not a silent empty list
            raise ErpRejected("Tally sent a reply Orrfin could not read.") from None

    def _import(self, report: str, objects: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        raw = self._post(tx.import_envelope(self.company, report, objects))
        try:
            reply = tx.parse_import_reply(raw)
        except Exception:
            raise ErpRejected("Tally sent a reply Orrfin could not read.") from None
        if reply["errors"] or not reply["created"]:
            detail = "; ".join(m for m in reply["messages"] if m) or "Tally created nothing"
            raise ErpRejected(f"Tally refused it: {self.http.clean(detail)}")
        return reply

    def _vouchers(self) -> list[dict[str, Any]]:
        return self._export("VOUCHER", VOUCHER_FETCH)

    # --- port --------------------------------------------------------------------------------------
    def capabilities(self) -> Capabilities:
        return Capabilities(label=self.label,
                            draft_bill_means="Optional Purchase voucher (no effect on the books until regularised)",
                            draft_po_means="Optional Purchase Order voucher")

    def test_connection(self) -> ConnectionCheck:
        try:
            companies = [c.get("NAME", "") for c in self._export("COMPANY", ["NAME"])]
        except ErpError as exc:
            return ConnectionCheck(ok=False, steps=[CheckStep(
                name="Reach TallyPrime", ok=False,
                detail=f"{exc} Is TallyPrime open, with F1 → Settings → Connectivity → "
                       "'TallyPrime acts as' = Both and port 9000?")])
        steps = [CheckStep(name="Reach TallyPrime", ok=True, detail="TallyPrime answered on the configured port.")]
        loaded = any(c.strip().lower() == self.company.strip().lower() for c in companies)
        steps.append(CheckStep(name="Company loaded", ok=loaded,
                               detail=f"'{self.company}' is open." if loaded else
                               f"'{self.company}' is not open in TallyPrime (open: {', '.join(companies) or 'none'})."))
        if not loaded:
            return ConnectionCheck(ok=False, steps=steps)
        creditors = [v for v in self._export("LEDGER", ["NAME", "PARENT"]) if v.get("PARENT") == CREDITORS]
        steps.append(CheckStep(name="Read vendors", ok=True, detail=f"{len(creditors)} Sundry Creditors ledgers."))
        steps.append(CheckStep(name="Duplicate safety", ok=True,
                               detail="Tally has no duplicate-invoice setting; Orrfin always looks a voucher up first."))
        return ConnectionCheck(ok=True, steps=steps)

    def list_vendors(self) -> list[ErpVendor]:
        ledgers = self._export("LEDGER", ["NAME", "PARENT", "PARTYGSTIN", "ALTERID", "LEDGSTREGDETAILS"])
        return [ledger_to_vendor(obj) for obj in ledgers if obj.get("PARENT") == CREDITORS]

    def _po_and_receipt_vouchers(self) -> tuple[list[dict], list[dict]]:
        vouchers = [v for v in self._vouchers() if (v.get("ISOPTIONAL") or "No") != "Yes"]
        return ([v for v in vouchers if v.get("VOUCHERTYPENAME") == "Purchase Order"],
                [v for v in vouchers if v.get("VOUCHERTYPENAME") == "Receipt Note"])

    def list_purchase_orders(self) -> list[ErpPurchaseOrder]:
        pos, receipts = self._po_and_receipt_vouchers()
        received = _received(receipts)
        return [voucher_to_po(v, received) for v in pos]

    def list_receipts(self) -> list[ErpReceipt]:
        pos, receipts = self._po_and_receipt_vouchers()
        po_lines = {(po["VOUCHERNUMBER"], line["STOCKITEMNAME"]): f"{po['VOUCHERNUMBER']}#{i}"
                    for po in pos for i, line in enumerate(po.get("INVENTORY") or [], start=1)}
        return [voucher_to_receipt(v, po_lines) for v in receipts]

    def create_draft_bill(self, bill: DraftBill) -> Created:
        number = f"ORF-{bill.idempotency_key[:10].upper()}"
        voucher = {
            "VOUCHERTYPENAME": "Purchase", "VOUCHERNUMBER": number,
            "DATE": tally_date(edu_date(bill.invoice_date, 1, self.educational)),
            "REFERENCE": bill.supplier_invoice_no, "REFERENCEDATE": tally_date(bill.invoice_date),
            "PARTYLEDGERNAME": bill.vendor_ref, "ISOPTIONAL": "Yes", "ISINVOICE": "Yes",
            "NARRATION": f"orrfin:{bill.idempotency_key} | Draft from Orrfin. Invoice dated {bill.invoice_date}.",
            "INVENTORY": [_inventory(line.item_code, line.uom or "Nos", line.qty, line.rate, line.amount, bill.po_ref,
                                     purchase_ledger=PURCHASE_LEDGER) for line in bill.lines],
            "LEDGERS": [{"LEDGERNAME": bill.vendor_ref, "ISDEEMEDPOSITIVE": "No", "AMOUNT": str(bill.grand_total)},
                        *_tax_ledgers(bill.cgst, bill.sgst, bill.igst)],
        }
        self._import("Vouchers", [("VOUCHER", voucher)])
        return Created(erp_doc_name=number)

    def find_bill(self, vendor_ref: str, supplier_invoice_no: str) -> str | None:
        for v in self._vouchers():
            if (v.get("VOUCHERTYPENAME") == "Purchase" and v.get("PARTYLEDGERNAME") == vendor_ref
                    and (v.get("REFERENCE") or "").strip() == supplier_invoice_no.strip()):
                return v["VOUCHERNUMBER"]
        return None

    def create_draft_po(self, po: DraftPo) -> Created:
        number = f"ORF-PO-{po.idempotency_key[:10].upper()}"
        net = sum((line.amount for line in po.lines), Decimal("0"))
        voucher = {
            "VOUCHERTYPENAME": "Purchase Order", "VOUCHERNUMBER": number,
            "DATE": tally_date(edu_date(po.po_date, 1, self.educational)), "PARTYLEDGERNAME": po.vendor_ref,
            "ISOPTIONAL": "Yes",
            "NARRATION": f"orrfin:{po.idempotency_key} | Draft PO from Orrfin for {po.request_number}.",
            "INVENTORY": [_inventory(line.item_code, line.uom or "Nos", line.qty, line.rate, line.amount, number,
                                     po.schedule_date) for line in po.lines],
            "LEDGERS": [{"LEDGERNAME": po.vendor_ref, "ISDEEMEDPOSITIVE": "No", "AMOUNT": str(net)}],
        }
        self._import("Vouchers", [("VOUCHER", voucher)])
        return Created(erp_doc_name=number)

    def find_po(self, orrfin_key: str) -> str | None:
        for v in self._vouchers():
            if v.get("VOUCHERTYPENAME") == "Purchase Order" and f"orrfin:{orrfin_key}" in (v.get("NARRATION") or ""):
                return v["VOUCHERNUMBER"]
        return None

    def seed_demo_data(self, data: Dataset | None = None) -> SeedReport:
        data = data or dataset()
        created: dict[str, int] = {}
        existing: dict[str, int] = {}
        labels = {"LEDGER": "ledgers", "STOCKITEM": "stock items", "UNIT": "units"}
        have = {kind: {o.get("NAME") for o in self._export(kind, ["NAME"])} for kind in labels}
        missing = []
        for kind, obj in render_masters(data):
            bucket = existing if obj["NAME"] in have[kind] else created
            bucket[labels[kind]] = bucket.get(labels[kind], 0) + 1
            if obj["NAME"] not in have[kind]:
                missing.append((kind, obj))
        # Units first, then the items and ledgers that point at them.
        for group in (("UNIT",), ("STOCKITEM", "LEDGER")):
            batch = [m for m in missing if m[0] in group]
            if batch:
                self._import("All Masters", batch)
        numbers = {(v.get("VOUCHERTYPENAME"), v.get("VOUCHERNUMBER")) for v in self._vouchers()}
        for kind, vch in render_vouchers(data, self.educational):
            label = "purchase orders" if vch["VOUCHERTYPENAME"] == "Purchase Order" else "receipt notes"
            if (vch["VOUCHERTYPENAME"], vch["VOUCHERNUMBER"]) in numbers:
                existing[label] = existing.get(label, 0) + 1
                continue
            self._import("Vouchers", [(kind, vch)])
            created[label] = created.get(label, 0) + 1
        notes = ["Educational mode: demo vouchers are dated the 1st (orders) and 2nd (receipts) of their month."] \
            if self.educational else []
        return SeedReport(created=created, existing=existing, notes=notes)
