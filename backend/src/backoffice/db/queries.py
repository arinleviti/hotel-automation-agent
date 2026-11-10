"""Read the hotel's business data from Postgres, as the types the services already accept.

The services never touch the database: these functions load the data, the caller passes it in.

    with connect() as conn:
        nights = load_nights(conn, check_in - timedelta(days=7), check_out + timedelta(days=7))
    result = check_availability(check_in, check_out, nights)
"""

from datetime import date

import psycopg

from backoffice.services.availability import NightAvailability
from backoffice.services.invoice_check import SupplierPrice


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
