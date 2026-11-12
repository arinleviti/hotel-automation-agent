"""Invoice branch, the REPLY nodes: fixed text templates filled by code (step 11.3). No LLM here.

Same rule as booking (decided 2026-11-11, money involved): every WORD is fixed text in a file in
data/reply_templates/; every amount, code and name is put in by code from the InvoiceReview (11.2).
How a template is filled: see graph/branches/templates.py.

    outcome (11.2)        node                   template                          goes to          kind
    ALL_OK                ok_to_pay_note         invoice_ok_to_pay.txt             accounts         ok_to_pay          #2
    CORRECTION_NEEDED     correction_request     invoice_correction_request.txt    the supplier     reply_to_sender    #1
    NEEDS_CHECK           needs_check_note       invoice_needs_check.txt           accounts         forward_to_staff
    UNKNOWN_SUPPLIER      unknown_supplier_note  invoice_unknown_supplier.txt      accounts         forward_to_staff

The correction request lists ONLY the supplier's errors (✗ lines, wrong totals). A ⚠ line (e.g.
#1's eggs: no item number, price correct) is not the supplier's mistake: the approver sees it in
the evidence (11.4), the supplier doesn't.

Run (from backend/; Postgres running; one Haiku call per email for the extraction):
    uv run python -m backoffice.graph.branches.invoice.replies 01_invoice_front_range_provisions 02_invoice_summit_linen
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import sys                                     # sys.argv: the words typed on the command line
from decimal import Decimal                    # exact money amounts

# OURS:
from backoffice.graph.branches.invoice.extract import parse_amount
from backoffice.graph.branches.templates import bullet_list, format_money, render, reply_subject
from backoffice.graph.state import DraftKind, EmailState, OutgoingDraft
from backoffice.services.invoice_check import LineVerdict
from backoffice.services.invoice_review import CheckedLine, InvoiceReview

# Who receives internal notes about invoices.
ACCOUNTS = "Accounts <accounts@overlook-hotel.example>"

# How each verdict is shown in the line table.
SYMBOL = {LineVerdict.OK: "✓", LineVerdict.UNCLEAR: "⚠", LineVerdict.NOT_IN_CONTRACT: "⚠", LineVerdict.MISMATCH: "✗"}


# --- Formatting: code turns the review into text ----------------------------------------------------

def format_quantity(quantity: Decimal) -> str:
    """Decimal("30") -> "30";  Decimal("2.50") -> "2.5"   (no ".00" on counts)"""
    return format(quantity.normalize(), "f")


def format_line(checked: CheckedLine) -> str:
    """
    One row of the line table, with its ✓/⚠/✗ and, if not ✓, the reason.
        "  ✓ FRP-1034  Butter unsalted 36x1 lb             20 LB x $4.10 = $82.00"
        "  ⚠ (no code) Eggs large Gr.A 15 dz case          15 DZ x $3.10 = $46.50   No item number, matched by ..."
    """
    line, check = checked.line, checked.check
    row = (f"  {SYMBOL[check.verdict]} {line.code or '(no code)':<9} {line.description:<34} "
           f"{format_quantity(line.quantity)} {line.unit} x {format_money(line.unit_price)} = {format_money(line.line_total)}")
    if check.verdict != LineVerdict.OK:
        row += f"   {check.reason}"
    return row


def line_table(review: InvoiceReview) -> str:
    """All rows, one per line, then any line code couldn't read."""
    rows = [format_line(checked) for checked in review.lines]
    rows += [f"  ⚠ unreadable: {problem}" for problem in review.unreadable_lines]
    return "\n".join(rows)


