"""Seed validation tests: pure functions, no database needed."""

from datetime import date
from decimal import Decimal

import pytest

from backoffice.db.seed import SeedError, parse_availability, parse_supplier_prices, read_csv

# --- Helpers: CSV rows as read_csv returns them (every value is text) -----------------------


def price_row(supplier="Front Range Provisions", code="FRP-1021",
              product="Mozzarella, low-moisture whole milk", unit="lb", price="4.25") -> dict[str, str]:
    # Shape: {"supplier": "Front Range Provisions", "code": "FRP-1021", ..., "price": "4.25"}
    return {"supplier": supplier, "code": code, "product": product, "unit": unit, "price": price}


def night_row(day: str, total="120", booked="80") -> dict[str, str]:
    # Shape: {"date": "2026-12-30", "rooms_total": "120", "rooms_booked": "80"}
    return {"date": day, "rooms_total": total, "rooms_booked": booked}


# --- read_csv -----------------------------------------------------------------------------


def test_read_csv_accepts_excel_bom(tmp_path):
    # tmp_path: a fresh temporary folder pytest gives each test, deleted afterwards.
    path = tmp_path / "prices.csv"
    path.write_text("supplier,code,product,unit,price\nA,X-1,Thing,lb,1.00\n", encoding="utf-8-sig")  # adds the BOM

    rows = read_csv(path)

    assert rows == [{"supplier": "A", "code": "X-1", "product": "Thing", "unit": "lb", "price": "1.00"}]


# --- parse_supplier_prices ----------------------------------------------------------------


def test_valid_prices_become_supplier_prices_with_decimal():
    prices = parse_supplier_prices([price_row(), price_row(code="FRP-1034", product="Butter, unsalted", price="4.10")])

    assert len(prices) == 2
    assert prices[0].price == Decimal("4.25")
    assert isinstance(prices[1].price, Decimal)


@pytest.mark.parametrize(
    "bad_row, expected_message",
    [
        (price_row(price="four"), "is not a number"),
        (price_row(price="-1.00"), "is negative"),
        (price_row(price="4.255"), "more than 2 decimals"),
        (price_row(supplier=""), "missing supplier"),
    ],
)
def test_bad_price_row_is_rejected_with_its_line_number(bad_row, expected_message):
    with pytest.raises(SeedError) as error:
        parse_supplier_prices([bad_row])

    assert error.value.problems == [error.value.problems[0]]          # exactly one problem
    assert error.value.problems[0].startswith("line 2:")             # line 1 is the header
    assert expected_message in error.value.problems[0]


def test_duplicate_supplier_and_code_is_rejected():
    with pytest.raises(SeedError) as error:
        parse_supplier_prices([price_row(), price_row(product="Duplicate mozzarella")])

    assert "line 3: duplicate code FRP-1021" in error.value.problems[0]


def test_all_problems_are_reported_not_just_the_first():
    with pytest.raises(SeedError) as error:
        parse_supplier_prices([price_row(price="four"), price_row(code="FRP-2", price="-1"), price_row(code="FRP-3")])

    assert len(error.value.problems) == 2   # lines 2 and 3; line 4 is fine


# --- parse_availability -------------------------------------------------------------------


def test_valid_nights_become_a_dict_of_night_availability():
    data = parse_availability([night_row("2026-12-30", booked="120"), night_row("2026-12-31", booked="120")])

    assert data.nights[date(2026, 12, 30)].rooms_booked == 120
    assert list(data.nights) == [date(2026, 12, 30), date(2026, 12, 31)]
    assert data.warnings == []


def test_gap_inside_the_date_range_is_rejected():
    with pytest.raises(SeedError) as error:
        parse_availability([night_row("2026-12-18"), night_row("2026-12-20")])   # Dec 19 missing

    assert error.value.problems == ["missing night 2026-12-19 (gap inside the date range)"]


def test_duplicate_date_is_rejected():
    with pytest.raises(SeedError) as error:
        parse_availability([night_row("2026-12-18"), night_row("2026-12-18")])

    assert "duplicate date 2026-12-18" in error.value.problems[0]


@pytest.mark.parametrize(
    "bad_row, expected_message",
    [
        (night_row("2026-13-01"), "not a valid YYYY-MM-DD date"),
        (night_row("2026-12-18", booked="many"), "whole numbers"),
        (night_row("2026-12-18", total="0"), "impossible room counts"),
        (night_row("2026-12-18", booked="-3"), "impossible room counts"),
    ],
)
def test_bad_night_row_is_rejected(bad_row, expected_message):
    with pytest.raises(SeedError) as error:
        parse_availability([bad_row])

    assert expected_message in error.value.problems[0]


def test_overbooked_night_is_a_warning_not_an_error():
    data = parse_availability([night_row("2026-12-18", total="120", booked="122")])

    assert data.nights[date(2026, 12, 18)].rooms_booked == 122     # still loaded
    assert len(data.warnings) == 1
    assert "overbooked" in data.warnings[0]
