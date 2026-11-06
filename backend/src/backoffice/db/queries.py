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
    # price comes back from NUMERIC(10,2) as a Decimal already: no conversion needed.
    return [SupplierPrice(supplier=s, code=c, product=p, unit=u, price=pr) for s, c, p, u, pr in rows]


def load_nights(conn: psycopg.Connection, start: date, end: date) -> dict[date, NightAvailability]:
    """
    Return the nights from `start` (included) up to `end` (excluded), as date -> NightAvailability.

    Same convention as a stay: load_nights(conn, Dec 18, Dec 21) -> the nights of Dec 18, 19, 20.
    Nights not in the database are simply absent from the dict, so check_availability reports
    them as missing (NO_DATA) instead of guessing.
    """
    rows = conn.execute(
        "SELECT night, rooms_total, rooms_booked FROM availability"
        " WHERE night >= %s AND night < %s ORDER BY night",
        (start, end),
    ).fetchall()
    # night comes back from DATE as a Python date already.
    return {night: NightAvailability(rooms_total=total, rooms_booked=booked) for night, total, booked in rows}
