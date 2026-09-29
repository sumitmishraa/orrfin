"""Checks that the configured Postgres is reachable (runs in CI against a service container).

Skipped on a laptop when no database is running, so `pytest` still works offline.
In CI (where the CI variable is set) a missing database is a failure, not a skip.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import engine


def test_database_answers_a_query() -> None:
    try:
        with engine.connect() as connection:
            result = connection.execute(text("select 1")).scalar_one()
    except DBAPIError:
        if os.environ.get("CI"):
            raise
        pytest.skip("Postgres is not running; start it with scripts/dev.ps1")

    assert result == 1
