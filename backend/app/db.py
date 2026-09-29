"""Database engine, session factory and the declarative Base (BUILD_PLAN §3, §5).

No tables exist yet; Step 3 adds them through Alembic migrations. The naming
convention below gives every constraint a predictable name, so later
migrations can refer to constraints without guessing auto-generated names.
"""

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# pool_pre_ping drops connections that Postgres closed (e.g. after a container restart).
engine = create_engine(get_settings().database_url, pool_pre_ping=True)


@event.listens_for(engine, "connect")
def _use_app_role(dbapi_connection, _record) -> None:
    """Run every app query as the restricted `orrfin_app` role (BUILD_PLAN §5 grants).

    The login user owns the schema (migrations need that); the app role can only
    INSERT/SELECT audit_events, so even a bug cannot rewrite the audit trail.
    Committed at once: an uncommitted SET ROLE would be undone by the next rollback.
    See docs/adr/0002-app-database-role.md.
    """
    role = get_settings().db_app_role
    if not role:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute(f'SET ROLE "{role}"')
    cursor.close()
    dbapi_connection.commit()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    with SessionLocal() as session:
        yield session
