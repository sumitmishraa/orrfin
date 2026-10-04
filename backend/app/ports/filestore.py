"""FileStore port: keep uploaded documents by key (BUILD_PLAN §3 Files, §4 ports).

Local disk during development; the S3 adapter arrives with the deploy step. Keys are
"<org_id>/<sha256>.pdf", so one org's files are never mixed with another's.
"""

from typing import Protocol


class FileStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...
