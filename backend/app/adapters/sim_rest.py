"""Shared plumbing for simulated JSON/OData ERP servers (BUILD_PLAN §4 connector rules; ADR 0006).

Business Central, Dynamics F&O, SAP, Oracle, NetSuite, Zoho Books and Odoo are all JSON over HTTP. Each
simulated server (`<erp>_sim.py`) routes its own URLs and applies its own validation; this module gives
them the common parts:
- `Collections`: base documents (rendered from the canonical dataset) plus Orrfin's writes, persisted in a
  SimStore so lookups survive restarts;
- `odata_filter`: the small OData $filter subset the adapters send (`a eq 'x'`, `and`, `ne`, `startswith`);
- `json_reply` / `json_error`: responses with Decimal written as JSON numbers, like the real APIs.
"""

import json
import re
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.sim_store import SimStore

Doc = dict[str, Any]


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value).__name__)


def json_reply(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body, default=_default).encode(),
                          headers={"Content-Type": "application/json", **(headers or {})})


def json_error(status: int, code: str, message: str) -> httpx.Response:
    return json_reply(status, {"error": {"code": code, "message": message}})


def load(request: httpx.Request) -> Any:
    return json.loads(request.content or b"{}", parse_float=Decimal)


class Collections:
    """Base docs + persisted overlay, by collection name and id field."""

    def __init__(self, store: SimStore, base: Callable[[], dict[str, list[Doc]]], id_field: str = "id"):
        self.store = store
        self.base = base
        self.id_field = id_field

    def _merged(self, state: dict[str, Any]) -> dict[str, dict[str, Doc]]:
        merged = {name: {str(d[self.id_field]): d for d in docs} for name, docs in self.base().items()}
        for name, overlay in state.get("collections", {}).items():
            merged.setdefault(name, {}).update(overlay)
        return merged

    def all(self, name: str) -> list[Doc]:
        return list(self._merged(self.store.load()).get(name, {}).values())

    def get(self, name: str, doc_id: str) -> Doc | None:
        return self._merged(self.store.load()).get(name, {}).get(str(doc_id))

    def put(self, name: str, doc: Doc) -> Doc:
        state = self.store.load()
        doc.setdefault(self.id_field, str(uuid.uuid4()))
        state.setdefault("collections", {}).setdefault(name, {})[str(doc[self.id_field])] = doc
        self.store.save(state)
        return doc

    def next_number(self, series: str, start: int = 1) -> int:
        state = self.store.load()
        counters = state.setdefault("counters", {})
        counters[series] = counters.get(series, start - 1) + 1
        self.store.save(state)
        return counters[series]


_CLAUSE = re.compile(r"^\s*(?:(\w+)\s+(eq|ne)\s+(?:'((?:[^']|'')*)'|(-?\d+(?:\.\d+)?)|(true|false))"
                     r"|startswith\(\s*(\w+)\s*,\s*'((?:[^']|'')*)'\s*\))\s*$")


def odata_filter(expr: str | None) -> Callable[[Doc], bool]:
    """`a eq 'x' and b ne 5 and startswith(c,'ORF-')` → predicate. Anything else is refused (400)."""
    if not expr:
        return lambda doc: True
    tests = []
    for clause in re.split(r"\s+and\s+", expr.strip()):
        m = _CLAUSE.match(clause)
        if not m:
            raise ValueError(f"Unsupported filter clause: {clause}")
        field, op, text, num, boolean, sw_field, sw_text = m.groups()
        if sw_field:
            prefix = sw_text.replace("''", "'")
            tests.append(lambda d, f=sw_field, p=prefix: str(d.get(f) or "").startswith(p))
            continue
        value: Any = text.replace("''", "'") if text is not None else (
            Decimal(num) if num is not None else boolean == "true")
        if op == "eq":
            tests.append(lambda d, f=field, v=value: _same(d.get(f), v))
        else:
            tests.append(lambda d, f=field, v=value: not _same(d.get(f), v))
    return lambda doc: all(t(doc) for t in tests)


def _same(have: Any, want: Any) -> bool:
    if isinstance(want, bool):
        return bool(have) == want
    if isinstance(want, Decimal):
        try:
            return Decimal(str(have)) == want
        except Exception:
            return False
    return str(have if have is not None else "") == want


def odata_quote(value: str) -> str:
    """A string literal for an OData $filter (single quotes doubled), so a vendor name can't break the query."""
    return "'" + str(value).replace("'", "''") + "'"
