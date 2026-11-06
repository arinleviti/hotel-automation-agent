from decimal import Decimal

import pytest

from backoffice.services.invoice_check import (
    InvoiceLine,
    LineVerdict,
    SupplierPrice,
    check_invoice_line,
    find_by_code,
    find_by_description,
    normalize_unit,
)

FRP = "Front Range Provisions"
SLL = "Summit Linen & Laundry"

# A small copy of data/supplier_prices.csv: the "database" for these tests.
PRICES = [
    SupplierPrice(FRP, "FRP-1021", "Mozzarella, low-moisture whole milk", "lb", Decimal("4.25")),
    SupplierPrice(FRP, "FRP-1034", "Butter, unsalted", "lb", Decimal("4.10")),
    SupplierPrice(FRP, "FRP-2002", "Eggs, large grade A", "dozen", Decimal("3.10")),
    SupplierPrice(FRP, "FRP-3110", "All-purpose flour", "50 lb bag", Decimal("24.00")),
    SupplierPrice(FRP, "FRP-4405", "Coffee beans, house roast", "5 lb bag", Decimal("47.50")),
    SupplierPrice(SLL, "SLL-03", "Bath towel, laundered", "per piece", Decimal("0.65")),
]


def line(code, description, quantity, unit, unit_price, line_total) -> InvoiceLine:
    """Helper: build an InvoiceLine from short values (numbers given as strings)."""
    return InvoiceLine(code, description, Decimal(quantity), unit,
                       Decimal(unit_price), Decimal(line_total))


# --- normalize_unit ----------------------------------------------------------------
# parametrize runs the same test once per (input, expected) pair: 8 tests from one function.


@pytest.mark.parametrize(
    "unit, expected",
    [
        ("LB", "lb"),
        ("DZ", "dozen"),
        ("pieces", "piece"),
        ("50 lb bag", "bag"),
        ("per piece", "piece"),
        (" Gallon ", "gallon"),
        ("kg", "kg"),     # unknown unit: returned cleaned, unchanged
        ("", ""),         # empty unit: no crash
    ],
)
def test_normalize_unit(unit, expected):
    assert normalize_unit(unit) == expected


# --- find_by_code / find_by_description --------------------------------------------


def test_find_by_code_finds_the_row():
    assert find_by_code(FRP, "FRP-1021", PRICES).product == "Mozzarella, low-moisture whole milk"


def test_find_by_code_ignores_case_and_spaces():
    assert find_by_code(FRP, " frp-1021 ", PRICES) is not None


def test_find_by_code_only_looks_at_that_supplier():
    assert find_by_code(SLL, "FRP-1021", PRICES) is None


def test_find_by_description_matches_most_shared_words():
    assert find_by_description(FRP, "Eggs large Gr.A 15 dz case", PRICES).code == "FRP-2002"


def test_find_by_description_with_no_shared_word_is_none():
    assert find_by_description(FRP, "Truffle oil", PRICES) is None


# --- check_invoice_line: the demo invoices -------------------------------------------


def test_email_1_mozzarella_wrong_price_is_mismatch_with_overcharge():
    result = check_invoice_line(FRP, line("FRP-1021", "Mozz. LM WM, 6x5 lb", "30", "LB", "4.60", "138.00"), PRICES)

    assert result.verdict == LineVerdict.MISMATCH
    assert result.overcharge == Decimal("10.50")
    assert result.matched.code == "FRP-1021"


def test_email_1_butter_correct_line_is_ok():
    result = check_invoice_line(FRP, line("FRP-1034", "Butter unsalted 36x1 lb", "20", "LB", "4.10", "82.00"), PRICES)

    assert result.verdict == LineVerdict.OK
    assert result.overcharge == Decimal("0.00")


def test_email_1_eggs_without_code_is_unclear_even_if_price_is_right():
    result = check_invoice_line(FRP, line(None, "Eggs large Gr.A 15 dz case", "15", "DZ", "3.10", "46.50"), PRICES)

    assert result.verdict == LineVerdict.UNCLEAR
    assert result.matched.code == "FRP-2002"
    assert "description" in result.reason


def test_email_1_flour_bag_matches_50_lb_bag_unit():
    result = check_invoice_line(FRP, line("FRP-3110", "AP flour 50#", "2", "BAG", "24.00", "48.00"), PRICES)

    assert result.verdict == LineVerdict.OK


def test_email_2_linen_line_in_pieces_is_ok():
    result = check_invoice_line(SLL, line("SLL-03", "Bath towel", "720", "piece", "0.65", "468.00"), PRICES)

    assert result.verdict == LineVerdict.OK


# --- check_invoice_line: other cases ------------------------------------------------


def test_wrong_line_total_is_mismatch():
    # 20 x 4.10 = 82.00, but the invoice says 80.00
    result = check_invoice_line(FRP, line("FRP-1034", "Butter", "20", "LB", "4.10", "80.00"), PRICES)

    assert result.verdict == LineVerdict.MISMATCH
    assert "math" in result.reason


def test_different_unit_is_unclear():
    # Price looks right, but kg can't be compared with the agreed price per lb
    result = check_invoice_line(FRP, line("FRP-1021", "Mozzarella", "30", "KG", "4.25", "127.50"), PRICES)

    assert result.verdict == LineVerdict.UNCLEAR


def test_unknown_product_is_not_in_contract():
    result = check_invoice_line(FRP, line(None, "Truffle oil", "1", "bottle", "30.00", "30.00"), PRICES)

    assert result.verdict == LineVerdict.NOT_IN_CONTRACT
    assert result.matched is None


def test_unknown_code_falls_back_to_description_and_is_unclear():
    # e.g. the LLM misread the code: the description still finds the product, but only ⚠
    result = check_invoice_line(FRP, line("FRP-9999", "Butter unsalted", "20", "LB", "4.10", "82.00"), PRICES)

    assert result.verdict == LineVerdict.UNCLEAR
    assert result.matched.code == "FRP-1034"
