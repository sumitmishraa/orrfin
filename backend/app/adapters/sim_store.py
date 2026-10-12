"""Persistent state for simulated ERP servers (BUILD_PLAN §4 connector rules; ADR 0004).

A simulated connector answers like the real ERP's API from fixtures rendered from the
canonical dataset. Documents Orrfin *creates* there (draft bills, draft POs, seeded records)
must survive a worker restart, or the outbox's lookup-before-retry would be meaningless.
So writes are kept in one JSON file per connection under FILE_STORE_DIR/erp-sim/.

Only synthetic demo data ever lands here. The file is rewritten atomically (temp file +
os.replace), so a crash mid-write leaves the previous state.
"""

import json
import os
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Not JSON serialisable: {type(value).__name__}")


class SimStore:
    """`path=None` keeps the state in memory only (unit tests, contract tests)."""

    def __init__(self, path: Path | None):
        self.path = path
        self._memory: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        with _LOCK:
            if self.path is None:
                return json.loads(json.dumps(self._memory)) if self._memory else {"collections": {}, "counters": {}}
            if not self.path.exists():
                return {"collections": {}, "counters": {}}
            return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        with _LOCK:
            if self.path is None:
                self._memory = json.loads(json.dumps(state, default=_default))
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, default=_default, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    def reset(self) -> None:
        with _LOCK:
            self._memory = None
            if self.path is not None:
                self.path.unlink(missing_ok=True)


def next_number(state: dict[str, Any], series: str) -> int:
    counters = state.setdefault("counters", {})
    counters[series] = counters.get(series, 0) + 1
    return counters[series]


def created(state: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    return state.setdefault("collections", {}).setdefault(collection, [])
