"""Create the database tables: ours (schema.sql) and LangGraph's checkpoint tables.

Run:  uv run python -m backoffice.db.schema
Safe to run any number of times: nothing is deleted, existing tables are left as they are.
"""

from pathlib import Path

import psycopg

from backoffice.db.connection import connect

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def apply_schema(conn: psycopg.Connection) -> None:
    """Run schema.sql on this connection. Safe to repeat: every statement uses IF NOT EXISTS."""
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    # Our tables (schema.sql).
    with connect() as conn:
        apply_schema(conn)
    print("Schema applied: tables supplier_prices, availability, room_rates, chunks and actions are ready.")

    # LangGraph's tables, where paused runs are saved (step 9.3). Imported here, not at the top:
    # graph/checkpointer.py imports LangGraph, which the seed script (also using apply_schema) doesn't need.
    from backoffice.graph.checkpointer import setup_checkpoint_tables
    setup_checkpoint_tables()
    print("Checkpoint tables ready: checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations.")
