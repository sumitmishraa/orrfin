"""The AI layer: superagents, proposals a person submits, the workflow-builder agent (BUILD_PLAN change 47, ADR 0007).

AI reads (through the same permission-bound tools as the pages) and proposes. It never submits,
approves, awards, publishes, pays or scores risk: a named person does that through the normal endpoint.
"""
