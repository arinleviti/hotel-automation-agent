"""Load the hotel's CSV files into Postgres, after validating them.

Run:  uv run python -m backoffice.db.seed

1. Read data/supplier_prices.csv, data/availability.csv and data/room_rates.csv.
2. Validate every row and collect ALL problems (not just the first one).
   Any error -> stop before touching the database. Warnings are printed but don't stop.
3. In ONE transaction: create the tables if needed, empty them, insert everything.
   If anything fails, nothing changes. Running it twice gives the same result.
   (Only these three tables are emptied: never `actions`, `chunks` or LangGraph's checkpoint tables.)
"""

import csv
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg

from backoffice.db.connection import connect
from backoffice.db.schema import apply_schema
from backoffice.services.availability import NightAvailability
from backoffice.services.invoice_check import SupplierPrice
from backoffice.services.pricing import RoomRates

# seed.py is at backend/src/backoffice/db/ -> four levels up is the repo root.
DATA_DIR = Path(__file__).resolve().parents[4] / "data"


class SeedError(Exception):
    """The CSV data is invalid. `problems` lists every problem found, with its line number."""

    def __init__(self, filename: str, problems: list[str]):
        self.problems = problems
        super().__init__(f"{filename}: {len(problems)} problem(s)\n  " + "\n  ".join(problems))


