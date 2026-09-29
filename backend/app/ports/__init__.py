"""Interfaces to the outside world (BUILD_PLAN §4): Extractor, ErpAdapter, FileStore, Clock.

Business modules depend on these ports, never on a concrete provider, so the
fake ERPNext, local disk and fake extractor can be swapped for the real ones.
"""
