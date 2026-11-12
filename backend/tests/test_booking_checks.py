"""Tests for the booking branch's code nodes (graph/branches/booking/checks.py).

No database: the nodes' two loading functions are swapped (pytest monkeypatch) for versions that
read the REAL data/availability.csv and room rates straight from the files, so the demo emails'
expected outcomes are checked against the real data.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

import backoffice.graph.branches.booking.checks as checks
from backoffice.db.seed import DATA_DIR, parse_availability, parse_room_rates, read_csv
from backoffice.graph.state import ParsedEmail
from backoffice.services.availability import AlternativeStay, AvailabilityStatus
from backoffice.services.booking_request import BookingRequest

ALL_NIGHTS = parse_availability(read_csv(DATA_DIR / "availability.csv")).nights   # Nov 1, 2026 - Mar 31, 2027
RATES = parse_room_rates(read_csv(DATA_DIR / "room_rates.csv"))


@pytest.fixture(autouse=True)
def data_from_the_csv_files(monkeypatch):
    """autouse=True: pytest applies this to every test in the file without being asked."""
    monkeypatch.setattr(checks, "nights_between",
                        lambda start, end: {d: n for d, n in ALL_NIGHTS.items() if start <= d < end})
    monkeypatch.setattr(checks, "current_room_rates", lambda: RATES)


def state_for(check_in: date, check_out: date, adults: int, children: int, written: date) -> dict:
    """A state as it is after extract_request, for a complete request."""
    email = ParsedEmail(sender="Guest <g@mail.example>", to="info@overlook-hotel.example", subject="Room",
                        date=datetime(written.year, written.month, written.day, 9, 0, tzinfo=timezone.utc), body="...")
    request = BookingRequest(check_in=check_in, check_out=check_out, adults=adults, children=children,
                             guest_name="Guest")
    return {"email": email, "booking_request": request}


SARAH = state_for(date(2026, 12, 18), date(2026, 12, 21), adults=2, children=1, written=date(2026, 11, 2))   # #3
PRIYA = state_for(date(2026, 12, 30), date(2027, 1, 1), adults=2, children=0, written=date(2026, 11, 3))    # #5


def test_email_3_is_available_and_costs_1440_72():
    state = {**SARAH, **checks.check_availability(SARAH)}
    assert state["availability_result"].status == AvailabilityStatus.AVAILABLE
    assert checks.after_availability(state) == "price_stay"

    price = checks.price_stay(state)["stay_price"]

    assert (price.nights, price.subtotal, price.tax, price.total_price) == \
           (3, Decimal("1305.00"), Decimal("135.72"), Decimal("1440.72"))


def test_email_5_is_full_and_gets_the_three_closest_alternatives():
    state = {**PRIYA, **checks.check_availability(PRIYA)}
    result = state["availability_result"]
    assert result.status == AvailabilityStatus.FULL
    assert result.full_nights == [date(2026, 12, 30), date(2026, 12, 31)]
    assert checks.after_availability(state) == "find_alternatives"

    stays = checks.find_alternatives(state)["alternative_stays"]

    assert stays == [AlternativeStay(date(2026, 12, 28), date(2026, 12, 30)),
                     AlternativeStay(date(2027, 1, 1), date(2027, 1, 3)),
                     AlternativeStay(date(2026, 12, 27), date(2026, 12, 29))]


def test_dates_outside_the_data_go_to_no_data():
    july = state_for(date(2027, 7, 10), date(2027, 7, 14), adults=2, children=0, written=date(2026, 11, 3))

    state = {**july, **checks.check_availability(july)}

    assert state["availability_result"].status == AvailabilityStatus.NO_DATA
    assert checks.after_availability(state) == "no_data_reply"


def test_alternatives_never_start_before_the_email_was_written():
    # Asked on Dec 29 for Dec 30 - Jan 1: Dec 28-30 and Dec 27-29 would start in the past.
    late = state_for(date(2026, 12, 30), date(2027, 1, 1), adults=2, children=0, written=date(2026, 12, 29))

    stays = checks.find_alternatives(late)["alternative_stays"]

    assert all(stay.check_in >= date(2026, 12, 29) for stay in stays)
    assert AlternativeStay(date(2026, 12, 28), date(2026, 12, 30)) not in stays


def test_after_extract_routes_on_completeness():
    assert checks.after_extract(SARAH) == "check_availability"
    tom = {"booking_request": BookingRequest(check_in=date(2027, 2, 12), check_out=date(2027, 2, 15), adults=2,
                                             children=None, guest_name="Tom", missing=["how many children ..."])}
    assert checks.after_extract(tom) == "ask_for_missing_info"
