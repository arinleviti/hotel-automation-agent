"""Read the hotel's business data from Postgres, as the types the services already accept,
and record what the graph did (save_action, step 9.2).

The services never touch the database: these functions load the data, the caller passes it in.

    with connect() as conn:
        nights = load_nights(conn, check_in - timedelta(days=7), check_out + timedelta(days=7))
    result = check_availability(check_in, check_out, nights)
"""

from datetime import date, timedelta

import psycopg

from backoffice.graph.state import Decision, OutgoingDraft
from backoffice.services.availability import NightAvailability
from backoffice.services.invoice_check import SupplierPrice
from backoffice.services.pricing import RoomRates


def load_supplier_prices(conn: psycopg.Connection, supplier: str | None = None) -> list[SupplierPrice]:
    """
    Return the agreed prices, for one supplier or (supplier=None) for all of them.

    Example: load_supplier_prices(conn, "Front Range Provisions") -> 5 SupplierPrice rows.
    """
    sql = "SELECT supplier, code, product, unit, price FROM supplier_prices"
    params: tuple = ()
    if supplier is not None:
        sql += " WHERE supplier = %s"          # %s = placeholder: psycopg sends the value separately
        params = (supplier,)
    sql += " ORDER BY supplier, code"

    rows = conn.execute(sql, params).fetchall()
    # Shape of rows: list of tuples, one per row, values in SELECT order
    #   [
    #       ("Front Range Provisions", "FRP-1021", "Mozzarella, low-moisture whole milk", "lb", Decimal("4.25")),
    #       ("Front Range Provisions", "FRP-1034", "Butter, unsalted", "lb", Decimal("4.10")),
    #       ...
    #   ]
    # price comes back from NUMERIC(10,2) as a Decimal already: no conversion needed.

    # Shape returned: list of SupplierPrice instances
    #   [
    #       SupplierPrice(supplier="Front Range Provisions", code="FRP-1021",
    #                     product="Mozzarella, low-moisture whole milk", unit="lb", price=Decimal("4.25")),
    #       SupplierPrice(supplier="Front Range Provisions", code="FRP-1034",
    #                     product="Butter, unsalted", unit="lb", price=Decimal("4.10")),
    #       ...
    #   ]
    return [SupplierPrice(supplier=s, code=c, product=p, unit=u, price=pr) for s, c, p, u, pr in rows]


def load_nights(conn: psycopg.Connection, start: date, end: date) -> dict[date, NightAvailability]:
    """
    Return the nights from `start` (included) up to `end` (excluded), as date -> NightAvailability.

    Same convention as a stay: load_nights(conn, Dec 18, Dec 21) -> the nights of Dec 18, 19, 20.
    Nights not in the database are simply absent from the dict, so check_availability reports
    them as missing (NO_DATA) instead of guessing.
    """
    # rows is returned as a list of tuples: [(date, int, int), ...] where the ints are rooms_total and rooms_booked.
    rows = conn.execute(
        "SELECT night, rooms_total, rooms_booked FROM availability"
        " WHERE night >= %s AND night < %s ORDER BY night",
        (start, end),
    ).fetchall()
    # Shape of rows: list of tuples (night, rooms_total, rooms_booked)
    #   [
    #       (date(2026, 12, 30), 120, 120),
    #       (date(2026, 12, 31), 120, 120),
    #       ...
    #   ]
    # night comes back from DATE as a Python date already.

    # Shape returned: dict, key = the night's date, value = a NightAvailability instance
    #   {
    #       date(2026, 12, 30): NightAvailability(rooms_total=120, rooms_booked=120),
    #       date(2026, 12, 31): NightAvailability(rooms_total=120, rooms_booked=120),
    #       ...
    #   }
    return {night: NightAvailability(rooms_total=total, rooms_booked=booked) for night, total, booked in rows}


