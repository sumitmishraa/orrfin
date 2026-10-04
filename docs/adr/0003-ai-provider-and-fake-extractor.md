# ADR 0003: One AI port, three providers; the stand-in is always labelled

**Date:** 4 Oct 2026 · **Status:** accepted · **Plan:** BUILD_PLAN §3 AI row, §6 explanation, §7

## Context
Steps 7–10 need an AI to read invoices and to explain match results, but Bedrock model access is still
not granted (every call returns `400 Operation not allowed`, docs/spikes.md). The plan already allows
"Bedrock (or the Anthropic API directly)" behind one Extractor interface, and Step 7 asks for a
FakeExtractor for tests.

## Decision
- One setting, `AI_PROVIDER`: `bedrock` (default), `anthropic` (with `ANTHROPIC_API_KEY` in `.env`), or `fake`.
- `fake` returns the Step 6 answer keys for the evaluation PDFs only (matched by SHA-256). Its
  extractions are stored with `model_id = "fake-answer-key"`, and every screen shows "Simulated reading",
  so it is never mistaken for AI. Unknown PDFs go to manual entry, like a real outage.
- AI failures never block work: extraction retries 3 times, then switches the invoice to manual entry;
  a failed explanation falls back to a template built from the same rule results.
- The SDK makes one attempt per call (`max_retries=0`); the job queue owns retries and backoff.

## Consequences
- The whole workflow can be demonstrated and tested without AI, and the rules are proven end to end
  (all 12 evaluation PDFs give their expected outcome).
- Real extraction accuracy is still unmeasured: `evals/extraction/report.md` shows the Bedrock refusals.
  Rerun `backend/scripts/run_extraction_eval.py --provider bedrock` when access is granted, then set
  `AI_PROVIDER=bedrock` in `.env`.
