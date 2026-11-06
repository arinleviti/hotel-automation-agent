from datetime import date

import pytest

from backoffice.services.availability import (
    AvailabilityStatus,
    NightAvailability,
    check_availability,
)

# Nights taken from data/availability.csv, so the tests mirror the demo emails.
# Each test builds only the nights it needs: the dictionary is the "database" for that test.


def test_email_3_all_nights_have_free_rooms_is_available():
    nights = {
        date(2026, 12, 18): NightAvailability(rooms_total=120, rooms_booked=96),
        date(2026, 12, 19): NightAvailability(rooms_total=120, rooms_booked=88),
        date(2026, 12, 20): NightAvailability(rooms_total=120, rooms_booked=79),
    }

    result = check_availability(date(2026, 12, 18), date(2026, 12, 21), nights)

    assert result.status == AvailabilityStatus.AVAILABLE
    assert result.full_nights == []
    assert result.missing_nights == []


def test_email_5_fully_booked_nights_are_full_and_listed():
    nights = {
        date(2026, 12, 30): NightAvailability(rooms_total=120, rooms_booked=120),
        date(2026, 12, 31): NightAvailability(rooms_total=120, rooms_booked=120),
    }

    result = check_availability(date(2026, 12, 30), date(2027, 1, 1), nights)

    assert result.status == AvailabilityStatus.FULL
    assert result.full_nights == [date(2026, 12, 30), date(2026, 12, 31)]


def test_one_full_night_among_free_ones_makes_the_stay_full():
    nights = {
        date(2026, 12, 29): NightAvailability(rooms_total=120, rooms_booked=102),
        date(2026, 12, 30): NightAvailability(rooms_total=120, rooms_booked=120),
    }

    result = check_availability(date(2026, 12, 29), date(2026, 12, 31), nights)

    assert result.status == AvailabilityStatus.FULL
    assert result.full_nights == [date(2026, 12, 30)]


def test_missing_night_is_no_data_and_listed():
    nights = {
        date(2026, 12, 18): NightAvailability(rooms_total=120, rooms_booked=96),
        # Dec 19 is missing
        date(2026, 12, 20): NightAvailability(rooms_total=120, rooms_booked=79),
    }

    result = check_availability(date(2026, 12, 18), date(2026, 12, 21), nights)

    assert result.status == AvailabilityStatus.NO_DATA
    assert result.missing_nights == [date(2026, 12, 19)]


def test_full_night_wins_over_missing_night():
    # A known full night is a certain "no", even if another night has no data.
    nights = {
        date(2026, 12, 18): NightAvailability(rooms_total=120, rooms_booked=120),
        # Dec 19 is missing
    }

    result = check_availability(date(2026, 12, 18), date(2026, 12, 20), nights)

    assert result.status == AvailabilityStatus.FULL
    assert result.full_nights == [date(2026, 12, 18)]
    assert result.missing_nights == [date(2026, 12, 19)]


def test_overbooked_night_counts_as_full():
    nights = {
        date(2026, 12, 18): NightAvailability(rooms_total=120, rooms_booked=122),
    }

    result = check_availability(date(2026, 12, 18), date(2026, 12, 19), nights)

    assert result.status == AvailabilityStatus.FULL


def test_check_out_date_is_not_a_stayed_night():
    # Only Dec 18 is stayed; Dec 19 (check-out) is full but must not matter.
    nights = {
        date(2026, 12, 18): NightAvailability(rooms_total=120, rooms_booked=96),
        date(2026, 12, 19): NightAvailability(rooms_total=120, rooms_booked=120),
    }

    result = check_availability(date(2026, 12, 18), date(2026, 12, 19), nights)

    assert result.status == AvailabilityStatus.AVAILABLE


def test_check_out_on_same_day_is_rejected():
    with pytest.raises(ValueError):
        check_availability(date(2026, 12, 18), date(2026, 12, 18), {})
