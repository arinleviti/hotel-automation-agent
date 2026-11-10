"""Opening a connection to Postgres."""

import psycopg

from backoffice.config import get_settings


def connect() -> psycopg.Connection:
    """
    Open a new connection using DATABASE_URL.

    Use it in a `with` block so it is always closed, and committed or rolled back:

        with connect() as conn:
            conn.execute("SELECT 1")
    """
    # connect_timeout: give up after 5 seconds per address instead of hanging forever when the
    # database isn't running (on Windows an unanswered connection can otherwise wait indefinitely).
    return psycopg.connect(get_settings().database_url, connect_timeout=5)
