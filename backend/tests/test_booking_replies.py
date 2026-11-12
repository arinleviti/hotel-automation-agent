"""Tests for the booking reply nodes (graph/branches/booking/replies.py) and the template files.

No LLM, no database: states are built by hand with the values 10.2 and 10.3 produce for the demo
emails, and the room rates are read from data/room_rates.csv.
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from string import Template

import pytest

import backoffice.graph.branches.booking.replies as replies
from backoffice.db.seed import DATA_DIR, parse_room_rates, read_csv
from backoffice.graph.branches.human_review import FRONT_DESK
from backoffice.graph.state import DraftKind, ParsedEmail
from backoffice.services.availability import AlternativeStay, AvailabilityResult, AvailabilityStatus
from backoffice.services.booking_request import BookingRequest
from backoffice.services.pricing import StayPrice

RATES = parse_room_rates(read_csv(DATA_DIR / "room_rates.csv"))


@pytest.fixture(autouse=True)
def rates_from_the_csv(monkeypatch):
    monkeypatch.setattr(replies, "current_room_rates", lambda: RATES)


def email(sender: str, subject: str) -> ParsedEmail:
    return ParsedEmail(sender=sender, to="info@overlook-hotel.example", subject=subject,
                       date=datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc), body="(the guest's text)")


SARAH = {   # #3 after 10.2 and 10.3
    "email": email("Sarah Mitchell <s.mitchell@mail.example>", "Room availability December 18-21"),
    "booking_request": BookingRequest(date(2026, 12, 18), date(2026, 12, 21), adults=2, children=1,
                                      guest_name="Sarah Mitchell"),
    "availability_result": AvailabilityResult(status=AvailabilityStatus.AVAILABLE),
    "stay_price": StayPrice(nights=3, subtotal=Decimal("1305.00"), tax=Decimal("135.72"),
                            total_price=Decimal("1440.72")),
}
TOM = {     # #4 after 10.2
    "email": email("Tom Becker <tom.b@mail.example>", "presidents day weekend"),
    "booking_request": BookingRequest(date(2027, 2, 12), date(2027, 2, 15), adults=2, children=None, guest_name="Tom",
                                      missing=["how many children are travelling",
                                               "the age of each child (children under 13 pay the child rate)"]),
}
PRIYA = {   # #5 after 10.2 and 10.3
    "email": email("Priya Patel <priya.patel@mail.example>", "New Year's Eve at The Overlook"),
    "booking_request": BookingRequest(date(2026, 12, 30), date(2027, 1, 1), adults=2, children=0,
                                      guest_name="Priya Patel"),
    "availability_result": AvailabilityResult(status=AvailabilityStatus.FULL,
                                              full_nights=[date(2026, 12, 30), date(2026, 12, 31)]),
    "alternative_stays": [AlternativeStay(date(2026, 12, 28), date(2026, 12, 30)),
                          AlternativeStay(date(2027, 1, 1), date(2027, 1, 3)),
                          AlternativeStay(date(2026, 12, 27), date(2026, 12, 29))],
}


# --- The demo emails ----------------------------------------------------------------------------

def test_email_3_quote_has_every_figure_from_code():
    draft = replies.quote_reply(SARAH)["outgoing_draft"]

    assert draft.kind == DraftKind.REPLY_TO_SENDER
    assert draft.outgoing_to == "Sarah Mitchell <s.mitchell@mail.example>"
    assert draft.outgoing_subject == "Re: Room availability December 18-21"
    body = draft.outgoing_body
    assert body.startswith("Dear Sarah Mitchell,")
    for line in ("Friday, December 18, 2026", "Monday, December 21, 2026 (3 nights)", "2 adults and 1 child",
                 "Mountain View Room", "$1,305.00", "(10.4%)", "$135.72", "$1,440.72"):
        assert line in body


def test_email_4_asks_for_exactly_what_is_missing():
    draft = replies.ask_for_missing_info(TOM)["outgoing_draft"]

    assert draft.outgoing_body.startswith("Dear Tom,")
    assert "  - how many children are travelling\n  - the age of each child (children under 13 pay the child rate)" \
           in draft.outgoing_body
    assert "$" not in draft.outgoing_body                         # no price in a reply that has none


def test_email_5_full_lists_the_three_alternatives_and_no_price():
    draft = replies.full_reply(PRIYA)["outgoing_draft"]

    body = draft.outgoing_body
    assert "(Wednesday, December 30, 2026 to Friday, January 1, 2027)" in body
    assert ("  - Monday, December 28 to Wednesday, December 30, 2026\n"
            "  - Friday, January 1 to Sunday, January 3, 2027\n"
            "  - Sunday, December 27 to Tuesday, December 29, 2026") in body
    assert "$" not in body                                         # "no prices invented"
    assert "December 30, 2026, Thursday, December 31, 2026" in draft.reason


def test_full_without_alternatives_uses_its_own_wording():
    draft = replies.full_reply({**PRIYA, "alternative_stays": []})["outgoing_draft"]
    assert "reservations@overlook-hotel.example" in draft.outgoing_body


def test_no_data_goes_to_the_front_desk_not_the_guest():
    july = {**PRIYA,
            "booking_request": BookingRequest(date(2027, 7, 10), date(2027, 7, 12), adults=2, children=0,
                                              guest_name="Priya Patel"),
            "availability_result": AvailabilityResult(status=AvailabilityStatus.NO_DATA,
                                                      missing_nights=[date(2027, 7, 10), date(2027, 7, 11)])}

    draft = replies.no_data_reply(july)["outgoing_draft"]

    assert draft.kind == DraftKind.FORWARD_TO_STAFF
    assert draft.outgoing_to == FRONT_DESK
    assert "No data for: Saturday, July 10, 2027, Sunday, July 11, 2027" in draft.outgoing_body


# --- The template files ---------------------------------------------------------------------------

def test_every_placeholder_in_every_template_gets_a_value():
    # Whatever a template file asks for, filling it must leave no $placeholder behind.
    for path in sorted(replies.TEMPLATES_DIR.glob("booking_*.txt")):
        names = set(re.findall(r"\$(\w+)", path.read_text(encoding="utf-8")))
        filled = Template(path.read_text(encoding="utf-8")).substitute({name: "X" for name in names})
        assert not re.search(r"\$\w", filled), path.name


def test_a_missing_value_is_an_error_never_a_blank():
    with pytest.raises(KeyError):
        replies.render("booking_ask_missing", {"guest_name": "Tom"})        # no missing_items


# --- Formatting -----------------------------------------------------------------------------------

def test_formatting_helpers():
    assert replies.format_money(Decimal("1440.72")) == "$1,440.72"
    assert replies.format_rate(Decimal("0.104")) == "10.4%"
    assert replies.format_rate(Decimal("0.10")) == "10%"
    assert replies.format_guests(1, 2) == "1 adult and 2 children"
    assert replies.format_guests(2, 0) == "2 adults"
    assert replies.format_nights(1) == "1 night"
    assert replies.reply_subject("RE: Booking confirmation OVR-58213") == "RE: Booking confirmation OVR-58213"
