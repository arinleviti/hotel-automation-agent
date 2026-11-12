"""End-to-end tests of the invoice branch INSIDE the real main graph (step 11.4).

Each demo invoice email goes: read_email -> classify -> decide_route -> invoice_branch (the
subgraph) -> approval (pause) -> resume -> action -> END.

Faked, so no cost and no database: both Claude calls (classify, invoice extraction), the supplier
prices (from the real CSV file), and the action node's write (fake_actions_table, conftest.py).
"""

from types import SimpleNamespace

import pytest

import backoffice.graph.branches.invoice.checks as checks
import backoffice.graph.branches.invoice.extract as extract_module
import backoffice.graph.nodes.classify as classify_module
from backoffice.db.seed import DATA_DIR, parse_supplier_prices, read_csv
from backoffice.graph.branches.invoice.subgraph import build_invoice_graph
from backoffice.graph.main_graph import build_graph, process_email, resume_email
from backoffice.graph.state import Classification, DraftKind, ExtractedInvoiceLine, InvoiceExtraction

PRICES = parse_supplier_prices(read_csv(DATA_DIR / "supplier_prices.csv"))
INVOICE = Classification(type="invoice", suspicious=False, suspicious_reason="", confidence=0.97,
                         summary="Supplier invoice.")


def extracted(code, description, quantity, unit, unit_price, line_total, status="ok", reason=""):
    return ExtractedInvoiceLine(code=code, description=description, quantity=quantity, unit_of_measure=unit,
                                unit_price=unit_price, line_total=line_total, status=status, reason=reason)


# What Claude copies from each demo invoice (as in the real run of 11.1).
READ_AS = {
    "FRP-INV-2026-1184": InvoiceExtraction(
        supplier_name="Front Range Provisions", invoice_number="FRP-INV-2026-1184", invoice_date="10/30/2026",
        lines=[extracted("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.60", "138.00"),
               extracted("FRP-1034", "Butter unsalted 36x1 lb", "20", "LB", "4.10", "82.00"),
               extracted(None, "Eggs large Gr.A 15 dz case", "15", "DZ", "3.10", "46.50", "missing",
                         "No item number printed."),
               extracted("FRP-3110", "AP flour 50#", "2", "BAG", "24.00", "48.00"),
               extracted("FRP-4405", "Coffee whole bean house roast 5#", "4", "BAG", "47.50", "190.00")],
        subtotal="504.50", tax="0.00", total="$504.50"),
    "SLL-10442": InvoiceExtraction(
        supplier_name="Summit Linen &amp; Laundry", invoice_number="SLL-10442", invoice_date="November 1, 2026",
        lines=[extracted("SLL-01", "Queen flat sheet", "480", "piece", "$1.10", "$528.00"),
               extracted("SLL-02", "Pillowcase", "960", "piece", "$0.35", "$336.00"),
               extracted("SLL-03", "Bath towel", "720", "piece", "$0.65", "$468.00"),
               extracted("SLL-04", "Hand towel", "720", "piece", "$0.30", "$216.00"),
               extracted("SLL-05", "Bathrobe", "90", "piece", "$2.75", "$247.50")],
        subtotal="$1,795.50", tax=None, total="$1,795.50"),
}


def fake_client(answer_for):
    def parse(**request):
        return SimpleNamespace(stop_reason="end_turn", parsed_output=answer_for(request),
                               usage=SimpleNamespace(input_tokens=1500, output_tokens=400))
    return SimpleNamespace(messages=SimpleNamespace(parse=parse))


def extraction_for(request):
    """Pick the extraction by the invoice number inside the prompt."""
    prompt = request["messages"][0]["content"]
    return next(form for number, form in READ_AS.items() if number in prompt)


@pytest.fixture(autouse=True)
def fake_world(monkeypatch, fake_actions_table):
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake_client(lambda request: INVOICE))
    monkeypatch.setattr(extract_module, "anthropic_client", lambda: fake_client(extraction_for))
    monkeypatch.setattr(checks, "all_supplier_prices", lambda: PRICES)
    return fake_actions_table


def test_the_subgraph_has_every_invoice_node():
    nodes = set(build_invoice_graph().get_graph().nodes)
    assert nodes == {"__start__", "extract_invoice", "check_invoice", "ok_to_pay_note", "correction_request",
                     "needs_check_note", "unknown_supplier_note", "__end__",
                     "__default_error_handler__"}    # step 13: the subgraph's error handler


def test_email_1_runs_the_correction_path_with_evidence():
    result = process_email("01_invoice_front_range_provisions")

    assert result.nodes_run == ["read_email", "classify", "decide_route",
                                "invoice_branch > extract_invoice", "invoice_branch > check_invoice",
                                "invoice_branch > correction_request"]
    request = result.waiting_for_human
    evidence = request["evidence"]
    assert evidence["supplier"] == "Front Range Provisions (agreed prices found)"
    assert evidence["outcome"] == "correction_needed"
    assert any(row.strip().startswith("✗ FRP-1021") for row in evidence["lines"])
    assert any(row.strip().startswith("⚠ (no code) Eggs") for row in evidence["lines"])
    assert request["outgoing_draft"]["kind"] == "reply_to_sender"
    assert "$10.50 more than agreed" in request["outgoing_draft"]["outgoing_body"]


def test_email_2_is_ok_to_pay_and_approved_is_recorded(fake_world):
    graph = build_graph()
    paused = process_email("02_invoice_summit_linen", graph)
    assert paused.nodes_run[-1] == "invoice_branch > ok_to_pay_note"
    assert paused.waiting_for_human["outgoing_draft"]["kind"] == "ok_to_pay"

    resumed = resume_email(paused.thread_id, {"decision": "approve"}, graph)

    sent = resumed.state["final_outgoing_message"]
    assert sent.kind == DraftKind.OK_TO_PAY
    assert sent.outgoing_subject == "OK to pay: Summit Linen & Laundry invoice SLL-10442 ($1,795.50)"
    assert fake_world[0]["email_name"] == "02_invoice_summit_linen"
