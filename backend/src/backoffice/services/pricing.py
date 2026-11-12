from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from dataclasses import dataclass

@dataclass
class RoomRates:
    """
    The hotel's room rates: what calculate_stay_price needs besides the stay itself (step 10.1).
    Comes from data/room_rates.csv (loaded into the room_rates table by the seed script), which
    stands for the rates in the hotel's booking system. Same numbers as the printed rate card.

    Example (The Overlook, the only room type in phase 1):
        RoomRates(room_type="Mountain View Room", adult_rate=Decimal("185.00"), child_rate=Decimal("65.00"),
                  child_under_age=13, tax_rate=Decimal("0.104"))
    """
    room_type: str
    adult_rate: Decimal          # per adult, per night
    child_rate: Decimal          # per child, per night
    child_under_age: int         # a guest YOUNGER than this pays the child rate (13: "under 13")
    tax_rate: Decimal            # lodging tax as a decimal: 0.104 = 10.4%


@dataclass
class StayPrice:
    nights: int
    subtotal: Decimal
    tax: Decimal
    total_price: Decimal

def calculate_stay_price(check_in_date: date, check_out_date: date, n_adults: int, n_children: int, adult_rate: Decimal, child_rate: Decimal, tax_rate: Decimal) -> StayPrice:
    """
    Calculate the total price for a stay based on the check-in and check-out dates, number of adults and children,
    adult and child rates, and tax rate.

    :param check_in_date: The check-in date (datetime object)
    :param check_out_date: The check-out date (datetime object)
    :param n_adults: Number of adults
    :param n_children: Number of children
    :param adult_rate: Rate per adult per night
    :param child_rate: Rate per child per night
    :param tax_rate: Tax rate as a decimal (e.g., 0.1 for 10%)
    :return: Total price for the stay including taxes
    """

     # Validate business rules
    if check_out_date <= check_in_date:
        raise ValueError("Check-out date must be after check-in date.")

    if n_adults < 1 or n_children < 0:
        raise ValueError("Invalid number of guests.")

    if not all(
        rate.is_finite() and rate >= 0
        for rate in (adult_rate, child_rate, tax_rate)
    ):
        raise ValueError("Rates and tax must be finite and non-negative.")

    # Calculate number of nights
    num_nights = (check_out_date - check_in_date).days

        # Calculate subtotal
    subtotal = (
        n_adults * adult_rate + n_children * child_rate
    ) * num_nights

    subtotal = subtotal.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Calculate tax
    tax = (subtotal * tax_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Calculate total
    total_price = (subtotal + tax).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return StayPrice(
        nights=num_nights,
        subtotal=subtotal,
        tax=tax,
        total_price=total_price
    )