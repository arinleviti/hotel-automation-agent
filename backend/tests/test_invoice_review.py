"""Tests for services/invoice_review.py (find_supplier, review_invoice): pure code, the real
supplier prices read from data/supplier_prices.csv, no database, no LLM."""

from decimal import Decimal

from backoffice.db.seed import DATA_DIR, parse_supplier_prices, read_csv
from backoffice.services.invoice_check import InvoiceLine, LineVerdict
from backoffice.services.invoice_review import InvoiceOutcome, find_supplier, review_invoice

PRICES = parse_supplier_prices(read_csv(DATA_DIR / "supplier_prices.csv"))
SUPPLIERS = sorted({p.supplier for p in PRICES})
FRP = [p for p in PRICES if p.supplier == "Front Range Provisions"]


def line(code, description, quantity, unit, unit_price, line_total) -> InvoiceLine:
    return InvoiceLine(code, description, Decimal(quantity), unit, Decimal(unit_price), Decimal(line_total))


# The 5 lines of invoice #1 (FRP-INV-2026-1184), as code gets them from the extraction.
INVOICE_1 = [
    line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.60", "138.00"),
    line("FRP-1034", "Butter unsalted 36x1 lb", "20", "LB", "4.10", "82.00"),
    line(None, "Eggs large Gr.A 15 dz case", "15", "DZ", "3.10", "46.50"),
    line("FRP-3110", "AP flour 50#", "2", "BAG", "24.00", "48.00"),
    line("FRP-4405", "Coffee whole bean house roast 5#", "4", "BAG", "47.50", "190.00"),
]
NO_DOUBTS = [None] * 5


def review_1(**overrides):
    values = dict(supplier="Front Range Provisions", lines=INVOICE_1, doubts=NO_DOUBTS, unreadable_lines=[],
                  subtotal=Decimal("504.50"), tax=Decimal("0.00"), total=Decimal("504.50"), prices=FRP)
    values.update(overrides)
    return review_invoice(**values)


# --- find_supplier ----------------------------------------------------------------------------

def test_the_supplier_is_found_by_its_printed_name():
    assert find_supplier(SUPPLIERS, "Front Range Provisions", "billing@frontrangeprovisions.example", "") \
           == "Front Range Provisions"


def test_the_html_escape_in_the_pdf_text_still_matches():
    assert find_supplier(SUPPLIERS, "Summit Linen &amp; Laundry", "accounts@summitlinen.example", "") \
           == "Summit Linen & Laundry"


def test_an_unknown_or_ambiguous_supplier_gives_none():
    assert find_supplier(SUPPLIERS, "Rocky Mountain Produce", "orders@rmp.example", "...") is None
    assert find_supplier(SUPPLIERS, "Front Range Provisions and Summit Linen & Laundry", "", "") is None


# --- review_invoice ---------------------------------------------------------------------------

def test_invoice_1_needs_a_correction_for_the_mozzarella():
    review = review_1()

    assert review.outcome == InvoiceOutcome.CORRECTION_NEEDED
    verdicts = [c.check.verdict for c in review.lines]
    assert verdicts == [LineVerdict.MISMATCH, LineVerdict.OK, LineVerdict.UNCLEAR, LineVerdict.OK, LineVerdict.OK]
    assert review.total_overcharge == Decimal("10.50")
    assert review.totals.verdict == LineVerdict.OK


def test_all_lines_right_is_ok_to_pay():
    fixed = [line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.25", "127.50")] + INVOICE_1[1:2] + INVOICE_1[3:]
    review = review_1(lines=fixed, doubts=[None] * 4, subtotal=Decimal("447.50"), total=Decimal("447.50"))

    assert review.outcome == InvoiceOutcome.ALL_OK


def test_a_line_the_model_doubted_is_never_ok():
    doubts = [None, "Quantity hard to read.", None, None, None]
    fixed = [line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.25", "127.50")] + INVOICE_1[1:]
    review = review_1(lines=fixed, doubts=doubts, subtotal=Decimal("494.00"), total=Decimal("494.00"))

    assert review.lines[1].check.verdict == LineVerdict.UNCLEAR
    assert "Quantity hard to read." in review.lines[1].check.reason
    assert review.outcome == InvoiceOutcome.NEEDS_CHECK          # ⚠ but no ✗: accounts checks it


def test_wrong_totals_need_a_correction():
    assert review_1(total=Decimal("514.50")).totals.verdict == LineVerdict.MISMATCH


def test_unreadable_lines_skip_the_totals_and_need_a_check():
    # With a line missing, the sum would be wrong and look like the supplier's mistake: not checked.
    fixed = [line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.25", "127.50")] + INVOICE_1[1:2]
    review = review_1(lines=fixed, doubts=[None, None], unreadable_lines=["Eggs ...: can't be read"])

    assert review.totals is None
    assert review.outcome == InvoiceOutcome.NEEDS_CHECK


def test_totals_not_printed_need_a_check():
    fixed = [line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.25", "127.50")]
    assert review_1(lines=fixed, doubts=[None], total=None).outcome == InvoiceOutcome.NEEDS_CHECK
