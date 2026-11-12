"""Read the hotel's business data from Postgres, as the types the services already accept,
and record what the graph did (save_action, step 9.2).

The services never touch the database: these functions load the data, the caller passes it in.

    with connect() as conn:
        nights = load_nights(conn, check_in - timedelta(days=7), check_out + timedelta(days=7))
    result = check_availability(check_in, check_out, nights)
"""

from datetime import date

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
