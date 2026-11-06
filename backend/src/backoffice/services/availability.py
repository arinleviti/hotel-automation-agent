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
