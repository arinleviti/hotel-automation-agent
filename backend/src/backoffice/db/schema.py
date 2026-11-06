"""Create the database tables from schema.sql.

Run:  uv run python -m backoffice.db.schema
"""

from pathlib import Path

import psycopg

from backoffice.db.connection import connect

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def apply_schema(conn: psycopg.Connection) -> None:
    """Run schema.sql on this connection. Safe to repeat: every statement uses IF NOT EXISTS."""
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    with connect() as conn:
        apply_schema(conn)
    print("Schema applied: tables supplier_prices and availability are ready.")
