"""Review a whole invoice: which supplier, every line checked, the totals, and ONE outcome (step 11).

Built on the step-4 checks in invoice_check.py (check_invoice_line, check_invoice_totals), which
stay unchanged. This module adds what a whole invoice needs on top of single lines:

    find_supplier   which supplier's agreed prices apply (a name lookup, no LLM)
    review_invoice  every line checked + the model's own doubts + the totals -> InvoiceReview
                    with ONE outcome the graph routes on:

        outcome             when                                                  what follows (11.3)
        ALL_OK              every line ✓ and the totals add up                      "OK to pay" -> accounts
        CORRECTION_NEEDED   any ✗: a wrong price, wrong line math or wrong totals    "please correct" -> supplier
        NEEDS_CHECK         no ✗ but some ⚠: unclear, not in contract, unreadable,  "please check" -> accounts
                            or totals not printed
        UNKNOWN_SUPPLIER    no agreed prices for this supplier                       "unknown supplier" -> accounts

Like every service: no database, no LLM; the data comes in as arguments.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import re                                      # regular expressions: here, to squeeze repeated spaces
from dataclasses import dataclass, field       # @dataclass: a class that just holds fields
from decimal import Decimal                    # exact money amounts
from enum import StrEnum                       # a closed list of named text values

# OURS (step 4, unchanged):
from backoffice.services.invoice_check import (InvoiceLine, LineCheck, LineVerdict, SupplierPrice, TotalsCheck,
                                               check_invoice_line, check_invoice_totals)


class InvoiceOutcome(StrEnum):
    ALL_OK = "all_ok"
    CORRECTION_NEEDED = "correction_needed"
    NEEDS_CHECK = "needs_check"
    UNKNOWN_SUPPLIER = "unknown_supplier"


@dataclass
class CheckedLine:
    """
    One invoice line with its verdict.

    Example (#1, mozzarella):
        CheckedLine(line=InvoiceLine(code="FRP-1021", description="Mozz. LM WM, 6x5 lb", quantity=Decimal("30"),
                                     unit="LB", unit_price=Decimal("4.60"), line_total=Decimal("138.00")),
                    check=LineCheck(verdict=LineVerdict.MISMATCH, reason="Price 4.60/LB, contract 4.25/lb",
                                    matched=SupplierPrice(... "FRP-1021" ... Decimal("4.25")),
                                    overcharge=Decimal("10.50")))
    """

    line: InvoiceLine
    check: LineCheck


@dataclass
class InvoiceReview:
    """
    The whole invoice, reviewed.

    Example (#2, Summit Linen & Laundry):
        InvoiceReview(supplier="Summit Linen & Laundry", outcome=InvoiceOutcome.ALL_OK,
                      lines=[CheckedLine(... SLL-01 ... OK), ... 5 lines ...],
                      unreadable_lines=[], totals=TotalsCheck(verdict=LineVerdict.OK, reason="Lines, subtotal, ..."),
                      total_due=Decimal("1795.50"), total_overcharge=Decimal("0.00"))
    """

    supplier: str | None                       # None = no agreed prices for this supplier
    outcome: InvoiceOutcome
    lines: list[CheckedLine] = field(default_factory=list)
    unreadable_lines: list[str] = field(default_factory=list)   # lines code couldn't turn into numbers, with why
    totals: TotalsCheck | None = None          # None when subtotal or total isn't printed
    total_due: Decimal | None = None           # the invoice's printed total
    total_overcharge: Decimal = Decimal("0.00")  # sum of the lines' overcharges


def normalize_name(text: str) -> str:
    """
    Lowercase, "&amp;" -> "&" (an HTML escape Docling leaves in PDF text), single spaces.
        "Summit Linen &amp; Laundry" -> "summit linen & laundry"
    re.sub(r"\\s+", " ", text) (plain Python, regular expressions) = replace every run of spaces,
    tabs or line breaks with one space.
    """
    return re.sub(r"\s+", " ", text.replace("&amp;", "&")).strip().lower()


def find_supplier(known_suppliers: list[str], name_on_invoice: str, sender: str, invoice_text: str) -> str | None:
    """
    Which known supplier sent this invoice: a plain name lookup (no LLM), so the wrong contract
    can't be picked by a model's guess.

    Looks first in the name printed on the invoice and the email's From header; then in the whole
    invoice text. Exactly one supplier must match; none or several -> None ("unknown supplier").

    Examples:
        (["Front Range Provisions", "Summit Linen & Laundry", "Peak Clean Supply Co."],
         "Front Range Provisions", "Front Range Provisions <billing@...>", "...") -> "Front Range Provisions"
        (same list, "Summit Linen &amp; Laundry", ...)                               -> "Summit Linen & Laundry"
        (same list, "Rocky Mountain Produce", "orders@rmp.example", "...")           -> None
    """
    for place in (f"{name_on_invoice} {sender}", invoice_text):
        found = [name for name in known_suppliers if normalize_name(name) in normalize_name(place)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return None                     # two suppliers named: ambiguous, a person decides
    return None


def review_invoice(
    supplier: str,
    lines: list[InvoiceLine],
    doubts: list[str | None],
    unreadable_lines: list[str],
    subtotal: Decimal | None,
    tax: Decimal | None,
    total: Decimal | None,
    prices: list[SupplierPrice],
) -> InvoiceReview:
    """
    Check every line and the totals, and decide the outcome.

    doubts: for each line (same order as `lines`), what the MODEL said it wasn't sure about
            (its status unclear/missing + reason), or None. A line the model doubted is never ✓:
            if the price check passes, it becomes ⚠ with the model's reason.

    Expected on the demo invoices (CLAUDE.md, email table):
      #1 FRP-INV-2026-1184: mozzarella ✗ (overcharge 10.50), eggs ⚠ (no item number), others ✓, totals ✓
         -> CORRECTION_NEEDED (a ✗ beats a ⚠), total_overcharge 10.50
      #2 SLL-10442: all 5 lines ✓, totals ✓ -> ALL_OK, total_due 1795.50
    """
    checked: list[CheckedLine] = []
    for line, doubt in zip(lines, doubts):
        # zip (plain Python) walks two lists side by side: (line 1, doubt 1), (line 2, doubt 2), ...
        check = check_invoice_line(supplier, line, prices)
        if doubt and check.verdict == LineVerdict.OK:
            check = LineCheck(verdict=LineVerdict.UNCLEAR, reason=f"Read with doubt: {doubt}",
                              matched=check.matched, overcharge=check.overcharge)
        checked.append(CheckedLine(line=line, check=check))

    # The totals are checked only when every line could be read: with a line missing from `lines`,
    # the sum would be wrong and look like the SUPPLIER's mistake.
    totals = None
    if subtotal is not None and total is not None and not unreadable_lines:
        totals = check_invoice_totals(lines, subtotal, tax, total)

    verdicts = [c.check.verdict for c in checked]
    if LineVerdict.MISMATCH in verdicts or (totals is not None and totals.verdict == LineVerdict.MISMATCH):
        outcome = InvoiceOutcome.CORRECTION_NEEDED
    elif (LineVerdict.UNCLEAR in verdicts or LineVerdict.NOT_IN_CONTRACT in verdicts
          or unreadable_lines or totals is None or not checked):
        outcome = InvoiceOutcome.NEEDS_CHECK
    else:
        outcome = InvoiceOutcome.ALL_OK

    return InvoiceReview(
        supplier=supplier,
        outcome=outcome,
        lines=checked,
        unreadable_lines=unreadable_lines,
        totals=totals,
        total_due=total,
        total_overcharge=sum((c.check.overcharge for c in checked), Decimal("0.00")),
    )
