"""TallyPrime XML: the envelopes Orrfin sends and the replies it reads (BUILD_PLAN §4; PROMPTS Step 16).

Tally speaks XML over HTTP (POST to http://localhost:9000). Two request kinds are used:
- **Import Data** (create masters and vouchers): ENVELOPE/HEADER/TALLYREQUEST = "Import Data", then
  BODY/IMPORTDATA/REQUESTDESC/REPORTNAME (= "All Masters" or "Vouchers") and REQUESTDATA/TALLYMESSAGE.
  The reply carries CREATED / ALTERED / ERRORS counts, LASTVCHID and LINEERROR text.
- **Export of a collection** (read): a TDL collection of a TYPE (Ledger, Voucher, Company) with a FETCH list.
  Orrfin filters the rows itself, so it never depends on TDL filter syntax.

Objects are plain dicts in Tally's own tag names (the adapter and the simulated server share them):
  ledger  {NAME, PARENT, PARTYGSTIN, ALTERID}
  voucher {VOUCHERTYPENAME, VOUCHERNUMBER, DATE (YYYYMMDD), PARTYLEDGERNAME, REFERENCE, NARRATION, ISOPTIONAL,
           ALTERID, INVENTORY: [{STOCKITEMNAME, RATE "285.00/Ream", ACTUALQTY " 100 Ream", AMOUNT, ORDERNO,
           ORDERDUEDATE}], LEDGERS: [{LEDGERNAME, AMOUNT}]}
Amounts are Tally-signed strings: a debit is negative ("-28500.00"), a credit positive. Parsed with defusedxml
(blocks entity-expansion attacks), never with regex; regex only reads the "285.00/Ream" value strings.
"""

import re
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml import ElementTree as SafeET

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
OBJECT_TAGS = {"LEDGER", "VOUCHER", "STOCKITEM", "UNIT", "GROUP", "COMPANY"}


def number(text: str | None) -> Decimal:
    """'285.00/Ream' → 285.00, ' 100 Ream' → 100, '-28500.00' → -28500.00."""
    match = _NUMBER.search((text or "").replace(",", ""))
    return Decimal(match.group(0)) if match else Decimal("0")


def _text(parent: Element, tag: str, value: Any) -> None:
    if value is not None:
        SubElement(parent, tag).text = str(value)


def _object_xml(kind: str, obj: dict[str, Any]) -> Element:
    attrs = {"ACTION": "Create"}
    if kind in ("LEDGER", "STOCKITEM", "UNIT", "GROUP"):
        attrs["NAME"] = obj["NAME"]
    if kind == "VOUCHER":
        attrs["VCHTYPE"] = obj["VOUCHERTYPENAME"]
    el = Element(kind, attrs)
    for key, value in obj.items():
        if key in ("INVENTORY", "LEDGERS", "ALTERID"):
            continue
        _text(el, key, value)
    for line in obj.get("INVENTORY") or []:
        inv = SubElement(el, "ALLINVENTORYENTRIES.LIST")
        for key in ("STOCKITEMNAME", "RATE", "ACTUALQTY", "BILLEDQTY", "AMOUNT", "ISDEEMEDPOSITIVE"):
            _text(inv, key, line.get(key))
        if line.get("ORDERNO") or line.get("ORDERDUEDATE"):
            batch = SubElement(inv, "BATCHALLOCATIONS.LIST")
            _text(batch, "ORDERNO", line.get("ORDERNO"))
            _text(batch, "ORDERDUEDATE", line.get("ORDERDUEDATE"))
            _text(batch, "AMOUNT", line.get("AMOUNT"))
            _text(batch, "ACTUALQTY", line.get("ACTUALQTY"))
        if line.get("PURCHASELEDGER"):
            # Item-invoice purchases book each line to a purchase ledger (Tally's accounting allocation).
            alloc = SubElement(inv, "ACCOUNTINGALLOCATIONS.LIST")
            _text(alloc, "LEDGERNAME", line["PURCHASELEDGER"])
            _text(alloc, "ISDEEMEDPOSITIVE", "Yes")
            _text(alloc, "AMOUNT", line.get("AMOUNT"))
    for led in obj.get("LEDGERS") or []:
        entry = SubElement(el, "LEDGERENTRIES.LIST")
        for key in ("LEDGERNAME", "ISDEEMEDPOSITIVE", "AMOUNT"):
            _text(entry, key, led.get(key))
    return el


