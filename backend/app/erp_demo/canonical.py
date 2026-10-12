"""The one canonical demo dataset every ERP connector is fed from (BUILD_PLAN §4 connector rules; ADR 0004).

5 vendors, 8 purchase orders and 8 goods receipts, in Orrfin's own words. Each adapter has a
renderer that writes these into its ERP's native shape (fixtures for simulated connectors) and
a seeder that creates them in a live ERP ("Prepare demo data"). Because all ERPs carry the
same PO numbers, vendor GSTINs and item codes, the 12 evaluation invoices (evals/extraction)
match the same way whichever ERP is active.

The buyer org sits in Maharashtra (state 27): same-state suppliers charge CGST 9% + SGST 9%,
others IGST 18%. All companies and GSTINs are fictional; GSTINs carry a valid check character.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
COMPANY = "Orrfin Demo Co"
BUYER_STATE = "27"
GST_RATE = Decimal("18")
CENT = Decimal("0.01")
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_with_check(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return first14 + GSTIN_CHARS[(36 - total % 36) % 36]


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Vendor:
    key: str  # stable short id used by ERPs that want a code (Tally ledger alias, BC vendor no.)
    name: str
    group: str
    gstin: str
    modified: datetime

    @property
    def state_code(self) -> str:
        return self.gstin[:2]

    @property
    def same_state(self) -> bool:
        return self.state_code == BUYER_STATE


@dataclass(frozen=True)
class Line:
    item_code: str
    item_name: str
    hsn: str
    uom: str
    qty: Decimal
    rate: Decimal
    tax_rate: Decimal = GST_RATE

    @property
    def amount(self) -> Decimal:
        return money(self.qty * self.rate)


@dataclass(frozen=True)
class Receipt:
    number: str
    po_number: str
    posting_date: date
    quantities: dict[int, Decimal]  # PO line index → accepted quantity

    @property
    def modified(self) -> datetime:
        return datetime(self.posting_date.year, self.posting_date.month, self.posting_date.day, 18, 5, tzinfo=IST)


@dataclass(frozen=True)
class PurchaseOrder:
    number: str
    vendor: Vendor
    po_date: date
    schedule_date: date
    lines: tuple[Line, ...]
    closed: bool
    receipts: tuple[Receipt, ...] = field(default=())

    @property
    def modified(self) -> datetime:
        return datetime(self.po_date.year, self.po_date.month, self.po_date.day, 16, 30, tzinfo=IST)

    @property
    def net_total(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0"))

    @property
    def cgst(self) -> Decimal:
        return money(self.net_total * GST_RATE / 2 / 100) if self.vendor.same_state else Decimal("0.00")

    @property
    def sgst(self) -> Decimal:
        return self.cgst

    @property
    def igst(self) -> Decimal:
        return Decimal("0.00") if self.vendor.same_state else money(self.net_total * GST_RATE / 100)

    @property
    def tax_total(self) -> Decimal:
        return self.cgst + self.sgst + self.igst

    @property
    def grand_total(self) -> Decimal:
        return self.net_total + self.tax_total

    def received(self, index: int) -> Decimal:
        return sum((r.quantities.get(index, Decimal("0")) for r in self.receipts), Decimal("0"))

    @property
    def per_received(self) -> Decimal:
        ordered = sum((line.qty for line in self.lines), Decimal("0"))
        got = sum((self.received(i) for i in range(len(self.lines))), Decimal("0"))
        return round(Decimal(100) * got / ordered, 2)

    @property
    def status(self) -> str:
        """Orrfin's PO status vocabulary (ports/erp.py)."""
        if self.closed:
            return "closed"
        return "to_bill" if self.per_received >= 100 else "open"


@dataclass(frozen=True)
class Dataset:
    vendors: tuple[Vendor, ...]
    purchase_orders: tuple[PurchaseOrder, ...]

    @property
    def receipts(self) -> list[Receipt]:
        return [r for po in self.purchase_orders for r in po.receipts]

    def vendor(self, key: str) -> Vendor:
        return next(v for v in self.vendors if v.key == key)


_VENDORS = [
    # (key, name, group, gstin first 14, modified)
    ("V001", "Shreeji Office Supplies Pvt Ltd", "Stationery", "27AABCS4821K1Z", "2026-09-18 10:12:04"),
    ("V002", "Kaveri IT Solutions LLP", "Hardware", "29AAKFK3310P1Z", "2026-09-18 10:15:41"),
    ("V003", "Northwind Networks India Pvt Ltd", "Hardware", "07AADCN5566Q1Z", "2026-09-18 10:19:02"),
    ("V004", "Deccan Facility Services Pvt Ltd", "Services", "27AAECD9082R1Z", "2026-09-18 10:22:37"),
    ("V005", "Sahyadri Print & Stationery", "Stationery", "27ABNPS1204H1Z", "2026-09-18 10:25:55"),
]

