"""End-to-end tests of the booking branch INSIDE the real main graph (step 10.5).

Each demo booking email goes: read_email -> classify -> decide_route -> booking_branch (the
subgraph) -> approval (pause) -> resume -> action -> END.

Faked, so no cost and no database:
  - both Claude calls (classify, and the booking extraction) return what Claude reads for that email;
  - the availability and room rates come from the real CSV files;
  - the action node's write goes to fake_actions_table (conftest.py).
"""

from datetime import date
from types import SimpleNamespace

import pytest

import backoffice.graph.branches.booking.checks as checks
import backoffice.graph.branches.booking.extract as extract_module
import backoffice.graph.branches.booking.replies as replies
import backoffice.graph.nodes.classify as classify_module
from backoffice.db.seed import DATA_DIR, parse_availability, parse_room_rates, read_csv
from backoffice.graph.branches.booking.subgraph import build_booking_graph
from backoffice.graph.main_graph import build_graph, process_email, resume_email
from backoffice.graph.state import BookingExtraction, Classification, DraftKind

ALL_NIGHTS = parse_availability(read_csv(DATA_DIR / "availability.csv")).nights
RATES = parse_room_rates(read_csv(DATA_DIR / "room_rates.csv"))

BOOKING = Classification(type="booking", suspicious=False, suspicious_reason="", confidence=0.95,
                         summary="Room request.")

# What Claude reads from each demo booking email (as in the real run of 10.2).
READ_AS = {
    "Room availability December 18-21": BookingExtraction(
        check_in=date(2026, 12, 18), check_out=date(2026, 12, 21), adults=2, children=1, children_ages=[8],
        guest_name="Sarah Mitchell", unclear=""),
    "presidents day weekend": BookingExtraction(
        check_in=date(2027, 2, 12), check_out=date(2027, 2, 15), adults=2, children=None, children_ages=[],
        guest_name="tom", unclear="The email says 'the kids' without a number or ages."),
    "New Year's Eve at The Overlook": BookingExtraction(
        check_in=date(2026, 12, 30), check_out=date(2027, 1, 1), adults=2, children=0, children_ages=[],
        guest_name="Priya Patel", unclear=""),
}


def fake_client(answer_for):
    """A fake Claude client whose messages.parse(**request) returns answer_for(request)."""
    def parse(**request):
        return SimpleNamespace(stop_reason="end_turn", parsed_output=answer_for(request),
                               usage=SimpleNamespace(input_tokens=400, output_tokens=80))
    return SimpleNamespace(messages=SimpleNamespace(parse=parse))


def extraction_for(request):
    """Pick the extraction by the subject line inside the prompt."""
    prompt = request["messages"][0]["content"]
    return next(form for subject, form in READ_AS.items() if f"Subject: {subject}" in prompt)


@pytest.fixture(autouse=True)
def fake_world(monkeypatch, fake_actions_table):
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake_client(lambda request: BOOKING))
    monkeypatch.setattr(extract_module, "anthropic_client", lambda: fake_client(extraction_for))
    monkeypatch.setattr(extract_module, "current_room_rates", lambda: RATES)
    monkeypatch.setattr(checks, "current_room_rates", lambda: RATES)
    monkeypatch.setattr(replies, "current_room_rates", lambda: RATES)
    monkeypatch.setattr(checks, "nights_between",
                        lambda start, end: {d: n for d, n in ALL_NIGHTS.items() if start <= d < end})
    return fake_actions_table


def test_the_subgraph_has_every_booking_node():
    nodes = set(build_booking_graph().get_graph().nodes)
    assert nodes == {"__start__", "extract_request", "check_availability", "price_stay", "find_alternatives",
                     "ask_for_missing_info", "quote_reply", "full_reply", "no_data_reply", "__end__"}


def test_email_3_runs_the_quote_path_and_pauses_with_the_quote():
    result = process_email("03_booking_complete")

    assert result.nodes_run == ["read_email", "classify", "decide_route",
                                "booking_branch > extract_request", "booking_branch > check_availability",
                                "booking_branch > price_stay", "booking_branch > quote_reply"]
    request = result.waiting_for_human
    assert request["evidence"]["read_as"] == "Friday, December 18 to Monday, December 21, 2026; 2 adults and 1 child"
    assert request["outgoing_draft"]["kind"] == "reply_to_sender"
    assert "Total:                $1,440.72" in request["outgoing_draft"]["outgoing_body"]


def test_email_4_runs_the_ask_path():
    result = process_email("04_booking_missing_info")

    assert result.nodes_run[-2:] == ["booking_branch > extract_request", "booking_branch > ask_for_missing_info"]
    evidence = result.waiting_for_human["evidence"]
    assert evidence["read_as"].endswith("2 adults, children not stated")
    assert "how many children are travelling" in evidence["missing"]
    assert result.waiting_for_human["outgoing_draft"]["outgoing_body"].startswith("Dear Tom,")


def test_email_5_runs_the_full_path_with_alternatives():
    result = process_email("05_booking_no_availability")

    assert result.nodes_run[-3:] == ["booking_branch > check_availability", "booking_branch > find_alternatives",
                                     "booking_branch > full_reply"]
    body = result.waiting_for_human["outgoing_draft"]["outgoing_body"]
    assert "  - Monday, December 28 to Wednesday, December 30, 2026" in body


def test_an_approved_quote_is_recorded_as_sent(fake_world):
    graph = build_graph()
    paused = process_email("03_booking_complete", graph)

    resumed = resume_email(paused.thread_id, {"decision": "approve"}, graph)

    assert resumed.nodes_run == ["approval", "action"]
    sent = resumed.state["final_outgoing_message"]
    assert sent.kind == DraftKind.REPLY_TO_SENDER
    assert "$1,440.72" in sent.outgoing_body
    assert fake_world[0]["email_name"] == "03_booking_complete"
    # The booking keys stayed in the main state, for the evals and the UI.
    assert {"booking_extraction", "booking_request", "availability_result", "stay_price"} <= set(resumed.state)
    assert str(resumed.state["stay_price"].total_price) == "1440.72"