def save_action(conn: psycopg.Connection, thread_id: str, email_name: str, decision: Decision,
                message: OutgoingDraft, comment: str = "") -> bool:
    """
    Record what was done with one run's outgoing message: one row in the `actions` table.

    message: the FINAL message (the edited version after "edit"); after "reject", the draft that
             was refused, so the audit trail shows what was turned down.
    Returns True if the row was written, False if this run already had one (see below).

    IDEMPOTENT: thread_id is the table's primary key, and ON CONFLICT (thread_id) DO NOTHING tells
    Postgres "if a row for this run already exists, skip the insert, without an error". So if the
    action node runs twice for the same run (e.g. a crash after this insert but before LangGraph
    saved "action finished"), the message is still recorded only once.

    Example (email #9, approved):
        save_action(conn, "6b9a9f43-...", "09_suspicious_hidden_instruction", Decision.APPROVE,
                    OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, outgoing_to="Front desk <...>", ...))
        -> True   (a second identical call -> False)
    """
    cursor = conn.execute(
        "INSERT INTO actions (thread_id, email_name, decision, kind, outgoing_to,"
        " outgoing_subject, outgoing_body, comment)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (thread_id) DO NOTHING",
        (thread_id, email_name, str(decision), str(message.kind), message.outgoing_to,
         message.outgoing_subject, message.outgoing_body, comment),
    )
    # cursor.rowcount = how many rows the statement changed: 1 = inserted, 0 = skipped (already there).
    return cursor.rowcount == 1


def load_room_rates(conn: psycopg.Connection) -> RoomRates:
    """
    Return the room rates (phase 1: exactly one room type).

    Example: load_room_rates(conn) ->
        RoomRates(room_type="Mountain View Room", adult_rate=Decimal("185.00"), child_rate=Decimal("65.00"),
                  child_under_age=13, tax_rate=Decimal("0.1040"))
    Raises LookupError if the table is empty (the seed script hasn't been run).
    """
    rows = conn.execute(
        "SELECT room_type, adult_rate, child_rate, child_under_age, tax_rate FROM room_rates"
    ).fetchall()
    # Shape of rows: list of tuples, one per room type, values in SELECT order
    #   [("Mountain View Room", Decimal("185.00"), Decimal("65.00"), 13, Decimal("0.1040"))]
    if len(rows) != 1:
        raise LookupError(f"expected exactly 1 room type in room_rates, found {len(rows)} (run the seed script)")
    room_type, adult_rate, child_rate, child_under_age, tax_rate = rows[0]
    return RoomRates(room_type=room_type, adult_rate=adult_rate, child_rate=child_rate,
                     child_under_age=child_under_age, tax_rate=tax_rate)


# --- Runs and actions, for the backend API (step 15) ------------------------------------------------

def save_run(conn: psycopg.Connection, thread_id: str, email_name: str, visitor_id: str = "") -> None:
    """
    Record that a run started (one row in `runs`), and WHOSE run it is (step 16.2).
    Example: save_run(conn, "31917ec5-...", "03_booking_complete", "7c1e2b0a-...")
    """
    conn.execute("INSERT INTO runs (thread_id, email_name, visitor_id) VALUES (%s, %s, %s)"
                 " ON CONFLICT (thread_id) DO NOTHING",
                 (thread_id, email_name, visitor_id))


def load_latest_runs(conn: psycopg.Connection, visitor_id: str) -> dict[str, dict]:
    """
    ONE VISITOR's latest run of each email, with its decision if it has one (from `actions`).
    Another visitor's runs are never returned: each visitor sees their own inbox.

    DISTINCT ON (email_name) ... ORDER BY email_name, started_at DESC (Postgres): keep only the first
    row per email, i.e. the newest. LEFT JOIN actions: the decision, or NULL while waiting.

    Shape returned: dict, key = email name (only the emails this visitor processed)
        {"03_booking_complete": {"thread_id": "31917ec5-...", "started_at": datetime(...), "decision": "approve"},
         "08_question_helicopter_not_found": {"thread_id": "1e72...", "started_at": datetime(...), "decision": None},
         ...}
    """
    rows = conn.execute(
        "SELECT DISTINCT ON (r.email_name) r.email_name, r.thread_id, r.started_at, a.decision"
        " FROM runs r LEFT JOIN actions a ON a.thread_id = r.thread_id"
        " WHERE r.visitor_id = %s"
        " ORDER BY r.email_name, r.started_at DESC",
        (visitor_id,),
    ).fetchall()
    return {name: {"thread_id": thread_id, "started_at": started_at, "decision": decision}
            for name, thread_id, started_at, decision in rows}


