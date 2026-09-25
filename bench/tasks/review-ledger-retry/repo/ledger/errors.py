"""Classification of database errors."""
import sqlite3

# Message prefixes (lower case) of sqlite3.OperationalError worth retrying.
TRANSIENT_MESSAGES = (
    'database is locked',
    'database table is locked',
    'disk i/o error',
)


def is_transient(exc):
    """True if `exc` is a SQLite failure that may succeed when retried."""
    return (isinstance(exc, sqlite3.OperationalError)
            and str(exc).lower().startswith(TRANSIENT_MESSAGES))
