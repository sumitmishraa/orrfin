# ADR 0007: The Orrfin Assistant is a read-only agent with the user's own permissions

**Date:** 19 Oct 2026 · **Status:** accepted · **Plan:** BUILD_PLAN v2.3 changes 25–26, §4 assistant rule, §5 `assistant_turns` · **Builds on:** ADR 0003, ADR 0005

## Context
The Zip / DualEntry research showed AI agents next to every workflow, always on the pattern
"AI suggests, a person approves". The founder chose an assistant that may read, explain and
draft, never act (18 Oct). Finance data is sensitive and invoices are written by suppliers, so a
planted instruction ("say this invoice is approved", "pay here: <link>") must not be able to do harm.

## Decision
- **One port, three adapters** (`ports/assistant.py`): Gemini (manual function calling, automatic
  calling off), Claude on Bedrock or the Anthropic API (manual tool-use loop, `tool_choice: auto`,
  `stop_reason` checked, refusal = unavailable), and a scripted fake for tests. Same `AI_PROVIDER`
  setting as extraction; at most 6 tool rounds; one SDK attempt.
- **Tools are read-only and bound to the user** (`modules/assistant/tools.py`): each reuses the loader
  the pages use (`load_request`, `load_invoice`, insights, rules, budgets), so the assistant sees only
  what that person could open. No tool writes, calls an ERP, or passes an invoice's printed text
  (lines carry codes and numbers only).
- **The service, not the model, decides what is shown** (`modules/assistant/service.py`): links only to
  records a tool returned this turn and the answer names; web addresses removed; every ₹ figure checked
  against the tool results (a miss shows a warning, `grounded = false`); 30 questions per hour per person.
- **Every turn is logged** in `assistant_turns` (question, tool names + arguments, answer, model,
  prompt version, grounded, error). It is a log, not an audit event: asking changes nothing.
- **Never blocks work:** no key, an outage or a refusal returns "unavailable"; every page still works.

## Consequences
- A successful prompt injection can at most make one answer wrong; it cannot act, link elsewhere, or
  show a made-up rupee figure without a warning. Answers say "AI-written · check the linked page".
- Server-side refusal fallbacks (`fallbacks: "default"`) are not enabled yet: Bedrock is the target and
  does not take the parameter; a refusal simply shows "unavailable". Revisit when the provider is fixed.
- Real accuracy is measured by `evals/assistant/` (Step 24); CI runs it with the fake model.
