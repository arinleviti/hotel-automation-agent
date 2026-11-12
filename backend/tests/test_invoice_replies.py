"""Tests for the invoice reply nodes (graph/branches/invoice/replies.py) and the invoice templates.

No LLM, no database: the reviews are made by the real review_invoice service on hand-made lines,
with the real supplier prices from data/supplier_prices.csv.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal
from string import Template

import backoffice.graph.branches.invoice.replies as replies
from backoffice.db.seed import DATA_DIR, parse_supplier_prices, read_csv
from backoffice.graph.branches.templates import TEMPLATES_DIR
from backoffice.graph.state import DraftKind, InvoiceExtraction, ParsedEmail
from backoffice.services.invoice_check import InvoiceLine
from backoffice.services.invoice_review import InvoiceOutcome, InvoiceReview, review_invoice

PRICES = parse_supplier_prices(read_csv(DATA_DIR / "supplier_prices.csv"))
FRP = [p for p in PRICES if p.supplier == "Front Range Provisions"]


def line(code, description, quantity, unit, unit_price, line_total) -> InvoiceLine:
    return InvoiceLine(code, description, Decimal(quantity), unit, Decimal(unit_price), Decimal(line_total))


INVOICE_1 = [
    line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.60", "138.00"),
    line("FRP-1034", "Butter unsalted 36x1 lb", "20", "LB", "4.10", "82.00"),
    line(None, "Eggs large Gr.A 15 dz case", "15", "DZ", "3.10", "46.50"),
    line("FRP-3110", "AP flour 50#", "2", "BAG", "24.00", "48.00"),
    line("FRP-4405", "Coffee whole bean house roast 5#", "4", "BAG", "47.50", "190.00"),
]


def state_for(review: InvoiceReview, sender="Front Range Provisions <billing@frontrangeprovisions.example>") -> dict:
    email = ParsedEmail(sender=sender, to="info@overlook-hotel.example",
                        subject="Invoice FRP-INV-2026-1184 - The Overlook Hotel",
                        date=datetime(2026, 10, 30, tzinfo=timezone.utc), body="Please find attached ...")
    extraction = InvoiceExtraction(supplier_name="Front Range Provisions", invoice_number="FRP-INV-2026-1184",
                                   invoice_date="10/30/2026", lines=[], subtotal="504.50", tax="0.00", total="$504.50")
    return {"email": email, "invoice_extraction": extraction, "invoice_review": review}


def review_1(lines=INVOICE_1, doubts=None, subtotal="504.50", total="504.50") -> InvoiceReview:
    return review_invoice("Front Range Provisions", lines, doubts or [None] * len(lines), [],
                          Decimal(subtotal), Decimal("0.00"), Decimal(total), FRP)


# --- The demo emails ------------------------------------------------------------------------------

def test_email_1_asks_the_supplier_to_correct_only_the_mozzarella():
    draft = replies.correction_request(state_for(review_1()))["outgoing_draft"]

    assert draft.kind == DraftKind.REPLY_TO_SENDER
    assert draft.outgoing_to.endswith("<billing@frontrangeprovisions.example>")
    body = draft.outgoing_body
    assert ("  - FRP-1021 Mozz. LM WM, 6x5 lb: invoiced at $4.60 per LB, our agreed price is $4.25 per lb. "
            "On 30 LB, that is $10.50 more than agreed.") in body
    assert "In total, the invoice is $10.50 higher than our agreed prices." in body
    assert "Eggs" not in body                      # ⚠ is for the approver, not the supplier's problem


def test_all_lines_ok_is_an_ok_to_pay_note_to_accounts():
    fixed = [line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.25", "127.50")] + INVOICE_1[1:2] + INVOICE_1[3:]
    review = review_1(lines=fixed, subtotal="447.50", total="447.50")
    assert review.outcome == InvoiceOutcome.ALL_OK

    draft = replies.ok_to_pay_note(state_for(review))["outgoing_draft"]

    assert draft.kind == DraftKind.OK_TO_PAY
    assert draft.outgoing_to == replies.ACCOUNTS
    assert draft.outgoing_subject == "OK to pay: Front Range Provisions invoice FRP-INV-2026-1184 ($447.50)"
    assert "All 4 lines match" in draft.outgoing_body
    butter = next(row for row in draft.outgoing_body.splitlines() if "FRP-1034" in row)
    assert butter.strip().startswith("✓ FRP-1034") and butter.endswith("20 LB x $4.10 = $82.00")


def test_a_line_math_error_is_described_with_the_numbers():
    wrong = [line("FRP-1034", "Butter unsalted 36x1 lb", "20", "LB", "4.10", "92.00")]
    review = review_1(lines=wrong, subtotal="92.00", total="92.00")

    body = replies.correction_request(state_for(review))["outgoing_draft"].outgoing_body

    assert "FRP-1034 Butter unsalted 36x1 lb: 20 x $4.10 = $82.00, but the line shows $92.00." in body


def test_needs_check_lists_the_doubtful_lines_for_accounts():
    fixed = [line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.25", "127.50")] + INVOICE_1[1:]
    review = review_1(lines=fixed, subtotal="494.00", total="494.00")
    assert review.outcome == InvoiceOutcome.NEEDS_CHECK          # only the eggs ⚠

    draft = replies.needs_check_note(state_for(review))["outgoing_draft"]

    assert draft.kind == DraftKind.FORWARD_TO_STAFF and draft.outgoing_to == replies.ACCOUNTS
    to_check = draft.outgoing_body.split("To check:")[1].split("All lines:")[0]
    assert "Eggs large Gr.A" in to_check and "Butter" not in to_check


def test_unknown_supplier_goes_to_accounts():
    review = InvoiceReview(supplier=None, outcome=InvoiceOutcome.UNKNOWN_SUPPLIER, total_due=Decimal("88.00"))

    draft = replies.unknown_supplier_note(state_for(review, sender="orders@rmp.example"))["outgoing_draft"]

    assert draft.outgoing_to == replies.ACCOUNTS
    assert "orders@rmp.example" in draft.outgoing_body and "$88.00" in draft.outgoing_body


# --- The template files ---------------------------------------------------------------------------

def test_every_invoice_template_is_fully_filled():
    for path in sorted(TEMPLATES_DIR.glob("invoice_*.txt")):
        text = path.read_text(encoding="utf-8")
        names = set(re.findall(r"\$(\w+)", text))
        filled = Template(text).substitute({name: "X" for name in names})
        assert not re.search(r"\$\w", filled), path.name