def describe_problem(checked: CheckedLine) -> str:
    """
    A ✗ line, in words for the SUPPLIER (from the numbers, not from the internal reason text).

    Wrong price (#1):
        "FRP-1021 Mozz. LM WM, 6x5 lb: invoiced at $4.60 per LB, our agreed price is $4.25 per lb.
         On 30 LB, that is $10.50 more than agreed."
    Wrong line math:
        "FRP-1034 Butter unsalted 36x1 lb: 20 x $4.10 = $82.00, but the line shows $92.00."
    """
    line, check = checked.line, checked.check
    name = f"{line.code + ' ' if line.code else ''}{line.description}"
    expected_total = line.quantity * line.unit_price
    if expected_total.quantize(Decimal("0.01")) != line.line_total.quantize(Decimal("0.01")):
        return (f"{name}: {format_quantity(line.quantity)} x {format_money(line.unit_price)} = "
                f"{format_money(expected_total)}, but the line shows {format_money(line.line_total)}.")
    agreed = check.matched
    more_or_less = "more" if check.overcharge > 0 else "less"
    return (f"{name}: invoiced at {format_money(line.unit_price)} per {line.unit}, our agreed price is "
            f"{format_money(agreed.price)} per {agreed.unit}. On {format_quantity(line.quantity)} {line.unit}, "
            f"that is {format_money(abs(check.overcharge))} {more_or_less} than agreed.")


def header_values(state: EmailState) -> dict[str, str]:
    """
    The invoice header, as text, for every template.
    Shape (#2): {"supplier": "Summit Linen & Laundry", "invoice_number": "SLL-10442",
                 "invoice_date": "November 1, 2026", "total_due": "$1,795.50"}
    """
    extraction, review = state["invoice_extraction"], state["invoice_review"]
    return {
        "supplier": review.supplier or extraction.supplier_name,
        "invoice_number": extraction.invoice_number or "(no number printed)",
        "invoice_date": extraction.invoice_date or "(no date printed)",
        "total_due": format_money(review.total_due) if review.total_due is not None else "(not printed)",
    }


def internal_note(subject: str, body: str, kind: DraftKind, reason: str) -> dict:
    """A note to Accounts (not to the supplier)."""
    return {"outgoing_draft": OutgoingDraft(kind=kind, outgoing_to=ACCOUNTS, outgoing_subject=subject,
                                            outgoing_body=body, reason=reason)}


# --- The nodes ----------------------------------------------------------------------------------

def ok_to_pay_note(state: EmailState) -> dict:
    """
    NODE (ALL_OK): tell Accounts the invoice can be paid.  (#2)
        to: Accounts   subject: "OK to pay: Summit Linen & Laundry invoice SLL-10442 ($1,795.50)"
    """
    review = state["invoice_review"]
    values = header_values(state) | {"line_count": str(len(review.lines)), "line_table": line_table(review)}
    # dict | dict (plain Python, 3.9+) = one dict with the keys of both.
    return internal_note(
        subject=f"OK to pay: {values['supplier']} invoice {values['invoice_number']} ({values['total_due']})",
        body=render("invoice_ok_to_pay", values),
        kind=DraftKind.OK_TO_PAY,
        reason=f"All {len(review.lines)} lines match the agreed prices; totals add up.",
    )


def correction_request(state: EmailState) -> dict:
    """
    NODE (CORRECTION_NEEDED): ask the supplier for a corrected invoice, listing only their errors. (#1)
        to: the supplier (reply)   "... - FRP-1021 Mozz. LM WM, 6x5 lb: invoiced at $4.60 per LB, ..."
    """
    email, review = state["email"], state["invoice_review"]
    problems = [describe_problem(c) for c in review.lines if c.check.verdict == LineVerdict.MISMATCH]
    if review.totals is not None and review.totals.verdict == LineVerdict.MISMATCH:
        problems.append(f"Totals: {review.totals.reason}.")
    text = bullet_list(problems)
    if review.total_overcharge > 0:
        text += f"\n\nIn total, the invoice is {format_money(review.total_overcharge)} higher than our agreed prices."
    body = render("invoice_correction_request", header_values(state) | {"problems": text})
    return {"outgoing_draft": OutgoingDraft(
        kind=DraftKind.REPLY_TO_SENDER,
        outgoing_to=email.sender,
        outgoing_subject=reply_subject(email.subject),
        outgoing_body=body,
        reason=f"{len(problems)} problem(s) found in code; overcharge {format_money(review.total_overcharge)}.",
    )}


