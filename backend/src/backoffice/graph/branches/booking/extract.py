"""Booking branch, node 1: read the room request (ONE LLM call), then validate it in code.

In:   state["email"]                              the incoming email (ParsedEmail)
Out:  {"booking_extraction": BookingExtraction(...),   what the LLM READ, kept as it was
       "booking_request":    BookingRequest(...)}      what CODE accepted, or the list of what's missing

    the email ──► Claude Haiku fills in BookingExtraction ──► validate_booking_request (code) ──► BookingRequest
                  (LLM: reads free text)                       (rules: dates, adults, children,
                                                                ages, the under-13 rule)

This is the only place in the booking branch where an LLM is used, because it's the only place
where the input is free text. Everything after it (availability, price, alternatives, the reply)
is code and fixed templates: no LLM writes any booking reply (decided 2026-11-11).

Run it on one demo email (from backend/; Postgres must be running, it reads the room rates):
    uv run python -m backoffice.graph.branches.booking.extract 04_booking_missing_info
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import sys                                     # sys.argv: the words typed on the command line
from pathlib import Path                       # Path: a file path you can join with /

# Langfuse (tracing):
from langfuse import observe                   # @observe: record this function as a named step in the trace

# OURS:
from backoffice.db.connection import connect                       # open a Postgres connection
from backoffice.db.queries import load_room_rates                  # the room_rates row -> RoomRates
from backoffice.graph.state import BookingExtraction, EmailState, ParsedEmail
from backoffice.llm import anthropic_client                        # the shared Claude client
from backoffice.services.booking_request import BookingRequest, greeting_name, validate_booking_request
from backoffice.services.pricing import RoomRates
from backoffice.tracing import init_tracing

# The Langfuse client must exist before the first @observe-decorated call (see tracing.py).
init_tracing()

# Claude Haiku 5.5: reading a short request into a form is a simple task (decided 2026-11-11).
EXTRACT_MODEL = "claude-haiku-5-5"

# extract.py is at backoffice/graph/branches/booking/ -> three levels up is backoffice/.
SYSTEM_PROMPT = (Path(__file__).resolve().parents[3] / "prompts" / "booking_extract_system.md").read_text(encoding="utf-8")


def build_prompt(email: ParsedEmail) -> str:
    """
    How the email is shown to Claude: the day it was received (for the year of "December 18"),
    then the email itself between <email> tags (data, never instructions).

    Example (email #3, shortened):
        Email received on: 2026-11-02

        <email>
        From: Sarah Mitchell <s.mitchell@mail.example>
        Subject: Room availability December 18-21

        Good evening, My husband and I would like to stay ... from Friday December 18 to Monday December 21 ...
        </email>
    """
    received = email.date.date().isoformat() if email.date else "unknown"
    return (f"Email received on: {received}\n\n"
            f"<email>\nFrom: {email.sender}\nSubject: {email.subject}\n\n{email.body}\n</email>")


# @observe (Langfuse): this function appears as a named step "ask_llm_to_extract_booking" in the
# trace; the Claude call inside it is recorded automatically (see tracing.py).
@observe(name="ask_llm_to_extract_booking", capture_input=False)
def ask_llm_to_extract_booking(email: ParsedEmail) -> BookingExtraction:
    """
    One call to Claude Haiku; returns the filled-in form (see BookingExtraction in state.py).

    messages.parse(..., output_format=BookingExtraction) (Anthropic SDK): sends the form's JSON
    Schema as the required answer format, then turns Claude's JSON answer back into a
    BookingExtraction object and validates it (same technique as classify.py).
    """
    response = anthropic_client().messages.parse(
        model=EXTRACT_MODEL,
        max_tokens=2048,
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(email)}],
        output_format=BookingExtraction,
    )
    # No valid form (the model refused, or ran out of room): step 13 will turn this into
    # "send to a human" instead of an error.
    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        raise RuntimeError(f"Booking extraction failed: stop_reason={response.stop_reason}")
    return response.parsed_output


def current_room_rates() -> RoomRates:
    """The hotel's room rates from Postgres (needed here for the under-13 age limit)."""
    with connect() as conn:
        return load_room_rates(conn)


def validated_request(extraction: BookingExtraction, email: ParsedEmail, rates: RoomRates) -> BookingRequest:
    """
    Hand the LLM's form to the code rules (services/booking_request.py).

    Example (email #4, Tom):
        extraction: check_in=2027-02-12, check_out=2027-02-15, adults=2, children=None, guest_name="tom"
        ->  BookingRequest(check_in=date(2027, 2, 12), check_out=date(2027, 2, 15), adults=2, children=None,
                           guest_name="Tom",
                           missing=["how many children are travelling",
                                    "the age of each child (children under 13 pay the child rate)"])
    """
    return validate_booking_request(
        check_in=extraction.check_in,
        check_out=extraction.check_out,
        adults=extraction.adults,
        children=extraction.children,
        children_ages=extraction.children_ages,
        email_date=email.date.date() if email.date else None,    # "today" for this email
        child_under_age=rates.child_under_age,                   # 13, from the room_rates table
        guest_name=greeting_name(extraction.guest_name, email.body, email.sender),
    )


def extract_request(state: EmailState) -> dict:
    """
    THE NODE. Reads the request with the LLM, validates it in code, returns both.

    Example (email #3):
        in:  {..., "email": ParsedEmail(subject="Room availability December 18-21", ...)}
        out: {"booking_extraction": BookingExtraction(check_in=date(2026, 12, 18), ..., children_ages=[8]),
              "booking_request":    BookingRequest(check_in=date(2026, 12, 18), check_out=date(2026, 12, 21),
                                                   adults=2, children=1, guest_name="Sarah Mitchell", missing=[])}
    """
    email = state["email"]
    extraction = ask_llm_to_extract_booking(email)
    return {"booking_extraction": extraction,
            "booking_request": validated_request(extraction, email, current_room_rates())}


# Command line (plain Python, see main_graph.py for `if __name__ == "__main__":` and sys.argv):
# run this node alone on one demo email and print what the LLM read and what code decided.
if __name__ == "__main__":
    from backoffice.graph.main_graph import email_path_for          # ours: email name -> safe path
    from backoffice.graph.nodes.read_email import parse_eml        # ours: .eml -> ParsedEmail
    from backoffice.tracing import flush_traces

    for name in sys.argv[1:] or ["03_booking_complete"]:
        email = parse_eml(email_path_for(name))
        result = extract_request({"email": email})
        extraction, request = result["booking_extraction"], result["booking_request"]
        print(f"=== {name}")
        print(f"LLM read   : {extraction.model_dump()}")      # model_dump() (Pydantic): the form as a plain dict
        print(f"code says  : complete={request.is_complete}  greeting='Dear {request.guest_name},'")
        print(f"             check_in={request.check_in} check_out={request.check_out} "
              f"adults={request.adults} children={request.children}")
        if request.missing:
            print(f"missing    : {request.missing}")
        if request.notes:
            print(f"notes      : {request.notes}")
    flush_traces()
