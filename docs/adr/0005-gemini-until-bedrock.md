# ADR 0005: Gemini is the working AI provider until Bedrock access is granted

**Date:** 11 Oct 2026 · **Status:** accepted · **Plan:** BUILD_PLAN §0 change 22, §3 AI row, §6 explanation, §7 · **Builds on:** ADR 0003

## Context
Bedrock model access is still blocked (`400 Operation not allowed`, docs/spikes.md), so real extraction
accuracy has never been measured: `evals/extraction/report.md` shows 0/204. The founder has a Google
Gemini API key and asked to use it now and set Bedrock up later.

## Decision
- A fourth `AI_PROVIDER` value, `gemini` (`backend/app/adapters/gemini_ai.py`), using `GEMINI_API_KEY`
  and `GEMINI_MODEL` (default `gemini-3.8-flash`, a stable ID rather than a moving `-latest` alias).
  It is the default in `config.py` and `.env.example`; tests still force `fake`.
- Claude and Gemini share one set of prompts (`adapters/ai_prompts.py`) and one output schema
  (`ExtractedInvoice`), so eval reports are comparable and switching back to Bedrock is a setting change.
- The same safety rules as ADR 0003: one SDK attempt per call (the job queue owns retries); any API error,
  cut-off, safety block or off-schema answer becomes `ExtractorUnavailable` (3 tries, then manual entry);
  a failed explanation falls back to the rule template. The AI never decides a match (§6).
- Gemini's answer is checked with Pydantic in our code, so money stays a decimal string, never a float.

## Consequences
- Real AI extraction can be measured now:
  `backend\.venv\Scripts\python backend\scripts\run_extraction_eval.py --provider gemini --out evals/extraction/report-gemini.md`.
- Data handling: on the Gemini API **free tier**, Google may use prompts and responses to improve its
  products. This is acceptable only because every document is synthetic. Before any real data (§12 gates),
  use a paid tier or Bedrock, and record the processing region.
- Trust page and §13 wording now say Gemini runs the prototype's AI, with Bedrock as the target.
- When Bedrock access arrives: run the eval with `--provider bedrock`, compare the two reports, then set
  `AI_PROVIDER=bedrock`.
