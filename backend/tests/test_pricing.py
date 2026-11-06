from datetime import date
from decimal import Decimal
import string
from backoffice.services.pricing import calculate_stay_price
import pytest

# pytest It finds files named test_*.py inside tests/. 
# Inside them, it runs every function whose name starts with test_.
#   Inside each test, every assert is a claim. If it’s true, nothing happens. 
# If it’s false, the test fails and pytest shows you both values.
def test_email_3_two_adults_one_child_three_nights():
    # Arrange + act: call the function with the inputs from email #3
    result = calculate_stay_price(
        check_in_date=date(2026, 12, 18),
        check_out_date=date(2026, 12, 21),
        n_adults=2,
        n_children=1,
        adult_rate=Decimal("185"),
        child_rate=Decimal("65"),
        tax_rate=Decimal("0.104"),
    )

    # Assert: each line is one claim about the result
    assert result.nights == 3
    assert result.subtotal == Decimal("1305.00")
    assert result.tax == Decimal("135.72")
    assert result.total_price == Decimal("1440.72")

def test_one_adult_zero_child_one_night():
    # Arrange + act: call the function with the inputs from email #3
    result = calculate_stay_price(
        check_in_date=date(2026, 12, 18),
        check_out_date=date(2026, 12, 19),
        n_adults=1,
        n_children=0,
        adult_rate=Decimal("185"),
        child_rate=Decimal("65"),
        tax_rate=Decimal("0.104"),
    )

    # Assert: each line is one claim about the result
    assert result.nights == 1
    assert result.subtotal == Decimal("185.00")
    assert result.tax == Decimal("19.24")
    assert result.total_price == Decimal("204.24")
       


def test_check_out_on_same_day_is_rejected():
    #Testing that an error is raised works differently. You expect the function to fail, so you wrap the call in pytest.raises:
    with pytest.raises(ValueError):
        calculate_stay_price(
            check_in_date=date(2026, 12, 18),
            check_out_date=date(2026, 12, 18),   # same day: must fail
            n_adults=2,
            n_children=0,
            adult_rate=Decimal("185"),
            child_rate=Decimal("65"),
            tax_rate=Decimal("0.104"),
        )

def test_zero_adults_is_rejected():
    with pytest.raises(ValueError):
        calculate_stay_price(
            check_in_date=date(2026, 12, 18),
            check_out_date=date(2026, 12, 19),
            n_adults=0,   # zero adults: must fail
            n_children=1,
            adult_rate=Decimal("185"),
            child_rate=Decimal("65"),
            tax_rate=Decimal("0.104"),
        )

