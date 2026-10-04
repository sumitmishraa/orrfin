"""LocalFileStore: the FileStore port on local disk (BUILD_PLAN §3 "Files on local disk", PROMPTS Step 7)."""

from pathlib import Path


class LocalFileStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Keys come from our own code, but refuse anything that would escape the store anyway.
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"File key escapes the store: {key!r}")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()
