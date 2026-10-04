"""Which Extractor and FileStore the invoices module uses (BUILD_PLAN §4 ports; §3 AI row).

Chosen from settings (AI_PROVIDER, FILE_STORE_DIR). Tests swap the extractor with
`use_extractor(...)`, e.g. to simulate an AI outage, without touching settings.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from app.adapters.claude_ai import ClaudeExtractor, build_client
from app.adapters.fake_extractor import FakeExtractor
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
    return ClaudeExtractor(*build_client(settings))


def get_file_store() -> FileStore:
    return LocalFileStore(REPO_ROOT / get_settings().file_store_dir)


@contextmanager
def use_extractor(extractor: Extractor) -> Iterator[None]:
    global _override
    previous, _override = _override, extractor
    try:
        yield
    finally:
        _override = previous
