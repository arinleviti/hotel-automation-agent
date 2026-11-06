from datetime import date, timedelta

import pytest

from backoffice.services.availability import (
    AlternativeStay,
    AvailabilityStatus,
    NightAvailability,
    check_availability,
    find_alternative_stays,
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


# --- Alternative stays -------------------------------------------------------------


def make_nights(first: date, last: date, rooms_booked: int = 80) -> dict[date, NightAvailability]:
    """Helper: every night from `first` to `last` (inclusive) with the same number booked."""
    nights = {}
    current = first
    while current <= last:
        nights[current] = NightAvailability(rooms_total=120, rooms_booked=rooms_booked)
        current += timedelta(days=1)
    return nights


def test_email_5_suggests_the_three_closest_free_stays():
    # Like the real data: only Dec 30 and Dec 31 are full.
    nights = make_nights(date(2026, 12, 20), date(2027, 1, 10))
    nights[date(2026, 12, 30)] = NightAvailability(rooms_total=120, rooms_booked=120)
    nights[date(2026, 12, 31)] = NightAvailability(rooms_total=120, rooms_booked=120)

    suggestions = find_alternative_stays(
        date(2026, 12, 30), date(2027, 1, 1), nights, today=date(2026, 11, 3)
    )

    # -1 (Dec 29-31) and +1 (Dec 31-Jan 2) touch a full night and are skipped.
    assert suggestions == [
        AlternativeStay(date(2026, 12, 28), date(2026, 12, 30)),
        AlternativeStay(date(2027, 1, 1), date(2027, 1, 3)),
        AlternativeStay(date(2026, 12, 27), date(2026, 12, 29)),
    ]


def test_alternatives_keep_the_same_length_of_stay():
    nights = make_nights(date(2027, 2, 1), date(2027, 2, 28))
    nights[date(2027, 2, 14)] = NightAvailability(rooms_total=120, rooms_booked=120)

    suggestions = find_alternative_stays(
        date(2027, 2, 12), date(2027, 2, 16), nights, today=date(2026, 11, 3)
    )

    assert suggestions
    for stay in suggestions:
        assert (stay.check_out - stay.check_in).days == 4


def test_no_alternative_found_returns_empty_list():
    # Every night in the ±7-day window is full.
    nights = make_nights(date(2026, 12, 20), date(2027, 1, 10), rooms_booked=120)

    suggestions = find_alternative_stays(
        date(2026, 12, 30), date(2027, 1, 1), nights, today=date(2026, 11, 3)
    )

    assert suggestions == []


def test_never_suggests_a_stay_starting_before_today():
    nights = make_nights(date(2026, 10, 25), date(2026, 11, 20))
    nights[date(2026, 11, 3)] = NightAvailability(rooms_total=120, rooms_booked=120)

    suggestions = find_alternative_stays(
        date(2026, 11, 3), date(2026, 11, 5), nights, today=date(2026, 11, 3)
    )

    # -1 (Nov 2) and -2 (Nov 1) would be in the past; only later stays are offered.
    assert suggestions == [
        AlternativeStay(date(2026, 11, 4), date(2026, 11, 6)),
        AlternativeStay(date(2026, 11, 5), date(2026, 11, 7)),
        AlternativeStay(date(2026, 11, 6), date(2026, 11, 8)),
    ]


def test_candidates_with_missing_nights_are_skipped():
    # Data only up to Dec 31: later candidates have missing nights and must not be offered.
    nights = make_nights(date(2026, 12, 20), date(2026, 12, 31))
    nights[date(2026, 12, 30)] = NightAvailability(rooms_total=120, rooms_booked=120)

    suggestions = find_alternative_stays(
        date(2026, 12, 30), date(2027, 1, 1), nights, today=date(2026, 11, 3)
    )

    assert AlternativeStay(date(2027, 1, 1), date(2027, 1, 3)) not in suggestions
    assert suggestions == [
        AlternativeStay(date(2026, 12, 28), date(2026, 12, 30)),
        AlternativeStay(date(2026, 12, 27), date(2026, 12, 29)),
        AlternativeStay(date(2026, 12, 26), date(2026, 12, 28)),
    ]


def test_alternatives_reject_bad_dates():
    with pytest.raises(ValueError):
        find_alternative_stays(date(2026, 12, 30), date(2026, 12, 30), {}, today=date(2026, 11, 3))