def import_envelope(company: str, report: str, objects: list[tuple[str, dict[str, Any]]]) -> bytes:
    """report: "All Masters" (ledgers, items, units) or "Vouchers". objects: [(TAG, dict), ...]."""
    env = Element("ENVELOPE")
    SubElement(SubElement(env, "HEADER"), "TALLYREQUEST").text = "Import Data"
    importdata = SubElement(SubElement(env, "BODY"), "IMPORTDATA")
    desc = SubElement(importdata, "REQUESTDESC")
    SubElement(desc, "REPORTNAME").text = report
    SubElement(SubElement(desc, "STATICVARIABLES"), "SVCURRENTCOMPANY").text = company
    message = SubElement(SubElement(importdata, "REQUESTDATA"), "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
    for kind, obj in objects:
        message.append(_object_xml(kind, obj))
    return tostring(env, encoding="utf-8")


def export_request(company: str, collection_type: str, fetch: list[str]) -> bytes:
    env = Element("ENVELOPE")
    header = SubElement(env, "HEADER")
    _text(header, "VERSION", 1)
    _text(header, "TALLYREQUEST", "Export")
    _text(header, "TYPE", "Collection")
    _text(header, "ID", f"Orrfin{collection_type}s")
    desc = SubElement(SubElement(env, "BODY"), "DESC")
    static = SubElement(desc, "STATICVARIABLES")
    _text(static, "SVEXPORTFORMAT", "$$SysName:XML")
    if company:
        _text(static, "SVCURRENTCOMPANY", company)
    _text(static, "SVFROMDATE", "20000101")
    _text(static, "SVTODATE", "20991231")
    tdl = SubElement(SubElement(desc, "TDL"), "TDLMESSAGE")
    coll = SubElement(tdl, "COLLECTION", {"NAME": f"Orrfin{collection_type}s", "ISMODIFY": "No"})
    _text(coll, "TYPE", collection_type)
    _text(coll, "FETCH", ",".join(fetch))
    return tostring(env, encoding="utf-8")


def _object_from(el: Element) -> dict[str, Any]:
    obj: dict[str, Any] = {k: v for k, v in el.attrib.items() if k in ("NAME", "VCHTYPE")}
    if "VCHTYPE" in obj:
        obj["VOUCHERTYPENAME"] = obj.pop("VCHTYPE")
    inventory, ledgers = [], []
    for child in el:
        tag = child.tag
        if tag in ("ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST"):
            line = {c.tag: (c.text or "").strip() for c in child if not c.tag.endswith(".LIST")}
            batch = child.find("BATCHALLOCATIONS.LIST")
            if batch is not None:
                for key in ("ORDERNO", "ORDERDUEDATE"):
                    if batch.findtext(key):
                        line[key] = batch.findtext(key).strip()
            alloc = child.find("ACCOUNTINGALLOCATIONS.LIST")
            if alloc is not None and alloc.findtext("LEDGERNAME"):
                line["PURCHASELEDGER"] = alloc.findtext("LEDGERNAME").strip()
            inventory.append(line)
        elif tag in ("LEDGERENTRIES.LIST", "ALLLEDGERENTRIES.LIST"):
            ledgers.append({c.tag: (c.text or "").strip() for c in child if not c.tag.endswith(".LIST")})
        elif tag == "LEDGSTREGDETAILS.LIST":
            if child.findtext("GSTIN"):
                obj.setdefault("PARTYGSTIN", child.findtext("GSTIN").strip())
        elif not tag.endswith(".LIST"):
            obj[tag] = (child.text or "").strip()
    if el.tag == "VOUCHER":
        obj["INVENTORY"], obj["LEDGERS"] = inventory, ledgers
    return obj


def parse_import(body: bytes) -> tuple[str, str, list[tuple[str, dict[str, Any]]]]:
    """(company, report, [(TAG, object)]) from an Import Data envelope (used by the simulated Tally)."""
    root = SafeET.fromstring(body)
    company = root.findtext(".//REQUESTDESC/STATICVARIABLES/SVCURRENTCOMPANY") or ""
    report = root.findtext(".//REQUESTDESC/REPORTNAME") or ""
    message = root.find(".//REQUESTDATA/TALLYMESSAGE")
    objects = [(el.tag, _object_from(el)) for el in (message if message is not None else []) if el.tag in OBJECT_TAGS]
    return company, report, objects


def parse_export_request(body: bytes) -> tuple[str, str]:
    """(company, collection TYPE) from an export request (used by the simulated Tally)."""
    root = SafeET.fromstring(body)
    return (root.findtext(".//STATICVARIABLES/SVCURRENTCOMPANY") or "",
            root.findtext(".//TDLMESSAGE/COLLECTION/TYPE") or "")


def export_reply(kind: str, objects: list[dict[str, Any]]) -> bytes:
    """A collection export reply: ENVELOPE/BODY/DATA/COLLECTION/<KIND>... (used by the simulated Tally)."""
    env = Element("ENVELOPE")
    SubElement(SubElement(env, "HEADER"), "VERSION").text = "1"
    coll = SubElement(SubElement(SubElement(env, "BODY"), "DATA"), "COLLECTION")
    for obj in objects:
        el = _object_xml(kind, obj)
        el.attrib.pop("ACTION", None)
        _text(el, "ALTERID", obj.get("ALTERID"))
        coll.append(el)
    return tostring(env, encoding="utf-8")


def parse_export(body: bytes, kind: str) -> list[dict[str, Any]]:
    root = SafeET.fromstring(body)
    return [_object_from(el) for el in root.iter(kind)]


def import_reply(created: int, errors: list[str], last_id: int | None = None) -> bytes:
    env = Element("RESPONSE")
    _text(env, "CREATED", created)
    _text(env, "ALTERED", 0)
    _text(env, "ERRORS", len(errors))
    _text(env, "LASTVCHID", last_id or 0)
    for error in errors:
        _text(env, "LINEERROR", error)
    return tostring(env, encoding="utf-8")


def parse_import_reply(body: bytes) -> dict[str, Any]:
    """CREATED / ERRORS / LINEERROR / LASTVCHID, wherever Tally puts them (RESPONSE or IMPORTRESULT)."""
    root = SafeET.fromstring(body)

    def first(tag: str) -> str:
        found = root if root.tag == tag else next(root.iter(tag), None)
        return (found.text or "").strip() if found is not None else ""

    return {"created": int(number(first("CREATED"))), "errors": int(number(first("ERRORS"))),
            "last_id": first("LASTVCHID"), "messages": [(e.text or "").strip() for e in root.iter("LINEERROR")]}
