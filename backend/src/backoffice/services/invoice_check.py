"""Check extracted invoice lines against the hotel's agreed supplier prices (code only, no AI)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


@dataclass
class SupplierPrice:
    """One agreed price: one row of data/supplier_prices.csv."""

    supplier: str        # "Front Range Provisions"
    code: str            # "FRP-1021"
    product: str         # "Mozzarella, low-moisture whole milk"
    unit: str            # "lb", "dozen", "50 lb bag", "per piece", ...
    price: Decimal       # Decimal("4.25")


@dataclass
class InvoiceLine:
    """One line as extracted from the invoice (later by the LLM, step 11)."""

    code: str | None     # None when the invoice prints no item number
    description: str     # the supplier's own wording, e.g. "Mozz. LM WM, 6x5 lb"
    quantity: Decimal
    unit: str            # as printed, e.g. "LB", "DZ", "BAG", "piece"
    unit_price: Decimal
    line_total: Decimal


class LineVerdict(StrEnum):
    OK = "ok"                            # ✓ code found, same unit, math right, price matches
    UNCLEAR = "unclear"                  # ⚠ matched by description only, or units differ
    MISMATCH = "mismatch"                # ✗ wrong price or wrong line total
    NOT_IN_CONTRACT = "not_in_contract"  # ✗ no agreed price found for this line


@dataclass
class LineCheck:
    verdict: LineVerdict
    reason: str                          # one sentence for the human, e.g. "Price $4.60/lb, contract $4.25/lb"
    matched: SupplierPrice | None = None # the agreed price used for the comparison, if any
    overcharge: Decimal = Decimal("0.00")  # (invoice price - agreed price) x quantity, 0 if none


# Abbreviations suppliers print -> the unit name used in supplier_prices.csv.
UNIT_ALIASES: dict[str, str] = {
    "lb": "lb", "lbs": "lb", "#": "lb",
    "dz": "dozen", "doz": "dozen", "dozen": "dozen",
    "bag": "bag", "bags": "bag",
    "gal": "gallon", "gallon": "gallon", "gallons": "gallon",
    "cs": "case", "case": "case", "cases": "case",
    "pc": "piece", "pcs": "piece", "ea": "piece", "piece": "piece", "pieces": "piece",
}


def normalize_unit(unit: str) -> str:
    """
    Turn any way of writing a unit into one standard name, so units can be compared.

    Examples:
        "LB" -> "lb"          "DZ" -> "dozen"        "pieces" -> "piece"
        "50 lb bag" -> "bag"  "per piece" -> "piece" "BAG" -> "bag"

    An unknown unit is returned cleaned but unchanged (it simply won't match).
    An empty unit returns "" (it won't match either, so the line becomes UNCLEAR).
    """
    words = unit.strip().lower().split()
    if not words:
        return ""
    last = words[-1]   # keep only the last word: "50 lb bag" -> "bag"
    return UNIT_ALIASES.get(last, last)


def find_by_code(supplier: str, code: str, prices: list[SupplierPrice]) -> SupplierPrice | None:
    """
    Return the agreed price with this exact supplier and code, or None.

    Example: ("Front Range Provisions", "FRP-1021") -> the mozzarella row.
    """
    for agreed_price in prices:
        if agreed_price.supplier == supplier and agreed_price.code.strip().upper() == code.strip().upper():
            return agreed_price
    return None 



def find_by_description(
    supplier: str, description: str, prices: list[SupplierPrice]
) -> SupplierPrice | None:
    """
    Fallback when the line has no code: return this supplier's product whose name shares
    the most words with the description, or None if no word is shared at all.

    Example: "Eggs large Gr.A 15 dz case" -> "Eggs, large grade A"
             (shares "eggs", "large", "a").

    Hint: lowercase, replace punctuation (, . -) with spaces, split into a set of words,
    and count the common words with `len(set_a & set_b)`.
    """
    description = description.strip().lower()
    # Replace punctuation with spaces and split into words
    description_words = set(description.replace(",", " ").replace(".", " ").replace("-", " ").split())
    best_match: SupplierPrice | None = None
    max_common_words = 0

    for agreed_price in prices:
        if agreed_price.supplier == supplier:
            product_description = agreed_price.product.strip().lower()
            product_words = set(product_description.replace(",", " ").replace(".", " ").replace("-", " ").split())
            # len(set_a & set_b) counts the number of words in common between the two sets
            common_words = len(description_words & product_words)
            if common_words > max_common_words:
                max_common_words = common_words
                best_match = agreed_price

    return best_match


def check_invoice_line(supplier: str, line: InvoiceLine, prices: list[SupplierPrice]) -> LineCheck:
    """
    Decide ✓ / ⚠ / ✗ for one invoice line.

    Steps, in order:
      1. Find the agreed price: by code if the line has one; otherwise by description.
         Nothing found -> NOT_IN_CONTRACT.
      2. Units: normalize_unit(line.unit) must equal normalize_unit(agreed.unit);
         if not -> UNCLEAR (prices in different units can't be compared).
      3. Line math: quantity x unit_price must equal line_total; if not -> MISMATCH.
      4. Price: unit_price must equal the agreed price; if not -> MISMATCH, with
         overcharge = (unit_price - agreed price) x quantity, rounded to cents.
      5. All good: OK if it was matched by code; UNCLEAR if only by description
         ("No item number, matched by description; price correct").

    Expected on the demo invoices:
      FRP-1021 mozzarella 30 LB @ 4.60 -> MISMATCH, overcharge 10.50
      FRP-1034 butter, FRP-3110 flour ("BAG" vs "50 lb bag"), FRP-4405 coffee -> OK
      (no code) "Eggs large Gr.A 15 dz case" 15 DZ @ 3.10 -> UNCLEAR
      SLL-01 ... SLL-05 (unit "piece") -> OK
    """
    supplier_price: SupplierPrice | None = None
    matched_by_code = False                                    # fix 3: remember how it was found

    if line.code:
        supplier_price = find_by_code(supplier, line.code, prices)
        if supplier_price:
            matched_by_code = True                             # fix 1: no return here, just remember

    if not supplier_price:                                     # fix 2: outside "if line.code:"
        supplier_price = find_by_description(supplier, line.description, prices)

    if not supplier_price:
        return LineCheck(
            verdict= LineVerdict.NOT_IN_CONTRACT,
            reason= "No agreed price found for this line",
            matched= None,
            overcharge= Decimal("0.00"),
        )
    if normalize_unit(line.unit) != normalize_unit(supplier_price.unit):
        return LineCheck(
            verdict= LineVerdict.UNCLEAR,
            reason= f"Units differ: invoice '{line.unit}' vs contract '{supplier_price.unit}'",
            matched= supplier_price,
            overcharge= Decimal("0.00"),
        )
    if (line.quantity * line.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != line.line_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
        return LineCheck(
            verdict= LineVerdict.MISMATCH,
            reason= f"Line math error: {line.quantity} x {line.unit_price} != {line.line_total}",
            matched= supplier_price,
            overcharge= Decimal("0.00"),
        )
    if line.unit_price != supplier_price.price:
        overcharge = ((line.unit_price - supplier_price.price) * line.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return LineCheck(
            verdict= LineVerdict.MISMATCH,
            reason= f"Price {line.unit_price}/{line.unit}, contract {supplier_price.price}/{supplier_price.unit}",
            matched= supplier_price,
            overcharge= overcharge,
        )

    # Step 5: every check passed. Only a match by code is certain enough for OK.
    if matched_by_code:
        return LineCheck(
            verdict= LineVerdict.OK,
            reason= "Matched by code; price correct",
            matched= supplier_price,
            overcharge= Decimal("0.00"),
        )
    return LineCheck(
        verdict= LineVerdict.UNCLEAR,
        reason= "No item number, matched by description; price correct",
        matched= supplier_price,
        overcharge= Decimal("0.00"),
    )


@dataclass
class TotalsCheck:
    verdict: LineVerdict      # reuse it: OK or MISMATCH
    reason: str
    difference: Decimal = Decimal("0.00")   # printed amount - calculated amount, 0 if it adds up


def check_invoice_totals(
    lines: list[InvoiceLine],
    subtotal: Decimal,
    tax: Decimal | None,      # None when the invoice has no tax line
    total: Decimal,
) -> TotalsCheck:
    """
    Check the invoice's own arithmetic at the bottom of the page.

      1. The line totals must add up to the printed subtotal.
      2. Subtotal + tax must equal the printed total (no tax line = tax 0).

    Only the arithmetic is checked, not whether the tax itself is right (e.g. "exempt").

    Expected on the demo invoices:
      FRP-INV-2026-1184: lines 504.50, subtotal 504.50, tax 0.00, total 504.50 -> OK
      SLL-10442: lines 1795.50, subtotal 1795.50, no tax line, total 1795.50 -> OK
    """
    cents = Decimal("0.01")

    # Check 1: lines -> subtotal
    lines_sum = sum((l.line_total for l in lines), Decimal("0")).quantize(cents, rounding=ROUND_HALF_UP)
    if lines_sum != subtotal:
        return TotalsCheck(
            verdict=LineVerdict.MISMATCH,
            reason=f"Lines add up to {lines_sum}, but the invoice subtotal is {subtotal}",
            difference=(subtotal - lines_sum).quantize(cents, rounding=ROUND_HALF_UP),
        )

    # Check 2: subtotal + tax -> total
    expected_total = (subtotal + (tax or Decimal("0"))).quantize(cents, rounding=ROUND_HALF_UP)
    if expected_total != total:
        return TotalsCheck(
            verdict=LineVerdict.MISMATCH,
            reason=f"Subtotal {subtotal} + tax {tax or Decimal('0.00')} = {expected_total}, "
                   f"but the invoice total is {total}",
            difference=(total - expected_total).quantize(cents, rounding=ROUND_HALF_UP),
        )

    return TotalsCheck(verdict=LineVerdict.OK, reason="Lines, subtotal, tax and total add up")