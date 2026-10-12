"""Registry of job handlers (BUILD_PLAN §4 worker). Importing this module registers them all.

Kept in one place so the worker and the tests load exactly the same set.
"""

from app.modules.sync import service as _sync_service  # noqa: F401  (registers "erp_pull")
from app.modules.invoices import service as _invoices_service  # noqa: F401  (registers "extract")
from app.modules.invoices import match_job as _match_job  # noqa: F401  (registers "match")
from app.modules.connectors import router as _connectors_router  # noqa: F401  (registers "erp_prepare")
from app.modules.erp_outbox import service as _erp_outbox  # noqa: F401  (registers "erp_push")
