from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum


@dataclass
class NightAvailability:
    """Rooms for one night: how many the hotel has and how many are already booked."""

    rooms_total: int
    rooms_booked: int


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"   # every night has at least 1 free room
    FULL = "full"             # at least one night has no free room
    NO_DATA = "no_data"       # no night is full, but some night is missing from the data


@dataclass
class AvailabilityResult:
    status: AvailabilityStatus
    full_nights: list[date] = field(default_factory=list)
    missing_nights: list[date] = field(default_factory=list)


def check_availability(
    check_in: date,
    check_out: date,
    nights: dict[date, NightAvailability],
) -> AvailabilityResult:
    """
    Check whether a stay can be booked.

    :param check_in: The check-in date
    :param check_out: The check-out date (this night is not stayed)
    :param nights: Lookup table: date -> that night's availability
    :return: An AvailabilityResult with the status and the full and missing nights
    """
    # Validate business rules
    if check_out <= check_in:
        raise ValueError("Check-out date must be after check-in date.")

    full_nights: list[date] = []
    missing_nights: list[date] = []

    # Walk through each night of the stay (check-out night excluded)
    current = check_in
    while current < check_out:
        if current not in nights:
            missing_nights.append(current)
        else:
            night = nights[current]
            if night.rooms_total - night.rooms_booked <= 0:   # <= also catches overbooking
                full_nights.append(current)
        current += timedelta(days=1)

    # Priority: a known full night is a certain "no"; missing data is only "can't tell"
    if full_nights:
        status = AvailabilityStatus.FULL
    elif missing_nights:
        status = AvailabilityStatus.NO_DATA
    else:
        status = AvailabilityStatus.AVAILABLE

    return AvailabilityResult(
        status=status,
        full_nights=full_nights,
        missing_nights=missing_nights,
    )


@dataclass
class AlternativeStay:
    check_in: date
    check_out: date


def find_alternative_stays(
    check_in: date,
    check_out: date,
    nights: dict[date, NightAvailability],
    today: date,
    max_shift_days: int = 7,
    max_suggestions: int = 3,
) -> list[AlternativeStay]:
    """
    Suggest stays of the same length close to the requested one, when it can't be booked.

    Candidates start 1 to `max_shift_days` days earlier or later, closest first
    (-1, +1, -2, +2, ...). Each one is checked with `check_availability`; only AVAILABLE
    ones are kept (a candidate with any full or missing night is skipped). Candidates
    starting before `today` are skipped.

    :param check_in: The requested check-in date
    :param check_out: The requested check-out date
    :param nights: Lookup table: date -> that night's availability
    :param today: The current date (passed in so the function is testable)
    :param max_shift_days: How far earlier or later a candidate may start
    :param max_suggestions: Stop after this many suggestions
    :return: Up to `max_suggestions` alternative stays, closest first; empty if none found
    """
    # Validate business rules
    if check_out <= check_in:
        raise ValueError("Check-out date must be after check-in date.")

    length = check_out - check_in
    suggestions: list[AlternativeStay] = []

    for shift in range(1, max_shift_days + 1):
        for direction in (-1, 1):                     # earlier first, then later
            start = check_in + timedelta(days=shift * direction)
            if start < today:
                continue                              # never suggest the past
            end = start + length
            if check_availability(start, end, nights).status == AvailabilityStatus.AVAILABLE:
                suggestions.append(AlternativeStay(check_in=start, check_out=end))
                if len(suggestions) == max_suggestions:
                    return suggestions

    return suggestions
