"""Run the Orrfin Assistant evaluation against a real model (PROMPTS Step 24; ADR 0007).

Builds the synthetic scenario in a new org of the local database ("Assistant Eval <time>"), asks
every question in evals/assistant/cases.json `--runs` times, grades the answers by code and writes
a markdown report. Synthetic data only; it calls the configured AI provider, so it costs money.

    backend\\.venv\\Scripts\\python backend\\scripts\\run_assistant_eval.py --provider gemini --runs 3
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="gemini", choices=["gemini", "anthropic", "bedrock", "fake"])
    parser.add_argument("--runs", type=int, default=1, help="Ask each question this many times (pass@k).")
    parser.add_argument("--pause", type=float, default=0, help="Seconds between questions (free-tier quotas).")
    parser.add_argument("--out", default=None, help="Report path (default evals/assistant/report-<provider>.md)")
    args = parser.parse_args()
    os.environ["AI_PROVIDER"] = args.provider

    from app import job_handlers  # noqa: F401  (registers the extract and match jobs)
    from app.config import REPO_ROOT, get_settings
    from app.db import SessionLocal
    from app.evals.assistant_eval import build_scenario, fake_factory, report, run_cases
    from app.modules.invoices.providers import get_assistant

    get_settings.cache_clear()
    out = Path(args.out) if args.out else REPO_ROOT / "evals" / "assistant" / f"report-{args.provider}.md"
    with SessionLocal() as db:
        scenario = build_scenario(db, f"Assistant Eval {datetime.now():%Y-%m-%d %H%M}")
        if args.provider == "fake":
            factory, model = fake_factory, "fake (scripted)"
        else:
            assistant = get_assistant()
            factory, model = (lambda case: assistant), assistant.model_id
        results = run_cases(db, scenario, factory, runs=args.runs, pause=args.pause)
    out.write_text(report(results, model, args.runs), encoding="utf-8")
    passed = sum(r.passed[0] for r in results)
    print(f"{model}: pass@1 {passed}/{len(results)}. Report: {out}")


if __name__ == "__main__":
    main()
