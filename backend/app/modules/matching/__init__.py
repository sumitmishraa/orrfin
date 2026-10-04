"""Matching (BUILD_PLAN §6): deterministic rules that decide whether an invoice matches its PO and receipt.

Pure by rule (§4): nothing here imports the database, HTTP or AI code. It takes plain
data and returns a result with RULE_SET_VERSION, so every decision can be re-run and explained.
"""
