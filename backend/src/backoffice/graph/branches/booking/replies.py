"""Booking branch, the REPLY nodes: fixed text templates filled by code (step 10.4). No LLM here.

Decided 2026-11-11: no LLM writes any booking reply. Every WORD is fixed text in a file in
data/reply_templates/; every NUMBER, DATE and NAME is put in by code. So a reply can't leave out
the tax, round a price, or invent a date.

    which reply (decided in code, 10.3)      template file                          goes to
    ask_for_missing_info  (#4 Tom)           booking_ask_missing.txt                the guest
    quote_reply           (#3 Sarah)         booking_quote.txt                      the guest
    full_reply            (#5 Priya)         booking_full_alternatives.txt          the guest
                                             booking_full_no_alternatives.txt       the guest
    no_data_reply         (dates not in data) booking_no_data.txt                   the front desk

Each node returns {"outgoing_draft": OutgoingDraft(...)}; approval and action (step 9) do the rest.

=================================================================================================
HOW A TEMPLATE IS FILLED: string.Template (plain Python)
=================================================================================================
A template file has $placeholders:          Dear $guest_name, ... Total: $total
Template(text).substitute(values) replaces each $name with values["name"]:
    values = {"guest_name": "Sarah Mitchell", "total": "$1,440.72", ...}
    ->  Dear Sarah Mitchell, ... Total: $1,440.72
substitute (not safe_substitute): a $placeholder with no value RAISES an error, so a guest can never
receive "Dear $guest_name" or a blank total. The dollar signs of prices come from code, inside the
VALUE ("$1,440.72"); a literal $ written in a template file would have to be $$.

Run (from backend/; Postgres running; one Haiku call per email for the extraction):
    uv run python -m backoffice.graph.branches.booking.replies 03_booking_complete 04_booking_missing_info 05_booking_no_availability
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import sys                                     # sys.argv: the words typed on the command line
from datetime import date                      # a calendar date
from decimal import Decimal                    # exact money amounts

# OURS:
from backoffice.graph.branches.booking.checks import current_room_rates   # the room_rates row (10.3), from Postgres
from backoffice.graph.branches.human_review import FRONT_DESK      # "Front desk <frontdesk@overlook-hotel.example>"
# Shared with the invoice branch since 11.3 (see templates.py for how a template is filled):
from backoffice.graph.branches.templates import TEMPLATES_DIR, bullet_list, format_money, render, reply_subject
from backoffice.graph.state import DraftKind, EmailState, OutgoingDraft
from backoffice.services.availability import AlternativeStay


# --- Formatting: code turns exact values into text --------------------------------------------------

def format_date(day: date) -> str:
    """date(2026, 12, 18) -> "Friday, December 18, 2026"   (%A = weekday name, %B = month name)"""
    return f"{day:%A, %B} {day.day}, {day.year}"


def format_stay(check_in: date, check_out: date) -> str:
    """
    A stay as one line; the year is written once if both dates share it.
        Dec 28 -> Dec 30, 2026     -> "Monday, December 28 to Wednesday, December 30, 2026"
        Dec 30, 2026 -> Jan 1, 2027 -> "Wednesday, December 30, 2026 to Friday, January 1, 2027"
    """
    if check_in.year == check_out.year:
        return f"{check_in:%A, %B} {check_in.day} to {format_date(check_out)}"
    return f"{format_date(check_in)} to {format_date(check_out)}"


def format_rate(rate: Decimal) -> str:
    """
    Decimal("0.104") -> "10.4%"
    normalize() drops trailing zeros (10.400 -> 10.4); format(..., "f") keeps it in plain notation
    (without it, a 10% tax would print as "1E+1").
    """
    return f"{format((rate * 100).normalize(), 'f')}%"


def format_guests(adults: int | None, children: int | None) -> str:
    """(2, 1) -> "2 adults and 1 child";  (2, 0) -> "2 adults";  (1, 2) -> "1 adult and 2 children" """
    parts = [f"{adults} adult{'s' if adults != 1 else ''}"]
    if children:
        parts.append(f"{children} child{'ren' if children != 1 else ''}")
    return " and ".join(parts)


def format_nights(nights: int) -> str:
    """3 -> "3 nights";  1 -> "1 night" """
    return f"{nights} night{'s' if nights != 1 else ''}"


def reply_to_guest(state: EmailState, body: str, reason: str) -> dict:
    """
    The draft for any reply that goes back to the guest.

    Shape returned (#3):
        {"outgoing_draft": OutgoingDraft(kind=DraftKind.REPLY_TO_SENDER,
                                         outgoing_to="Sarah Mitchell <s.mitchell@mail.example>",
                                         outgoing_subject="Re: Room availability December 18-21",
                                         outgoing_body="Dear Sarah Mitchell, ...", reason="Available on ...")}
    """
    email = state["email"]
    return {"outgoing_draft": OutgoingDraft(
        kind=DraftKind.REPLY_TO_SENDER,
        outgoing_to=email.sender,
        outgoing_subject=reply_subject(email.subject),
        outgoing_body=body,
        reason=reason,
    )}


# --- The nodes ----------------------------------------------------------------------------------

def quote_reply(state: EmailState) -> dict:
    """
    NODE (available): the quote, from booking_quote.txt. Every figure comes from stay_price (10.3).

    Example (#3): "... Departure: Monday, December 21, 2026 (3 nights) ... Total: $1,440.72"
    """
    request, price = state["booking_request"], state["stay_price"]
    rates = current_room_rates()          # room type and tax rate to show (the same rates price_stay used)
    body = render("booking_quote", {
        "guest_name": request.guest_name,
        "check_in": format_date(request.check_in),
        "check_out": format_date(request.check_out),
        "nights": format_nights(price.nights),
        "guests": format_guests(request.adults, request.children),
        "room_type": rates.room_type,
        "subtotal": format_money(price.subtotal),
        "tax_rate": format_rate(rates.tax_rate),
        "tax": format_money(price.tax),
        "total": format_money(price.total_price),
    })
    return reply_to_guest(state, body, reason=f"Available on all {format_nights(price.nights)}; "
                                              f"price calculated in code from the room rates: {format_money(price.total_price)}.")


def full_reply(state: EmailState) -> dict:
    """
    NODE (full): "fully booked", with the alternatives from 10.3, or the no-alternatives wording.

    Example (#5): "... fully booked for at least one night of your stay (Wednesday, December 30, 2026 to
                   Friday, January 1, 2027) ... - Monday, December 28 to Wednesday, December 30, 2026 ..."
    """
    request = state["booking_request"]
    stays: list[AlternativeStay] = state.get("alternative_stays", [])
    full_nights = ", ".join(format_date(night) for night in state["availability_result"].full_nights)
    values = {"guest_name": request.guest_name,
              "requested_stay": format_stay(request.check_in, request.check_out)}
    if stays:
        values["alternatives"] = bullet_list([format_stay(s.check_in, s.check_out) for s in stays])
        body = render("booking_full_alternatives", values)
        reason = f"Fully booked on {full_nights}; {len(stays)} free stay(s) of the same length found in code."
    else:
        body = render("booking_full_no_alternatives", values)
        reason = f"Fully booked on {full_nights}; no free stay of the same length within 7 days."
    return reply_to_guest(state, body, reason)


def ask_for_missing_info(state: EmailState) -> dict:
    """
    NODE (info missing): ask the guest for exactly what code found missing (10.2).

    Example (#4): "Dear Tom, ... could you please let us know:
                     - how many children are travelling
                     - the age of each child (children under 13 pay the child rate)"
    """
    request = state["booking_request"]
    body = render("booking_ask_missing", {"guest_name": request.guest_name,
                                          "missing_items": bullet_list(request.missing)})
    return reply_to_guest(state, body, reason=f"Missing from the request: {'; '.join(request.missing)}.")


def no_data_reply(state: EmailState) -> dict:
    """
    NODE (no data): the nights aren't in the availability data, so a person must check. Goes to the
    FRONT DESK (forward_to_staff), not to the guest.

    Example (a request for July 10-14, 2027): "No data for: Saturday, July 10, 2027, ..."
    """
    email, request = state["email"], state["booking_request"]
    missing_nights = state["availability_result"].missing_nights
    body = render("booking_no_data", {
        "sender": email.sender,
        "requested_stay": format_stay(request.check_in, request.check_out),
        "guests": format_guests(request.adults, request.children),
        "nights_without_data": ", ".join(format_date(night) for night in missing_nights),
        "original_subject": email.subject,
        "original_body": email.body,
    })
    return {"outgoing_draft": OutgoingDraft(
        kind=DraftKind.FORWARD_TO_STAFF,
        outgoing_to=FRONT_DESK,
        outgoing_subject=f"Needs a person: {email.subject}",
        outgoing_body=body,
        reason=f"No availability data for {len(missing_nights)} night(s) of the stay: can't be checked automatically.",
    )}


def booking_evidence(state: EmailState) -> dict:
    """
    For the approval screen (step 10.5): what the model READ and what code DECIDED, as text, so the
    staff member can spot a misreading before approving. Used by nodes/approval.py.

    Shape returned:
      #3: {"read_as": "Friday, December 18 to Monday, December 21, 2026; 2 adults and 1 child",
           "missing": [], "notes": [], "unclear": ""}
      #4: {"read_as": "Friday, February 12 to Monday, February 15, 2027; 2 adults, children not stated",
           "missing": ["how many children are travelling", "the age of each child (...)"], "notes": [],
           "unclear": "The email says 'the kids' without a number or ages ..."}
    """
    request = state["booking_request"]
    if request.check_in and request.check_out:
        dates = format_stay(request.check_in, request.check_out)
    else:
        dates = "dates not clear"
    if request.children is None:
        guests = f"{request.adults} adults, children not stated"
    else:
        guests = format_guests(request.adults, request.children)
    return {"read_as": f"{dates}; {guests}",
            "missing": request.missing,
            "notes": request.notes,
            "unclear": state["booking_extraction"].unclear}


# Command line (plain Python; see main_graph.py for `if __name__ == "__main__":` and sys.argv):
# run the whole booking branch by hand (extract -> checks -> reply) and print the reply.
if __name__ == "__main__":
    from backoffice.graph.branches.booking.checks import (after_availability, after_extract, check_availability,
                                                          find_alternatives, price_stay)
    from backoffice.graph.branches.booking.extract import extract_request
    from backoffice.graph.main_graph import email_path_for
    from backoffice.graph.nodes.read_email import parse_eml
    from backoffice.tracing import flush_traces

    # The node to run for each name the routing functions return.
    REPLY_FOR = {"ask_for_missing_info": ask_for_missing_info, "quote_reply": quote_reply,
                 "full_reply": full_reply, "no_data_reply": no_data_reply}

    for name in sys.argv[1:] or ["03_booking_complete"]:
        state: dict = {"email": parse_eml(email_path_for(name))}
        state.update(extract_request(state))
        if after_extract(state) == "ask_for_missing_info":
            reply = "ask_for_missing_info"
        else:
            state.update(check_availability(state))
            step = after_availability(state)
            if step == "price_stay":
                state.update(price_stay(state))
                reply = "quote_reply"
            elif step == "find_alternatives":
                state.update(find_alternatives(state))
                reply = "full_reply"
            else:
                reply = "no_data_reply"
        state.update(REPLY_FOR[reply](state))
        draft = state["outgoing_draft"]
        print(f"=================== {name}  ->  {reply}")
        print(f"kind    : {draft.kind}")
        print(f"to      : {draft.outgoing_to}")
        print(f"subject : {draft.outgoing_subject}")
        print(f"reason  : {draft.reason}")
        print(f"\n{draft.outgoing_body}")
    flush_traces()
