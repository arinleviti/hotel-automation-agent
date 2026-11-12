"""Booking branch, the CODE nodes: availability, price, alternatives (step 10.3). No LLM here.

Each node does one job: load what it needs from Postgres, call ONE service (services/, written and
tested in step 4, unchanged), write ONE key into the state.

    extract_request (10.2)
       │  after_extract (code): is booking_request complete?
       ├─ no  ─────────────────────────────────────────► "ask" reply              (10.4)
       └─ yes → check_availability ──► availability_result
                  │  after_availability (code): which status?
                  ├─ AVAILABLE → price_stay        ──► stay_price       → "quote" reply  (10.4)
                  ├─ FULL      → find_alternatives ──► alternative_stays → "full" reply  (10.4)
                  └─ NO_DATA   ─────────────────────────────────────────► "please handle" (10.4)

The arrows are drawn in 10.5 (the subgraph). The two routing functions are written here so each
decision is tested on its own; like follow_route in main_graph.py, they only READ the state and
return the name of the next node.

Run the checks on demo emails (from backend/; Postgres running; one Haiku call per email for 10.2):
    uv run python -m backoffice.graph.branches.booking.checks 03_booking_complete 05_booking_no_availability
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import sys                                     # sys.argv: the words typed on the command line
from datetime import date, timedelta           # timedelta(days=7): a length of time, to add to a date

# OURS:
from backoffice.db.connection import connect                            # open a Postgres connection
from backoffice.db.queries import load_nights, load_room_rates          # tables -> the services' input types
from backoffice.graph.state import EmailState
from backoffice.services.availability import (AvailabilityStatus, NightAvailability,
                                              check_availability as availability_of_stay,
                                              find_alternative_stays)
from backoffice.services.pricing import RoomRates, calculate_stay_price

# How far around the stay find_alternative_stays looks (its max_shift_days default), so we load
# exactly the nights it may need.
ALTERNATIVES_WINDOW = timedelta(days=7)


# --- Data loading (the only place these nodes touch the database; swapped for fakes in tests) ------

def nights_between(start: date, end: date) -> dict[date, NightAvailability]:
    """
    The nights from `start` (included) to `end` (excluded), from the availability table.

    Shape returned: dict, key = the night's date, value = NightAvailability
        {date(2026, 12, 18): NightAvailability(rooms_total=120, rooms_booked=96),
         date(2026, 12, 19): NightAvailability(rooms_total=120, rooms_booked=88),
         ...}
    """
    with connect() as conn:
        return load_nights(conn, start, end)


def current_room_rates() -> RoomRates:
    """The room rates from the room_rates table (10.1)."""
    with connect() as conn:
        return load_room_rates(conn)


# --- The nodes ----------------------------------------------------------------------------------

def check_availability(state: EmailState) -> dict:
    """
    NODE: is there a free room on every night of the stay?

    In:   state["booking_request"]  (complete: dates and guests known)
    Out:  {"availability_result": AvailabilityResult(...)}

    Examples:
        #3 Sarah, Dec 18-21  -> AvailabilityResult(status=AVAILABLE, full_nights=[], missing_nights=[])
        #5 Priya, Dec 30-Jan 1 -> AvailabilityResult(status=FULL,
                                                     full_nights=[date(2026, 12, 30), date(2026, 12, 31)],
                                                     missing_nights=[])
    """
    request = state["booking_request"]
    nights = nights_between(request.check_in, request.check_out)
    # availability_of_stay = the check_availability SERVICE (services/availability.py), imported
    # under another name so it doesn't clash with this node's name.
    return {"availability_result": availability_of_stay(request.check_in, request.check_out, nights)}


def price_stay(state: EmailState) -> dict:
    """
    NODE: the price of the stay, calculated in code ("the model judges, code calculates").

    In:   state["booking_request"]  (available)
    Out:  {"stay_price": StayPrice(...)}

    Example (#3 Sarah: 3 nights, 2 adults, 1 child):
        3 x (2 x $185 + 1 x $65) = $1,305.00;  tax 10.4% = $135.72;  total $1,440.72
        -> StayPrice(nights=3, subtotal=Decimal("1305.00"), tax=Decimal("135.72"), total_price=Decimal("1440.72"))
    """
    request = state["booking_request"]
    rates = current_room_rates()
    return {"stay_price": calculate_stay_price(
        request.check_in, request.check_out, request.adults, request.children,
        rates.adult_rate, rates.child_rate, rates.tax_rate,
    )}


def find_alternatives(state: EmailState) -> dict:
    """
    NODE: when the dates are full, find up to 3 free stays of the same length nearby (code).

    In:   state["booking_request"]  (full), state["email"] (its date = "today": nothing before it)
    Out:  {"alternative_stays": [AlternativeStay(...), ...]}   (empty list if none found)

    Example (#5 Priya, Dec 30 - Jan 1, 2 nights; tried closest first: -1, +1, -2, +2, -3 ...):
        Dec 29-31 (Dec 30 full, skipped), Dec 31-Jan 2 (Dec 31 full, skipped), then
        -> [AlternativeStay(check_in=date(2026, 12, 28), check_out=date(2026, 12, 30)),
            AlternativeStay(check_in=date(2027, 1, 1),   check_out=date(2027, 1, 3)),
            AlternativeStay(check_in=date(2026, 12, 27), check_out=date(2026, 12, 29))]
    """
    request = state["booking_request"]
    email = state["email"]
    # "today" for this email = the day it was written (decided 2026-11-11), so the result
    # doesn't change with the calendar. No date on the email -> the stay's own check-in date.
    today = email.date.date() if email.date else request.check_in
    nights = nights_between(request.check_in - ALTERNATIVES_WINDOW, request.check_out + ALTERNATIVES_WINDOW)
    return {"alternative_stays": find_alternative_stays(request.check_in, request.check_out, nights, today)}


# --- The routing decisions (code), wired as conditional edges in 10.5 ---------------------------

def after_extract(state: EmailState) -> str:
    """
    After extract_request: complete request -> check availability; otherwise ask the guest.

    Examples: #3, #5 -> "check_availability";  #4 (children not counted) -> "ask_for_missing_info"
    """
    return "check_availability" if state["booking_request"].is_complete else "ask_for_missing_info"


def after_availability(state: EmailState) -> str:
    """
    After check_availability: which way, by status.

    Examples: #3 AVAILABLE -> "price_stay";  #5 FULL -> "find_alternatives";
              a stay in July 2027 (not in the data) NO_DATA -> "no_data_reply"
    """
    status = state["availability_result"].status
    if status == AvailabilityStatus.AVAILABLE:
        return "price_stay"
    if status == AvailabilityStatus.FULL:
        return "find_alternatives"
    return "no_data_reply"


# Command line (plain Python; see main_graph.py for `if __name__ == "__main__":` and sys.argv):
# run extract (10.2) + these checks on demo emails, following the routing by hand, and print.
if __name__ == "__main__":
    from backoffice.graph.branches.booking.extract import extract_request      # ours: 10.2
    from backoffice.graph.main_graph import email_path_for                      # ours: name -> safe path
    from backoffice.graph.nodes.read_email import parse_eml                     # ours: .eml -> ParsedEmail
    from backoffice.tracing import flush_traces

    for name in sys.argv[1:] or ["03_booking_complete"]:
        state: dict = {"email": parse_eml(email_path_for(name))}
        state.update(extract_request(state))
        request = state["booking_request"]
        print(f"=== {name}")
        print(f"request    : {request.check_in} -> {request.check_out}, {request.adults} adults, "
              f"{request.children} children, complete={request.is_complete}")

        if after_extract(state) == "ask_for_missing_info":
            print(f"next       : ask_for_missing_info  {request.missing}")
            continue                                   # plain Python: go on with the next email

        state.update(check_availability(state))
        result = state["availability_result"]
        print(f"availability: {result.status}  full nights={result.full_nights}  missing nights={result.missing_nights}")

        next_node = after_availability(state)
        if next_node == "price_stay":
            state.update(price_stay(state))
            price = state["stay_price"]
            print(f"price      : {price.nights} nights, subtotal ${price.subtotal}, tax ${price.tax}, "
                  f"total ${price.total_price}")
        elif next_node == "find_alternatives":
            state.update(find_alternatives(state))
            stays = [f"{s.check_in} -> {s.check_out}" for s in state["alternative_stays"]]
            print(f"alternatives: {stays}")
        else:
            print("next       : no_data_reply (dates not in the availability data)")
    flush_traces()
