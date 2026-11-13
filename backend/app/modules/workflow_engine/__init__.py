"""Workflow engine (BUILD_PLAN v3.0 change 39, ADR 0010).

A workflow is data: a JSON definition checked by `definition.validate` and walked by
`evaluate.route`. Both are pure (no database, no HTTP, no AI), so the same definition and the
same facts always give the same route. The engine decides *which steps a record needs*; it never
decides *who is allowed to approve*: that stays in the §9 checks (procurement.decision_refusal).
"""
