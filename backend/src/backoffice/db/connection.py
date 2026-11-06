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
    return psycopg.connect(get_settings().database_url)
