"""Registry of job handlers (BUILD_PLAN §4 worker). Importing this module registers them all.

Kept in one place so the worker and the tests load exactly the same set.
"""

from app.modules.sync import service as _sync_service  # noqa: F401  (registers "erp_pull")
from app.modules.invoices import service as _invoices_service  # noqa: F401  (registers "extract")
from app.modules.invoices import match_job as _match_job  # noqa: F401  (registers "match")
