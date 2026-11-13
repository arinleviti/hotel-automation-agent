"""Each graph step for the UI's middle column ("what the agent is doing"): a one-line LABEL, and the
DETAIL (what the node added to the state, as JSON) shown when the person clicks the line.

The API streams one event per step (see app.py); each event carries the step's name, the label and
the detail.
    describe_step("classify", {"classification": Classification(type="booking", confidence=0.95, ...)})
        -> "Claude classified it: booking (confidence 0.95)"
    describe_step("booking_branch > price_stay", {"stay_price": StayPrice(... total_price=Decimal("1440.72"))})
        -> "Price calculated in code: $1,440.72"

Labels are built only from what the node ADDED (its update), never from guesses. Unknown steps get
a generic label, so a new node never breaks the stream.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import dataclasses                       # is_dataclass / fields: read any of our dataclasses generically
from datetime import date, datetime      # dates become text ("2026-12-18")
from decimal import Decimal              # money becomes text ("1440.72"), never a float
from enum import Enum                    # StrEnums (e.g. DraftKind) become their value ("reply_to_sender")

# Pydantic:
from pydantic import BaseModel           # our LLM forms (Classification, BookingExtraction ...)

# OURS:
from backoffice.graph.branches.templates import format_money


def describe_step(step: str, added: dict) -> str:
    """One line of text for one finished step (see the examples at the top of this file)."""
    node = step.split(" > ")[-1]              # "booking_branch > price_stay" -> "price_stay"

    if node == "read_email" and "email" in added:
        email = added["email"]
        files = f", {len(email.attachments)} attachment(s)" if email.attachments else ""
        return f"Read the email from {email.sender}{files}"
    if node == "classify" and "classification" in added:
        c = added["classification"]
        flag = ", flagged SUSPICIOUS" if c.suspicious else ""
        return f"Claude classified it: {c.type} (confidence {c.confidence:.2f}){flag}"
    if node == "decide_route" and "route" in added:
        reason = added.get("reason_for_human_review")
        return f"Route chosen in code: {added['route']}" + (f" ({reason})" if reason else "")

    # Booking branch
    if node == "extract_request" and "booking_request" in added:
        request = added["booking_request"]
        if request.missing:
            return f"Claude read the request; code found missing: {'; '.join(request.missing)}"
        return (f"Claude read the request; code checked it: {request.check_in} to {request.check_out}, "
                f"{request.adults} adult(s), {request.children} child(ren)")
    if node == "check_availability" and "availability_result" in added:
        return f"Availability checked in code: {added['availability_result'].status}"
    if node == "price_stay" and "stay_price" in added:
        return f"Price calculated in code: {format_money(added['stay_price'].total_price)}"
    if node == "find_alternatives" and "alternative_stays" in added:
        return f"Alternatives found in code: {len(added['alternative_stays'])}"

    # Invoice branch
    if node == "extract_invoice" and "invoice_extraction" in added:
        return f"Claude copied the invoice: {len(added['invoice_extraction'].lines)} line(s)"
    if node == "check_invoice" and "invoice_review" in added:
        review = added["invoice_review"]
        verdicts = [c.check.verdict for c in review.lines]
        counts = ", ".join(f"{verdicts.count(v)} {v}" for v in sorted(set(verdicts)))
        return f"Invoice checked in code: {review.outcome}" + (f" ({counts})" if counts else "")

    # Question branch (the agent)
    if node == "agent":
        if added.get("pending_search"):
            return f"Claude decided to search: \"{added['pending_search']['query']}\""
        if "question_answer" in added:
            return f"Claude gave its final answer: {added['question_answer'].status}"
    if node == "search_step" and added.get("searches"):
        last = added["searches"][-1]
        best = last.results[0] if last.results else None
        found = f"best: {' > '.join(best.headings) or best.document} ({best.rerank_score:.2f})" if best else "nothing"
        return f"Searched the documents for \"{last.query}\": {found}"
    if node == "check_agent_answer" and "answer_check" in added:
        check = added["answer_check"]
        return f"Answer checked in code: {check.outcome}" + (f" ({'; '.join(check.problems)})" if check.problems else "")

    # Any reply node, the human route, the error handler
    if node == "error_handler" and "processing_error" in added:
        error = added["processing_error"]
        return f"A step failed ({error['step']}): sent to a person"
    if "outgoing_draft" in added:
        draft = added["outgoing_draft"]
        return f"Draft written ({draft.kind}) for {draft.outgoing_to}"
    if node == "approval" and "final_human_decision" in added:
        return f"Staff decision: {added['final_human_decision'].decision}"
    if node == "action" and "final_outgoing_message" in added:
        sent = added["final_outgoing_message"]
        return f"Recorded: sent to {sent.outgoing_to}" if sent else "Recorded: rejected, nothing sent"

    return f"Step finished: {step}"


# --- The detail behind each line (step 16.2) -------------------------------------------------------

# How much of an attachment's text (the PDF as Markdown) to show; the PDF itself is in the email view.
ATTACHMENT_PREVIEW_CHARS = 300


def step_detail(added: dict) -> dict:
    """
    What a node added to the state, as plain JSON values, for the page to show when a line is clicked.
    ONE generic conversion for every node (no code per node), so a new node shows its detail for free.

    Example: step_detail({"stay_price": StayPrice(nights=3, subtotal=Decimal("1305.00"), ...)})
        -> {"stay_price": {"nights": 3, "subtotal": "1305.00", "tax": "135.72", "total_price": "1440.72", ...}}
    Two things are shortened so the page stays readable:
      - an attachment's text (the whole PDF as Markdown) -> its first 300 characters + how long it is
      - agent_messages (the agent's raw conversation with Claude, which repeats every search result)
        -> one line saying how many messages; each search is shown by search_step anyway
    """
    detail = {}
    for key, value in added.items():
        if key == "agent_messages":
            detail[key] = f"({len(value)} messages in the agent's conversation with Claude: not shown here)"
        else:
            detail[key] = to_json(value)
    return detail


def to_json(value, key: str = ""):
    """
    Turn one value into something json.dumps can write, going inside lists, dicts and our objects.
      our dataclasses (OutgoingDraft, StayPrice ...)   -> dict of their fields
      Pydantic models (Classification ...)            -> dict of their fields (model_dump)
      Decimal("1440.72") -> "1440.72"   date(2026, 12, 18) -> "2026-12-18"   DraftKind.OK_TO_PAY -> "ok_to_pay"
      0.7905674576759338 (a score) -> 0.7906
    `key` = the name this value had in its parent, used to shorten an attachment's "markdown" text.
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        # model_dump() (Pydantic): the model's fields as a plain dict
        return to_json(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # dataclasses.fields(...) (plain Python): the dataclass's fields, in order
        return {f.name: to_json(getattr(value, f.name), f.name) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        # Keys must be text in JSON (e.g. a date key -> "2026-12-30")
        return {str(to_json(k)): to_json(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        # Search scores: 0.7905674576759338 -> 0.7906 (readable; 4 decimals are plenty to compare them)
        return round(value, 4)
    if isinstance(value, str) and key == "markdown" and len(value) > ATTACHMENT_PREVIEW_CHARS:
        return value[:ATTACHMENT_PREVIEW_CHARS] + f" ... ({len(value):,} characters in total)"
    return value
