"""Tests for the booking extraction node (graph/branches/booking/extract.py), with a fake Claude and
fake room rates: no cost, no database."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

import backoffice.graph.branches.booking.extract as extract_module
from backoffice.graph.main_graph import email_path_for
from backoffice.graph.nodes.read_email import parse_eml
from backoffice.graph.state import BookingExtraction
from backoffice.services.pricing import RoomRates

RATES = RoomRates(room_type="Mountain View Room", adult_rate=Decimal("185.00"), child_rate=Decimal("65.00"),
                  child_under_age=13, tax_rate=Decimal("0.104"))

# What Claude would read from Tom's email (#4).
TOM_FORM = BookingExtraction(check_in=date(2027, 2, 12), check_out=date(2027, 2, 15), adults=2, children=None,
                             children_ages=[], guest_name="tom", unclear="Number of children not stated.")


@pytest.fixture
def fake_claude(monkeypatch):
    """Swap the Claude client for one that returns TOM_FORM, and record what it was sent."""
    sent: list[dict] = []

    def parse(**request):
        sent.append(request)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=TOM_FORM,
                               usage=SimpleNamespace(input_tokens=400, output_tokens=80))

    monkeypatch.setattr(extract_module, "anthropic_client", lambda: SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    monkeypatch.setattr(extract_module, "current_room_rates", lambda: RATES)
    return sent


def test_the_node_returns_what_the_llm_read_and_what_code_decided(fake_claude):
    email = parse_eml(email_path_for("04_booking_missing_info"))

    out = extract_module.extract_request({"email": email})

    assert out["booking_extraction"] == TOM_FORM                  # kept exactly as read
    request = out["booking_request"]
    assert not request.is_complete
    assert request.guest_name == "Tom"                            # "tom" is in the email, capitalised
    assert "how many children are travelling" in request.missing


def test_claude_gets_the_email_date_and_the_email_as_data(fake_claude):
    email = parse_eml(email_path_for("04_booking_missing_info"))

    extract_module.extract_request({"email": email})

    prompt = fake_claude[0]["messages"][0]["content"]
    assert prompt.startswith("Email received on: 2026-11-03")     # for the year of "feb 12"
    assert "<email>" in prompt and "me my wife and the kids" in prompt
    assert fake_claude[0]["output_format"] is BookingExtraction
