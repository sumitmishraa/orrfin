"""Write the simulated ERPNext fixtures to seed/erpnext/ (PROMPTS Steps 4 and 12, BUILD_PLAN §4).

The data comes from the canonical dataset (app/erp_demo/canonical.py) through the ERPNext renderer
(app/adapters/erpnext_fixtures.py), the same source every other connector renders from. Each file is
shaped like ERPNext's REST reply ({"data": [...]}). A contract test fails if these files drift from
the renderer, so rerun this after changing the canonical dataset.

Run from the repo root:  backend\\.venv\\Scripts\\python backend\\scripts\\make_erpnext_fixtures.py
"""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.adapters.erpnext_fixtures import render  # noqa: E402

OUT_DIR = BACKEND.parent / "seed" / "erpnext"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = render()
    for filename, docs in files.items():
        (OUT_DIR / filename).write_text(json.dumps({"data": docs}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {', '.join(f'{len(d)} {n}' for n, d in files.items())} to {OUT_DIR}")


if __name__ == "__main__":
    main()
