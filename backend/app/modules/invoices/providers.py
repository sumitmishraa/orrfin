"""Which Extractor, Explainer and FileStore the invoices module uses (BUILD_PLAN §4 ports; §3 AI row).

Chosen from settings (AI_PROVIDER, FILE_STORE_DIR). Tests swap the extractor with
`use_extractor(...)`, e.g. to simulate an AI outage, without touching settings.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from typing import Any

from app.adapters.claude_ai import ClaudeExplainer, ClaudeExtractor, build_client
from app.adapters.fake_extractor import FakeExtractor
from app.adapters.gemini_ai import GeminiExplainer, GeminiExtractor, build_gemini_client
from app.adapters.local_filestore import LocalFileStore
from app.config import REPO_ROOT, get_settings
from app.ports.extractor import Extractor
from app.ports.filestore import FileStore

ANSWER_KEY_DIRS = [REPO_ROOT / "evals" / "extraction", REPO_ROOT / "seed" / "invoices"]
_override: Extractor | None = None


def get_extractor() -> Extractor:
    if _override is not None:
        return _override
    settings = get_settings()
    if settings.ai_provider == "fake":
        return FakeExtractor(ANSWER_KEY_DIRS)
    if settings.ai_provider == "gemini":
        return GeminiExtractor(*build_gemini_client(settings))
    return ClaudeExtractor(*build_client(settings))


def get_explainer() -> Any | None:
    """The AI that writes match explanations, or None for "fake" (the template is used instead)."""
    settings = get_settings()
    if settings.ai_provider == "fake":
        return None
    if settings.ai_provider == "gemini":
        return GeminiExplainer(*build_gemini_client(settings))
    return ClaudeExplainer(*build_client(settings))


def get_file_store() -> FileStore:
    return LocalFileStore(REPO_ROOT / get_settings().file_store_dir)


_assistant_override: Any | None = None


def get_assistant() -> Any:
    """The model behind the Orrfin Assistant (ADR 0007), from the same AI_PROVIDER setting.

    "fake" has no assistant: the scripted FakeAssistant is only for tests (use_assistant).
    A missing key raises ExtractorUnavailable, which the assistant service reports as unavailable.
    """
    if _assistant_override is not None:
        return _assistant_override
    settings = get_settings()
    if settings.ai_provider == "fake":
        return None
    if settings.ai_provider == "gemini":
        from app.adapters.gemini_assistant import GeminiAssistant

        return GeminiAssistant(*build_gemini_client(settings))
    from app.adapters.claude_assistant import ClaudeAssistant

    return ClaudeAssistant(*build_client(settings))


_drafter_override: Any | None = None


def get_drafter() -> Any:
    """The writer behind intake drafts and AI notes (Step 24); None for "fake" (templates are used)."""
    if _drafter_override is not None:
        return _drafter_override
    settings = get_settings()
    if settings.ai_provider == "fake":
        return None
    if settings.ai_provider == "gemini":
        from app.adapters.gemini_assistant import GeminiDrafter

        return GeminiDrafter(*build_gemini_client(settings))
    from app.adapters.claude_assistant import ClaudeDrafter

    return ClaudeDrafter(*build_client(settings))


@contextmanager
def use_drafter(drafter: Any) -> Iterator[None]:
    global _drafter_override
    previous, _drafter_override = _drafter_override, drafter
    try:
        yield
    finally:
        _drafter_override = previous


@contextmanager
def use_assistant(assistant: Any) -> Iterator[None]:
    global _assistant_override
    previous, _assistant_override = _assistant_override, assistant
    try:
        yield
    finally:
        _assistant_override = previous


@contextmanager
def use_extractor(extractor: Extractor) -> Iterator[None]:
    global _override
    previous, _override = _override, extractor
    try:
        yield
    finally:
        _override = previous
