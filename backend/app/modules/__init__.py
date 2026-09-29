"""Business modules (BUILD_PLAN §4): procurement, invoices, matching, review, audit, sync.

Each module is added by the step that builds it. `matching` must stay pure:
no database, HTTP or AI imports.
"""
