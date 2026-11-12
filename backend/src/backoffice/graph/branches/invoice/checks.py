"""Invoice branch, node 2: check the invoice (CODE only, no LLM), and the routing decision.

In:   state["invoice_extraction"]  what the LLM copied (11.1);  state["email"]  sender + invoice text
Out:  {"invoice_review": InvoiceReview(...)}   supplier, every line ✓/⚠/✗ with its reason, totals, outcome

    1. load ALL agreed prices from Postgres            (db/queries.py, step 5)
    2. which supplier?  find_supplier                  (services/invoice_review.py)
    3. printed text -> exact Decimals                  (extract.py: to_invoice_lines, parse_amount)
    4. every line + totals -> one outcome              (review_invoice, built on YOUR step-4 checks)

Services never touch the database: this node loads the prices and passes them in (the same
pattern as the booking checks).

Run it (from backend/; Postgres running; one Haiku call per email):
    uv run python -m backoffice.graph.branches.invoice.checks 01_invoice_front_range_provisions 02_invoice_summit_linen
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import sys                                     # sys.argv: the words typed on the command line

# OURS:
from backoffice.db.connection import connect                               # open a Postgres connection
from backoffice.db.queries import load_supplier_prices                     # supplier_prices -> list[SupplierPrice]
from backoffice.graph.branches.invoice.extract import parse_amount, to_invoice_lines
from backoffice.graph.state import EmailState
from backoffice.services.invoice_check import SupplierPrice
from backoffice.services.invoice_review import InvoiceOutcome, InvoiceReview, find_supplier, review_invoice


def all_supplier_prices() -> list[SupplierPrice]:
    """
    Every agreed price (all suppliers), from Postgres. Swapped for the CSV in tests.

    Shape returned: list of SupplierPrice, 15 rows
        [SupplierPrice(supplier="Front Range Provisions", code="FRP-1021",
                       product="Mozzarella, low-moisture whole milk", unit="lb", price=Decimal("4.25")),
         ...]
    """
    with connect() as conn:
        return load_supplier_prices(conn)


def check_invoice(state: EmailState) -> dict:
    """
    THE NODE: find the supplier, check every line and the totals, decide the outcome.

    Examples:
        #1 -> InvoiceReview(supplier="Front Range Provisions", outcome=CORRECTION_NEEDED,
                            lines=[mozzarella ✗ overcharge 10.50, butter ✓, eggs ⚠, flour ✓, coffee ✓],
                            totals=OK, total_due=Decimal("504.50"), total_overcharge=Decimal("10.50"))
        #2 -> InvoiceReview(supplier="Summit Linen & Laundry", outcome=ALL_OK, ... total_due=Decimal("1795.50"))
    """
    extraction = state["invoice_extraction"]
    email = state["email"]
    prices = all_supplier_prices()

    # {p.supplier for p in prices} (plain Python) = a SET: each supplier name once.
    known_suppliers = sorted({p.supplier for p in prices})
    invoice_text = "\n".join(attachment.markdown for attachment in email.attachments)
    supplier = find_supplier(known_suppliers, extraction.supplier_name, email.sender, invoice_text)

    if supplier is None:
        return {"invoice_review": InvoiceReview(supplier=None, outcome=InvoiceOutcome.UNKNOWN_SUPPLIER,
                                                total_due=parse_amount(extraction.total))}

    lines, doubts, unreadable = to_invoice_lines(extraction)
    review = review_invoice(
        supplier=supplier,
        lines=lines,
        doubts=doubts,
        unreadable_lines=unreadable,
        subtotal=parse_amount(extraction.subtotal),
        tax=parse_amount(extraction.tax),
        total=parse_amount(extraction.total),
        prices=[p for p in prices if p.supplier == supplier],     # only this supplier's agreed prices
    )
    return {"invoice_review": review}


# The name of the reply node for each outcome (the reply nodes are written in 11.3).
REPLY_FOR_OUTCOME = {
    InvoiceOutcome.ALL_OK: "ok_to_pay_note",
    InvoiceOutcome.CORRECTION_NEEDED: "correction_request",
    InvoiceOutcome.NEEDS_CHECK: "needs_check_note",
    InvoiceOutcome.UNKNOWN_SUPPLIER: "unknown_supplier_note",
}


def after_check(state: EmailState) -> str:
    """
    The routing decision after check_invoice (code; wired as a conditional edge in 11.4).
    Examples: #1 CORRECTION_NEEDED -> "correction_request";  #2 ALL_OK -> "ok_to_pay_note"
    """
    return REPLY_FOR_OUTCOME[state["invoice_review"].outcome]


# Command line (plain Python; see main_graph.py for `if __name__ == "__main__":` and sys.argv).
if __name__ == "__main__":
    from backoffice.graph.branches.invoice.extract import extract_invoice
    from backoffice.graph.main_graph import email_path_for
    from backoffice.graph.nodes.read_email import parse_eml
    from backoffice.tracing import flush_traces

    SYMBOL = {"ok": "✓", "unclear": "⚠", "not_in_contract": "⚠", "mismatch": "✗"}

    for name in sys.argv[1:] or ["01_invoice_front_range_provisions"]:
        state: dict = {"email": parse_eml(email_path_for(name))}
        state.update(extract_invoice(state))
        state.update(check_invoice(state))
        review = state["invoice_review"]
        print(f"=== {name}: supplier={review.supplier}  outcome={review.outcome}  -> {after_check(state)}")
        for checked in review.lines:
            line, check = checked.line, checked.check
            print(f"  {SYMBOL[check.verdict]} {line.code or '(no code)':<9} {line.description:<34}"
                  f" {check.reason}" + (f"  overcharge ${check.overcharge}" if check.overcharge else ""))
        for problem in review.unreadable_lines:
            print(f"  ⚠ unreadable: {problem}")
        print(f"  totals: {review.totals.reason if review.totals else 'not checked'}   "
              f"total due ${review.total_due}   overcharge ${review.total_overcharge}")
    flush_traces()