# (po number, vendor index, date, schedule date, lines: (item_code, item_name, hsn, uom, qty, rate),
#  receipts: [(receipt number, posting date, {line index: qty received})], closed?)
_PURCHASE_ORDERS = [
    (1, 0, "2026-09-01", "2026-09-08",
     [("STAT-A4-75", "A4 copier paper 75 GSM (500 sheets)", "4802", "Ream", 100, "285.00"),
      ("STAT-PEN-BLU50", "Ball pens, blue (box of 50)", "9608", "Box", 40, "450.00")],
     [(1, "2026-09-07", {0: 100, 1: 40})], False),
    (2, 1, "2026-09-02", "2026-09-15",
     [("IT-LAP-14-I5", "Laptop 14in, Core i5, 16 GB RAM, 512 GB SSD", "8471", "Nos", 5, "78500.00"),
      ("IT-DOCK-USBC", "USB-C docking station", "8473", "Nos", 5, "9800.00")],
     [(2, "2026-09-12", {0: 3, 1: 5})], False),
    (3, 2, "2026-09-05", "2026-09-30",
     [("NET-AP-WIFI6", "Wi-Fi 6 access point", "8517", "Nos", 10, "14200.00"),
      ("NET-SW-24POE", "24-port PoE switch", "8517", "Nos", 2, "38500.00")],
     [], False),
    (4, 3, "2026-09-01", "2026-09-30",
     [("SVC-HOUSEKEEP", "Housekeeping services, September 2026", "9985", "Month", 1, "125000.00")],
     [(3, "2026-09-30", {0: 1})], False),
    (5, 4, "2026-09-03", "2026-09-17",
     [("PRN-VCARD", "Visiting cards, 100 per box", "4911", "Box", 20, "650.00"),
      ("PRN-LETTERHEAD", "Letterheads, 500 sheets", "4911", "Ream", 10, "1450.00")],
     [(4, "2026-09-09", {0: 10}), (5, "2026-09-16", {0: 10, 1: 10})], False),
    (6, 1, "2026-09-08", "2026-09-22",
     [("IT-MON-27", "27in IPS monitor", "8528", "Nos", 8, "16900.00")],
     [(6, "2026-09-20", {0: 6})], False),
    (7, 0, "2026-08-20", "2026-08-31",
     [("STAT-BOXFILE", "Box files, laminated", "4820", "Nos", 200, "95.50")],
     [(7, "2026-08-30", {0: 150})], True),
    (8, 2, "2026-09-10", "2026-09-19",
     [("NET-FW-APPL", "Next-generation firewall appliance", "8517", "Nos", 1, "215000.00"),
      ("NET-FW-AMC", "Firewall support and updates, 12 months", "9987", "Nos", 1, "36000.00")],
     [(8, "2026-09-18", {0: 1, 1: 1})], False),
]


def po_number(n: int) -> str:
    return f"PUR-ORD-2026-{n:05d}"


def receipt_number(n: int) -> str:
    return f"MAT-PRE-2026-{n:05d}"


@cache
def dataset() -> Dataset:
    vendors = tuple(
        Vendor(key=key, name=name, group=group, gstin=gstin_with_check(first14),
               modified=datetime.fromisoformat(modified).replace(tzinfo=IST))
        for key, name, group, first14, modified in _VENDORS)
    orders = []
    for n, vendor_index, po_date, schedule, lines, receipts, closed in _PURCHASE_ORDERS:
        number = po_number(n)
        orders.append(PurchaseOrder(
            number=number, vendor=vendors[vendor_index], po_date=date.fromisoformat(po_date),
            schedule_date=date.fromisoformat(schedule), closed=closed,
            lines=tuple(Line(code, name, hsn, uom, Decimal(qty), Decimal(rate))
                        for code, name, hsn, uom, qty, rate in lines),
            receipts=tuple(Receipt(receipt_number(rn), number, date.fromisoformat(posted),
                                   {i: Decimal(q) for i, q in qtys.items()})
                           for rn, posted, qtys in receipts),
        ))
    return Dataset(vendors=vendors, purchase_orders=tuple(orders))
