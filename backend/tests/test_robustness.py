"""Step 13: broken inputs. Whatever fails, the email reaches approval as a note to the front desk,
with the failed step and the error, instead of crashing the run.

Everything is faked (no cost, no database): Claude, the PDF reader, the database loads.
Note: RETRY_ONCE waits 2 s before its retry, so the tests that retry take a couple of seconds.
"""

from types import SimpleNamespace

import psycopg
import pytest
from pydantic import ValidationError

import backoffice.graph.branches.booking.checks as booking_checks
import backoffice.graph.branches.booking.extract as booking_extract
import backoffice.graph.nodes.classify as classify_module
import backoffice.graph.nodes.read_email as read_email_module
from backoffice.graph.main_graph import process_email
from backoffice.graph.state import Classification

BOOKING = Classification(type="booking", suspicious=False, suspicious_reason="", confidence=0.95, summary="Room request.")


def classifier_returning(*outcomes):
    """
    A fake Claude for classify that plays `outcomes` in order: an exception is raised, anything else
    is returned as the form. Returns (fake client, list of calls made).
    """
    calls = []
    plays = iter(outcomes)

    def parse(**request):
        calls.append(request)
        outcome = next(plays)
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(stop_reason="end_turn", parsed_output=outcome,
                               usage=SimpleNamespace(input_tokens=500, output_tokens=60))
    return SimpleNamespace(messages=SimpleNamespace(parse=parse)), calls


def a_validation_error() -> ValidationError:
    """A real Pydantic ValidationError (an answer in the wrong format)."""
    try:
        Classification.model_validate({"type": "booking"})        # required fields missing
    except ValidationError as error:
        return error


def assert_sent_to_a_person(result, failed_step: str) -> None:
    request = result.waiting_for_human
    assert request is not None, "the run must still pause at approval"
    assert request["evidence"]["failed_step"] == failed_step
    assert request["outgoing_draft"]["kind"] == "forward_to_staff"
    assert request["outgoing_draft"]["outgoing_to"].startswith("Front desk")
    assert f"Step:   {failed_step}" in request["outgoing_draft"]["outgoing_body"]


def test_an_unreadable_pdf_goes_to_a_person_with_the_email_kept(monkeypatch):
    # The PDF fails, but the email itself (sender, subject, text) is kept: read_email marks the
    # attachment unreadable, classify still sees an invoice email, and the invoice branch stops at
    # extract_invoice. The note to the front desk then shows who sent it and what they wrote.
    def broken_pdf(filename, data):
        raise RuntimeError("PDF could not be parsed")
    monkeypatch.setattr(read_email_module, "parse_bytes", broken_pdf)
    invoice = Classification(type="invoice", suspicious=False, suspicious_reason="", confidence=0.9,
                             summary="Supplier invoice.")
    fake, _ = classifier_returning(invoice)
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)

    result = process_email("01_invoice_front_range_provisions")

    # A node that FAILS reports no update in the stream, so the failed step itself doesn't show up;
    # its name is in the evidence (failed_step).
    assert result.nodes_run == ["read_email", "classify", "decide_route", "invoice_branch > error_handler"]
    assert_sent_to_a_person(result, "invoice_branch > extract_invoice")
    assert "FRP-INV-2026-1184.pdf could not be read" in result.waiting_for_human["evidence"]["error"]
    body = result.waiting_for_human["outgoing_draft"]["outgoing_body"]
    assert "From: Front Range Provisions <billing@frontrangeprovisions.example>" in body    # the email is kept
    assert result.state["email"].attachments[0].read_error == "RuntimeError: PDF could not be parsed"


def test_an_unreadable_email_file_still_goes_to_a_person(monkeypatch):
    # The .eml file itself can't be read: nothing to keep, read_email fails, straight to approval.
    def broken_file(path):
        raise OSError("disk error")
    monkeypatch.setattr(read_email_module, "parse_eml", broken_file)

    result = process_email("01_invoice_front_range_provisions")

    assert result.nodes_run == ["error_handler"]
    assert_sent_to_a_person(result, "read_email")
    assert result.waiting_for_human["incoming"]["sender"] == "(unreadable email)"


def test_claude_timing_out_twice_goes_to_a_person(monkeypatch):
    fake, calls = classifier_returning(TimeoutError("slow"), TimeoutError("slow again"))
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)

    result = process_email("03_booking_complete")

    assert len(calls) == 2                                           # the first try + ONE retry
    assert_sent_to_a_person(result, "classify")


def test_a_wrong_format_once_is_retried_and_recovers(monkeypatch):
    fake, calls = classifier_returning(a_validation_error(),
                                       Classification(type="other", suspicious=False, suspicious_reason="",
                                                      confidence=0.95, summary="Cancellation."))
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)

    result = process_email("10_other_cancellation")

    assert len(calls) == 2
    assert "processing_error" not in result.state                    # recovered: the normal path
    assert result.state["route"] == "human"


def test_a_refusal_is_not_retried(monkeypatch):
    fake, _ = classifier_returning(BOOKING)
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)
    extract_calls = []

    def refuse(**request):
        extract_calls.append(request)
        return SimpleNamespace(stop_reason="refusal", parsed_output=None,
                               usage=SimpleNamespace(input_tokens=400, output_tokens=0))
    monkeypatch.setattr(booking_extract, "anthropic_client",
                        lambda: SimpleNamespace(messages=SimpleNamespace(parse=refuse)))

    result = process_email("03_booking_complete")

    assert len(extract_calls) == 1                                   # a refusal is not temporary: no retry
    assert_sent_to_a_person(result, "booking_branch > extract_request")


def test_the_database_down_during_the_checks_goes_to_a_person(monkeypatch):
    from datetime import date
    from decimal import Decimal

    from backoffice.graph.state import BookingExtraction
    from backoffice.services.pricing import RoomRates

    fake, _ = classifier_returning(BOOKING)
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)
    form = BookingExtraction(check_in=date(2026, 12, 18), check_out=date(2026, 12, 21), adults=2, children=1,
                             children_ages=[8], guest_name="Sarah Mitchell", unclear="")
    monkeypatch.setattr(booking_extract, "anthropic_client", lambda: SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=form,
                                                usage=SimpleNamespace(input_tokens=400, output_tokens=80)))))
    monkeypatch.setattr(booking_extract, "current_room_rates",
                        lambda: RoomRates("Mountain View Room", Decimal("185.00"), Decimal("65.00"), 13, Decimal("0.104")))
    db_calls = []

    def database_down(start, end):
        db_calls.append((start, end))
        raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(booking_checks, "nights_between", database_down)

    result = process_email("03_booking_complete")

    assert len(db_calls) == 2                                        # temporary: retried once
    assert_sent_to_a_person(result, "booking_branch > check_availability")
    assert "OperationalError: connection refused" in result.waiting_for_human["evidence"]["error"]
