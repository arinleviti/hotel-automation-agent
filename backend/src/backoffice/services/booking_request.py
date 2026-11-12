"""Turn what the LLM read from a booking email into a request the code can trust (step 10.2).

The LLM (graph/branches/booking/extract.py) only READS the email and fills in a form. This module
DECIDES whether that form is usable: plain rules, no LLM, no database (values passed in), so every
rule is tested on its own.

    LLM form (BookingExtraction)  ->  validate_booking_request(...)  ->  BookingRequest
                                                                          complete, or with a list
                                                                          of what's missing

Why the rules live here and not in the prompt: "rules that must hold belong in code". A prompt can
ask the model to be careful; only code can guarantee that an impossible date is never priced.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
from dataclasses import dataclass, field       # @dataclass: a class that just holds fields
from datetime import date                      # a calendar date, e.g. date(2026, 12, 18)
from email.utils import parseaddr              # splits "Sarah Mitchell <s@x.example>" into name + address

# What's missing, as the words the "ask" reply will use (10.4 puts them into the template).
MISSING_DATES = "your arrival and departure dates"
MISSING_ADULTS = "how many adults are travelling"
MISSING_CHILDREN = "how many children are travelling"
MISSING_AGES = "the age of each child (children under {age} pay the child rate)"

NEUTRAL_GREETING_NAME = "guest"                # "Dear guest," when no name can be found


@dataclass
class BookingRequest:
    """
    The booking request the rest of the branch works from: either complete, or with `missing` filled.

    Examples:
      #3 Sarah (complete):
        BookingRequest(check_in=date(2026, 12, 18), check_out=date(2026, 12, 21), adults=2, children=1,
                       guest_name="Sarah Mitchell", missing=[], notes=[])
      #4 Tom (missing info):
        BookingRequest(check_in=date(2027, 2, 12), check_out=date(2027, 2, 15), adults=2, children=None,
                       guest_name="Tom",
                       missing=["how many children are travelling",
                                "the age of each child (children under 13 pay the child rate)"], notes=[])
    """

    check_in: date | None
    check_out: date | None
    adults: int | None              # guests who pay the adult rate (children aged 13+ are counted here)
    children: int | None            # guests who pay the child rate (under 13)
    guest_name: str                 # for the greeting only: "Sarah Mitchell", "Tom", or "guest"
    missing: list[str] = field(default_factory=list)   # empty = complete
    notes: list[str] = field(default_factory=list)     # what code changed, shown to the approver

    @property
    def is_complete(self) -> bool:
        """
        True when nothing is missing. @property (plain Python) = read it like a field, without ():
        request.is_complete, not request.is_complete().
        """
        return not self.missing


def validate_booking_request(
    check_in: date | None,
    check_out: date | None,
    adults: int | None,
    children: int | None,
    children_ages: list[int],
    email_date: date | None,
    child_under_age: int,
    guest_name: str,
) -> BookingRequest:
    """
    Apply the rules to what the LLM read. Never raises: every problem becomes a `missing` entry,
    because the outcome is a reply asking the guest, not a crash.

    Inputs: the LLM's values (None = not stated), the email's own date ("today" for this email),
    and child_under_age from the room_rates table (13 at The Overlook).

    Rules:
      1. dates not stated                                       -> missing dates
      2. check-out not after check-in, or check-in before the
         email was written (impossible / in the past)           -> missing dates (never priced)
      3. adults not stated, or fewer than 1                     -> missing adults
      4. children mentioned but not counted ("the kids")        -> missing children (and their ages)
      5. children counted but not every age given               -> missing ages
      6. a "child" aged 13 or more pays the adult rate          -> counted as an adult (+ a note)
    """
    missing: list[str] = []
    notes: list[str] = []

    # Rules 1 and 2: the dates.
    dates_ok = check_in is not None and check_out is not None and check_out > check_in
    if dates_ok and email_date is not None and check_in < email_date:
        dates_ok = False
    if not dates_ok:
        missing.append(MISSING_DATES)

    # Rule 3: adults.
    if adults is None or adults < 1:
        missing.append(MISSING_ADULTS)

    # Rules 4, 5, 6: children and their ages.
    if children is None:
        missing.append(MISSING_CHILDREN)
        missing.append(MISSING_AGES.format(age=child_under_age))
    elif children > 0 and len(children_ages) != children:
        missing.append(MISSING_AGES.format(age=child_under_age))
    elif children > 0:
        # Every age is known: anyone 13 or older pays the adult rate.
        older = [age for age in children_ages if age >= child_under_age]
        if older and adults is not None:
            adults += len(older)
            children -= len(older)
            notes.append(f"{len(older)} child(ren) aged {', '.join(map(str, older))} counted as "
                         f"adult(s): the child rate is for guests under {child_under_age}.")

    return BookingRequest(
        check_in=check_in if dates_ok else None,
        check_out=check_out if dates_ok else None,
        adults=adults,
        children=children,
        guest_name=guest_name,
        missing=missing,
        notes=notes,
    )


def greeting_name(name_read_by_llm: str | None, email_text: str, sender_header: str) -> str:
    """
    The name used in "Dear ...,". A name is never required: no name -> "guest".

    Order:
      1. the name the LLM read (usually from the signature), ONLY if it really appears in the email
         text (so a made-up name can't get in); all-lowercase names get capitals: "tom" -> "Tom";
      2. otherwise the display name in the From: header, if there is one;
      3. otherwise "guest".

    Examples:
        greeting_name("tom", "...thanks\\ntom", "Tom Becker <tom.b@mail.example>")          -> "Tom"
        greeting_name(None, "...", "Sarah Mitchell <s.mitchell@mail.example>")              -> "Sarah Mitchell"
        greeting_name(None, "do you have a room?", "aleviti2@hotmail.example")              -> "guest"
        greeting_name("Mr. Ullman", "...no such name...", "x@mail.example")                 -> "guest"
    """
    if name_read_by_llm:
        name = name_read_by_llm.strip()
        if name and name.lower() in email_text.lower():
            # str.title() (plain Python): capitalise each word, "tom" -> "Tom". Only for names the
            # guest wrote all in lowercase, so "McDonald" isn't turned into "Mcdonald".
            return name.title() if name.islower() else name

    # parseaddr (plain Python, email.utils): "Sarah Mitchell <s.mitchell@mail.example>"
    #   -> ("Sarah Mitchell", "s.mitchell@mail.example"); a bare address gives ("", "address").
    display_name, _address = parseaddr(sender_header)
    if display_name.strip():
        return display_name.strip()

    return NEUTRAL_GREETING_NAME