def load_actions(conn: psycopg.Connection, visitor_id: str) -> list[dict]:
    """
    ONE VISITOR's decisions, newest first: what was sent (approve/edit) or rejected. The UI's "Sent" folder.
    JOIN runs: an action belongs to a visitor through its run (same thread_id).

    Shape returned: list of dicts
        [{"thread_id": "31917ec5-...", "email_name": "03_booking_complete", "decision": "approve",
          "kind": "reply_to_sender", "outgoing_to": "Sarah Mitchell <...>", "outgoing_subject": "Re: ...",
          "outgoing_body": "Dear Sarah Mitchell, ...", "comment": "", "decided_at": datetime(...)},
         ...]
    """
    columns = ("thread_id", "email_name", "decision", "kind", "outgoing_to", "outgoing_subject",
               "outgoing_body", "comment", "decided_at")
    rows = conn.execute(
        f"SELECT {', '.join('a.' + c for c in columns)}"
        " FROM actions a JOIN runs r ON r.thread_id = a.thread_id"
        " WHERE r.visitor_id = %s ORDER BY a.decided_at DESC",
        (visitor_id,),
    ).fetchall()
    # zip(columns, row) (plain Python): pairs each column name with its value -> dict(...) builds the dict
    return [dict(zip(columns, row)) for row in rows]


def load_run_visitor(conn: psycopg.Connection, thread_id: str) -> str | None:
    """
    Whose run is this? The visitor_id saved with it, or None if there is no such run.
    The API uses it so a visitor can only open or decide THEIR OWN runs.
    Example: load_run_visitor(conn, "31917ec5-...") -> "7c1e2b0a-..."
    """
    row = conn.execute("SELECT visitor_id FROM runs WHERE thread_id = %s", (thread_id,)).fetchone()
    return row[0] if row else None


def delete_old_runs(conn: psycopg.Connection, older_than: timedelta) -> list[str]:
    """
    The demo's cleanup (step 16.2): delete every run started more than `older_than` ago (2 hours in
    the API), with its decision, and every decision older than that (also the command line's ones).
    Returns the thread_ids of the deleted runs, so the caller can also delete their checkpoints
    (the saved graph states, in LangGraph's own tables).

    Example: delete_old_runs(conn, timedelta(hours=2)) -> ["31917ec5-...", "1e72..."]
    `now() - %s` (Postgres): the current time minus the interval psycopg sends for the timedelta.
    """
    old_runs = "SELECT thread_id FROM runs WHERE started_at < now() - %s"
    conn.execute(f"DELETE FROM actions WHERE decided_at < now() - %s OR thread_id IN ({old_runs})",
                 (older_than, older_than))
    rows = conn.execute("DELETE FROM runs WHERE started_at < now() - %s RETURNING thread_id",
                        (older_than,)).fetchall()
    return [thread_id for (thread_id,) in rows]


def count_recent_runs(conn: psycopg.Connection, visitor_id: str) -> tuple[int, int]:
    """
    How many runs were started recently, for the demo's spending limits (step 18):
    (this visitor's runs in the last 2 hours, everyone's runs in the last hour).
    Example: count_recent_runs(conn, "7c1e2b0a-...") -> (12, 47)

    count(*) FILTER (WHERE ...) (Postgres): counts only the rows that match the condition, so both
    numbers come from one pass over the table.
    """
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE visitor_id = %s AND started_at > now() - interval '2 hours'),"
        "       count(*) FILTER (WHERE started_at > now() - interval '1 hour')"
        " FROM runs",
        (visitor_id,),
    ).fetchone()
    return row[0], row[1]
