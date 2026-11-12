"""Tests for the invoice branch nodes (extract.py, checks.py) with a fake Claude and the real
supplier prices from the CSV file: no cost, no database."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

import backoffice.graph.branches.invoice.checks as checks
import backoffice.graph.branches.invoice.extract as extract_module
from backoffice.db.seed import DATA_DIR, parse_supplier_prices, read_csv
from backoffice.graph.main_graph import email_path_for
from backoffice.graph.nodes.read_email import parse_eml
from backoffice.graph.state import ExtractedInvoiceLine, InvoiceExtraction
from backoffice.services.invoice_review import InvoiceOutcome

PRICES = parse_supplier_prices(read_csv(DATA_DIR / "supplier_prices.csv"))


def extracted(code, description, quantity, unit, unit_price, line_total, status="ok", reason=""):
    return ExtractedInvoiceLine(code=code, description=description, quantity=quantity, unit_of_measure=unit,
                                unit_price=unit_price, line_total=line_total, status=status, reason=reason)


# What Claude copies from invoice #2 (as in the real run): amounts as printed, with "$".
INVOICE_2 = InvoiceExtraction(
    supplier_name="Summit Linen &amp; Laundry", invoice_number="SLL-10442", invoice_date="November 1, 2026",
    lines=[extracted("SLL-01", "Queen flat sheet", "480", "piece", "$1.10", "$528.00"),
           extracted("SLL-02", "Pillowcase", "960", "piece", "$0.35", "$336.00"),
           extracted("SLL-03", "Bath towel", "720", "piece", "$0.65", "$468.00"),
           extracted("SLL-04", "Hand towel", "720", "piece", "$0.30", "$216.00"),
           extracted("SLL-05", "Bathrobe", "90", "piece", "$2.75", "$247.50")],
    subtotal="$1,795.50", tax=None, total="$1,795.50")


@pytest.fixture(autouse=True)
def fake_claude_and_prices(monkeypatch):
    sent: list[dict] = []

    def parse(**request):
        sent.append(request)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=INVOICE_2,
                               usage=SimpleNamespace(input_tokens=1500, output_tokens=400))

    monkeypatch.setattr(extract_module, "anthropic_client",
                        lambda: SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    monkeypatch.setattr(checks, "all_supplier_prices", lambda: PRICES)
    return sent


# --- parse_amount / to_invoice_lines ---------------------------------------------------------

def test_printed_amounts_become_exact_decimals():
    assert extract_module.parse_amount("$1,795.50") == Decimal("1795.50")
    assert extract_module.parse_amount("4.60") == Decimal("4.60")
    assert extract_module.parse_amount("two") is None
    assert extract_module.parse_amount(None) is None


def test_a_line_that_isnt_numbers_is_set_aside_with_why():
    form = INVOICE_2.model_copy(update={"lines": [extracted("SLL-01", "Queen flat sheet", "a lot", "piece",
                                                            "$1.10", "$528.00")]})
    lines, doubts, unreadable = extract_module.to_invoice_lines(form)

    assert lines == [] and doubts == []
    assert "Queen flat sheet" in unreadable[0]


# --- The nodes -----------------------------------------------------------------------------------

def test_extract_sends_the_whole_invoice_as_data(fake_claude_and_prices):
    email = parse_eml(email_path_for("02_invoice_summit_linen"))

    out = extract_module.extract_invoice({"email": email})

    assert out["invoice_extraction"] == INVOICE_2
    prompt = fake_claude_and_prices[0]["messages"][0]["content"]
    assert prompt.startswith("<email>") and "SLL-05" in prompt          # the whole table, not a preview


def test_check_invoice_2_is_ok_to_pay():
    email = parse_eml(email_path_for("02_invoice_summit_linen"))
    state = {"email": email, "invoice_extraction": INVOICE_2}

    review = checks.check_invoice(state)["invoice_review"]

    assert review.supplier == "Summit Linen & Laundry"
    assert review.outcome == InvoiceOutcome.ALL_OK
    assert review.total_due == Decimal("1795.50")
    assert checks.after_check({"invoice_review": review}) == "ok_to_pay_note"


def test_an_invoice_from_an_unknown_supplier():
    email = parse_eml(email_path_for("02_invoice_summit_linen"))
    stranger = INVOICE_2.model_copy(update={"supplier_name": "Rocky Mountain Produce"})
    # Another sender and no invoice text, so nothing names a known supplier.
    email.sender, email.attachments = "orders@rmp.example", []

    review = checks.check_invoice({"email": email, "invoice_extraction": stranger})["invoice_review"]

    assert review.outcome == InvoiceOutcome.UNKNOWN_SUPPLIER
    assert checks.after_check({"invoice_review": review}) == "unknown_supplier_note"
