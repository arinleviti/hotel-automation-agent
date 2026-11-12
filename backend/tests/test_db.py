"""Database tests: seed the real CSVs into Postgres, then read them back with the queries.

They need the Docker database running (docker compose up -d). If it isn't, every test here
is SKIPPED, not failed, so `uv run pytest` still works with Docker off.
Note: they re-seed the database from data/*.csv, which is what the seed script does anyway.
"""

from datetime import date
from decimal import Decimal

import psycopg
import pytest

from backoffice.db.connection import connect
from backoffice.db.queries import load_nights, load_room_rates, load_supplier_prices
from backoffice.db.seed import DATA_DIR, load, parse_availability, parse_room_rates, parse_supplier_prices, read_csv


@pytest.fixture(scope="module")
def conn():
    """
    One connection shared by the tests in this file, with the real CSVs loaded.

    A fixture is setup code pytest runs for any test that asks for it by name (the `conn`
    parameter). scope="module": run once for the whole file, not once per test.
    """
    try:
        connection = connect()
    except Exception as e:   # database not running, or DATABASE_URL not set
        pytest.skip(f"Postgres not available ({type(e).__name__}): start it with `docker compose up -d`")

    prices = parse_supplier_prices(read_csv(DATA_DIR / "supplier_prices.csv"))
    availability = parse_availability(read_csv(DATA_DIR / "availability.csv"))
    rates = parse_room_rates(read_csv(DATA_DIR / "room_rates.csv"))
    load(connection, prices, availability.nights, rates)

    yield connection          # the tests run here
    connection.close()        # cleanup after the last test of the file


def test_all_supplier_prices_are_loaded(conn):
    assert len(load_supplier_prices(conn)) == 15


def test_prices_for_one_supplier_come_back_as_decimal(conn):
    prices = load_supplier_prices(conn, "Front Range Provisions")

    assert [p.code for p in prices] == ["FRP-1021", "FRP-1034", "FRP-2002", "FRP-3110", "FRP-4405"]
    assert prices[0].price == Decimal("4.25")
    assert isinstance(prices[0].price, Decimal)


def test_unknown_supplier_gives_an_empty_list(conn):
    assert load_supplier_prices(conn, "Nobody Inc.") == []


def test_load_nights_includes_start_and_excludes_end(conn):
    nights = load_nights(conn, date(2026, 12, 18), date(2026, 12, 21))

    assert list(nights) == [date(2026, 12, 18), date(2026, 12, 19), date(2026, 12, 20)]


def test_email_5_nights_are_full_in_the_database(conn):
    nights = load_nights(conn, date(2026, 12, 30), date(2027, 1, 1))

    assert nights[date(2026, 12, 30)].rooms_booked == 120
    assert nights[date(2026, 12, 31)].rooms_booked == 120


def test_nights_outside_the_data_are_absent(conn):
    assert load_nights(conn, date(2027, 4, 10), date(2027, 4, 12)) == {}


def test_seeding_twice_gives_the_same_result(conn):
    prices = parse_supplier_prices(read_csv(DATA_DIR / "supplier_prices.csv"))
    availability = parse_availability(read_csv(DATA_DIR / "availability.csv"))
    rates = parse_room_rates(read_csv(DATA_DIR / "room_rates.csv"))
    load(conn, prices, availability.nights, rates)

    assert len(load_supplier_prices(conn)) == 15
    assert conn.execute("SELECT count(*) FROM availability").fetchone() == (151,)


def test_database_rejects_a_negative_price(conn):
    # The CHECK constraint in schema.sql is the last line of defence, even if Python validation is bypassed.
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("INSERT INTO supplier_prices VALUES ('Test', 'X-1', 'Test', 'lb', -1.00)")


def test_room_rates_come_back_as_in_the_rate_card(conn):
    rates = load_room_rates(conn)

    assert rates.room_type == "Mountain View Room"
    assert (rates.adult_rate, rates.child_rate) == (Decimal("185.00"), Decimal("65.00"))
    assert rates.child_under_age == 13
    assert rates.tax_rate == Decimal("0.104")                  # NUMERIC(6,4) gives 0.1040: the same number
