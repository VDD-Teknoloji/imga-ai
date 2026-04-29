"""imga-db: SQLAlchemy 2.0 + Alembic data layer for the imga platform."""

from imga_db.base import Base
from imga_db.session import (
    TENANT_SETTING,
    create_engine,
    create_session_factory,
    get_database_url,
    session_scope,
    set_current_tenant,
)

__version__ = "0.1.0"

__all__ = [
    "TENANT_SETTING",
    "Base",
    "__version__",
    "create_engine",
    "create_session_factory",
    "get_database_url",
    "session_scope",
    "set_current_tenant",
]