@dataclass
class AvailabilityData:
    nights: dict[date, NightAvailability]
    warnings: list[str] = field(default_factory=list)


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of rows (each row: column name -> text).

    "utf-8-sig" also accepts files saved by Excel, which start with an invisible BOM marker
    that would otherwise turn the first header "supplier" into "\\ufeffsupplier".
    """
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# --- Validation: pure functions, no database (easy to test) -------------------------------


def parse_supplier_prices(rows: list[dict[str, str]]) -> list[SupplierPrice]:
    """Turn CSV rows into SupplierPrice objects, or raise SeedError listing every problem."""
    prices: list[SupplierPrice] = []
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()

    for line_no, row in enumerate(rows, start=2):          # line 1 is the header
        values = {k: (row.get(k) or "").strip() for k in ("supplier", "code", "product", "unit", "price")}
        missing = [k for k, v in values.items() if not v]
        if missing:
            problems.append(f"line {line_no}: missing {', '.join(missing)}")
            continue

        try:
            price = Decimal(values["price"])
        except InvalidOperation:
            problems.append(f"line {line_no}: price {values['price']!r} is not a number")
            continue
        if price < 0:
            problems.append(f"line {line_no}: price {price} is negative")
            continue
        if price.as_tuple().exponent < -2:
            problems.append(f"line {line_no}: price {price} has more than 2 decimals")
            continue

        key = (values["supplier"], values["code"])
        if key in seen:
            problems.append(f"line {line_no}: duplicate code {values['code']} for {values['supplier']}")
            continue
        seen.add(key)

        prices.append(SupplierPrice(values["supplier"], values["code"], values["product"],
                                    values["unit"], price))

    if problems:
        raise SeedError("supplier_prices.csv", problems)
    return prices


def parse_availability(rows: list[dict[str, str]]) -> AvailabilityData:
    """Turn CSV rows into nights (date -> NightAvailability), or raise SeedError listing every problem."""
    nights: dict[date, NightAvailability] = {}
    problems: list[str] = []
    warnings: list[str] = []

    for line_no, row in enumerate(rows, start=2):
        try:
            night = date.fromisoformat((row.get("date") or "").strip())
        except ValueError:
            problems.append(f"line {line_no}: date {row.get('date')!r} is not a valid YYYY-MM-DD date")
            continue
        try:
            total = int((row.get("rooms_total") or "").strip())
            booked = int((row.get("rooms_booked") or "").strip())
        except ValueError:
            problems.append(f"line {line_no}: rooms_total and rooms_booked must be whole numbers")
            continue
        if total <= 0 or booked < 0:
            problems.append(f"line {line_no}: impossible room counts (total {total}, booked {booked})")
            continue
        if night in nights:
            problems.append(f"line {line_no}: duplicate date {night}")
            continue
        if booked > total:
            warnings.append(f"line {line_no}: {night} is overbooked ({booked} booked of {total})")
        nights[night] = NightAvailability(rooms_total=total, rooms_booked=booked)

    # Gaps: every night between the first and the last must be present.
    if nights:
        current, last = min(nights), max(nights)
        while current <= last:
            if current not in nights:
                problems.append(f"missing night {current} (gap inside the date range)")
            current += timedelta(days=1)

    if problems:
        raise SeedError("availability.csv", problems)
    return AvailabilityData(nights=nights, warnings=warnings)


def parse_room_rates(rows: list[dict[str, str]]) -> RoomRates:
    """
    Turn the CSV rows into RoomRates, or raise SeedError listing every problem.

    Phase 1 has ONE room type, so the file must have exactly one row:
        room_type,adult_rate,child_rate,child_under_age,tax_rate
        Mountain View Room,185.00,65.00,13,0.104
    -> RoomRates(room_type="Mountain View Room", adult_rate=Decimal("185.00"), child_rate=Decimal("65.00"),
                 child_under_age=13, tax_rate=Decimal("0.104"))
    """
    if len(rows) != 1:
        raise SeedError("room_rates.csv", [f"expected exactly 1 room type (one room type in phase 1), found {len(rows)}"])

    row = rows[0]
    line_no = 2                                                # line 1 is the header
    values = {k: (row.get(k) or "").strip()
              for k in ("room_type", "adult_rate", "child_rate", "child_under_age", "tax_rate")}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise SeedError("room_rates.csv", [f"line {line_no}: missing {', '.join(missing)}"])

    problems: list[str] = []
    money: dict[str, Decimal] = {}
    for column in ("adult_rate", "child_rate"):
        try:
            amount = Decimal(values[column])
        except InvalidOperation:
            problems.append(f"line {line_no}: {column} {values[column]!r} is not a number")
            continue
        if amount < 0 or amount.as_tuple().exponent < -2:
            problems.append(f"line {line_no}: {column} {amount} must be >= 0 with at most 2 decimals")
            continue
        money[column] = amount

    try:
        child_under_age = int(values["child_under_age"])
        if child_under_age <= 0:
            problems.append(f"line {line_no}: child_under_age must be a positive whole number")
    except ValueError:
        problems.append(f"line {line_no}: child_under_age {values['child_under_age']!r} is not a whole number")
        child_under_age = 0

    try:
        tax_rate = Decimal(values["tax_rate"])
        if not (0 <= tax_rate < 1):
            problems.append(f"line {line_no}: tax_rate {tax_rate} must be a decimal between 0 and 1 (0.104 = 10.4%)")
    except InvalidOperation:
        problems.append(f"line {line_no}: tax_rate {values['tax_rate']!r} is not a number")
        tax_rate = Decimal("0")

    if problems:
        raise SeedError("room_rates.csv", problems)
    return RoomRates(room_type=values["room_type"], adult_rate=money["adult_rate"], child_rate=money["child_rate"],
                     child_under_age=child_under_age, tax_rate=tax_rate)


# --- Loading: one transaction ---------------------------------------------------------------


def load(conn: psycopg.Connection, prices: list[SupplierPrice], nights: dict[date, NightAvailability],
         rates: RoomRates) -> None:
    """Replace the contents of the three business tables, all-or-nothing."""
    with conn.transaction():
        apply_schema(conn)
        conn.execute("TRUNCATE supplier_prices, availability, room_rates")
        conn.execute(
            "INSERT INTO room_rates (room_type, adult_rate, child_rate, child_under_age, tax_rate)"
            " VALUES (%s, %s, %s, %s, %s)",
            (rates.room_type, rates.adult_rate, rates.child_rate, rates.child_under_age, rates.tax_rate),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO supplier_prices (supplier, code, product, unit, price) VALUES (%s, %s, %s, %s, %s)",
                [(p.supplier, p.code, p.product, p.unit, p.price) for p in prices],
            )
            cur.executemany(
                "INSERT INTO availability (night, rooms_total, rooms_booked) VALUES (%s, %s, %s)",
                [(d, n.rooms_total, n.rooms_booked) for d, n in sorted(nights.items())],
            )


def main(data_dir: Path = DATA_DIR) -> int:
    # 1 + 2: read and validate everything before connecting to the database.
    try:
        prices = parse_supplier_prices(read_csv(data_dir / "supplier_prices.csv"))
        availability = parse_availability(read_csv(data_dir / "availability.csv"))
        rates = parse_room_rates(read_csv(data_dir / "room_rates.csv"))
    except SeedError as e:
        print(f"Seed stopped, nothing was loaded.\n{e}")
        return 1

    for warning in availability.warnings:
        print(f"Warning: {warning}")

    # 3: load in one transaction.
    with connect() as conn:
        load(conn, prices, availability.nights, rates)

    first, last = min(availability.nights), max(availability.nights)
    print(f"Loaded {len(prices)} supplier prices, {len(availability.nights)} nights ({first} to {last}) "
          f"and the {rates.room_type} rates (${rates.adult_rate} adult, ${rates.child_rate} child, "
          f"tax {(rates.tax_rate * 100).normalize()}%).")     # normalize(): Decimal 10.400 -> 10.4
    return 0


if __name__ == "__main__":
    sys.exit(main())