def needs_check_note(state: EmailState) -> dict:
    """NODE (NEEDS_CHECK): no ✗ but some ⚠: ask Accounts to check those lines by hand."""
    review = state["invoice_review"]
    to_check = [format_line(c) for c in review.lines if c.check.verdict != LineVerdict.OK]
    to_check += [f"  ⚠ unreadable: {problem}" for problem in review.unreadable_lines]
    if review.totals is None:
        to_check.append("  ⚠ totals not checked (subtotal or total not printed, or a line couldn't be read)")
    values = header_values(state) | {"to_check": "\n".join(to_check), "line_table": line_table(review)}
    return internal_note(
        subject=f"Please check: {values['supplier']} invoice {values['invoice_number']}",
        body=render("invoice_needs_check", values),
        kind=DraftKind.FORWARD_TO_STAFF,
        reason=f"{len(to_check)} item(s) need a person; no price or total error found.",
    )


def unknown_supplier_note(state: EmailState) -> dict:
    """NODE (UNKNOWN_SUPPLIER): no agreed prices for this supplier: Accounts checks it by hand."""
    email, extraction, review = state["email"], state["invoice_extraction"], state["invoice_review"]
    values = header_values(state) | {"sender": email.sender, "supplier_name": extraction.supplier_name,
                                     "original_subject": email.subject}
    return internal_note(
        subject=f"Unknown supplier: {email.subject}",
        body=render("invoice_unknown_supplier", values),
        kind=DraftKind.FORWARD_TO_STAFF,
        reason=f"No agreed prices for '{extraction.supplier_name}': the invoice can't be checked automatically.",
    )


def invoice_evidence(state: EmailState) -> dict:
    """
    For the approval screen (step 11.4): what the model READ and what code CHECKED, as text, so the
    staff member sees every ✓/⚠/✗ with its reason before approving. Used by nodes/approval.py.

    Shape returned (#1):
        {"supplier": "Front Range Provisions (agreed prices found)",
         "invoice": "FRP-INV-2026-1184, dated 10/30/2026, amount due $504.50",
         "lines": ["  ✗ FRP-1021  Mozz. LM WM, 6x5 lb   30 LB x $4.60 = $138.00   Price 4.60/LB, contract 4.25/lb",
                   "  ✓ FRP-1034  Butter unsalted 36x1 lb   20 LB x $4.10 = $82.00",
                   "  ⚠ (no code) Eggs large Gr.A 15 dz case   15 DZ x $3.10 = $46.50   No item number, ...", ...],
         "totals": "Lines, subtotal, tax and total add up",
         "outcome": "correction_needed"}
    """
    review = state["invoice_review"]
    values = header_values(state)
    if review.supplier:
        supplier = f"{review.supplier} (agreed prices found)"
    else:
        supplier = f"{state['invoice_extraction'].supplier_name} (NO agreed prices on file)"
    return {
        "supplier": supplier,
        "invoice": f"{values['invoice_number']}, dated {values['invoice_date']}, amount due {values['total_due']}",
        "lines": line_table(review).splitlines(),
        "totals": review.totals.reason if review.totals else "not checked",
        "outcome": str(review.outcome),
    }


# Command line (plain Python; see main_graph.py for `if __name__ == "__main__":` and sys.argv):
# run the whole invoice branch by hand (extract -> check -> reply) and print the reply.
if __name__ == "__main__":
    from backoffice.graph.branches.invoice.checks import after_check, check_invoice
    from backoffice.graph.branches.invoice.extract import extract_invoice
    from backoffice.graph.main_graph import email_path_for
    from backoffice.graph.nodes.read_email import parse_eml
    from backoffice.tracing import flush_traces

    REPLY_FOR = {"ok_to_pay_note": ok_to_pay_note, "correction_request": correction_request,
                 "needs_check_note": needs_check_note, "unknown_supplier_note": unknown_supplier_note}

    for name in sys.argv[1:] or ["01_invoice_front_range_provisions"]:
        state: dict = {"email": parse_eml(email_path_for(name))}
        state.update(extract_invoice(state))
        state.update(check_invoice(state))
        reply = after_check(state)
        state.update(REPLY_FOR[reply](state))
        draft = state["outgoing_draft"]
        print(f"=================== {name}  ->  {reply}")
        print(f"kind    : {draft.kind}")
        print(f"to      : {draft.outgoing_to}")
        print(f"subject : {draft.outgoing_subject}")
        print(f"reason  : {draft.reason}")
        print(f"\n{draft.outgoing_body}")
    flush_traces()
