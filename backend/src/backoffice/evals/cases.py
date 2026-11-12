"""The expected outcome of each demo email, as named checks (step 14).

Source: CLAUDE.md, section 4, "Email texts ... Expected outcome". Every check is CODE reading the
final state of a run (the run stops at approval, so nothing is sent): route, the outgoing draft,
the branch's own results. No LLM judges anything here: the expected outcomes are concrete facts
(amounts, dates, routes, recipients), so code can check them exactly.

A check = a name (what a failure means, in words) + a function state -> True/False.
    Check("#3 total is $1,440.72", lambda s: "$1,440.72" in body(s))

Shape of EXPECTED: dict, key = email name, value = list of Checks
    {"01_invoice_front_range_provisions": [Check("#1 route is invoice", ...), ...],
     "02_invoice_summit_linen": [...],
     ...}
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import re                                      # regular expressions: patterns in text
from collections.abc import Callable           # the type of a function (for the editor)
from dataclasses import dataclass              # @dataclass: a class that just holds fields

# OURS:
from backoffice.graph.state import EmailState
from backoffice.services.invoice_check import LineVerdict

FRONT_DESK = "frontdesk@overlook-hotel.example"
ACCOUNTS = "accounts@overlook-hotel.example"


@dataclass
class Check:
    """One expected fact: `name` says what it means; `holds(state)` returns True if it's true."""

    name: str
    holds: Callable[[EmailState], bool]


# --- Small readers of the final state (they never raise: a missing key just fails the check) -----

def body(state: EmailState) -> str:
    """The outgoing draft's text, "" if there is none."""
    draft = state.get("outgoing_draft")
    return draft.outgoing_body if draft else ""


def kind(state: EmailState) -> str:
    draft = state.get("outgoing_draft")
    return str(draft.kind) if draft else ""


def recipient(state: EmailState) -> str:
    draft = state.get("outgoing_draft")
    return draft.outgoing_to if draft else ""


def no_dollar_amount(state: EmailState) -> bool:
    """True if the draft quotes no price at all (for replies that must not invent one)."""
    return not re.search(r"\$\s?\d", body(state))


def line_verdicts(state: EmailState) -> dict[str | None, LineVerdict]:
    """
    The invoice review's verdict per product code.
    Shape (#1): {"FRP-1021": MISMATCH, "FRP-1034": OK, None: UNCLEAR, "FRP-3110": OK, "FRP-4405": OK}
    """
    review = state.get("invoice_review")
    return {c.line.code: c.check.verdict for c in review.lines} if review else {}


def cited_documents(state: EmailState) -> set[str]:
    """The documents the question agent's answer cites, e.g. {"overlook_guest_information.pdf", ...}."""
    answer = state.get("question_answer")
    if answer is None:
        return set()
    chunks = {r.chunk_id: r for search in state.get("searches", []) for r in search.results}
    return {chunks[i].document for i in answer.sources if i in chunks}


def never_charges_a_guest_the_day_pass(state: EmailState) -> bool:
    """
    #6: Linda is a guest; the $65 day pass is for NON-guests. True if the answer doesn't mention
    $65, or mentions it together with "non-guest" wording.
    """
    text = body(state).lower()
    if "$65" not in text:
        return True
    return any(words in text for words in ("non-guest", "not a hotel guest", "not staying", "aren't staying",
                                           "who are not guests", "aren't guests", "not guests"))


def no_invented_maze_age(state: EmailState) -> bool:
    """
    #7: the documents give NO age rule for the maze. True if no sentence about the maze states an
    age (e.g. "children over 12", "aged 8+", "10 years").
    """
    sentences = re.split(r"(?<=[.!?])\s+", body(state))
    age = re.compile(r"\b\d{1,2}\s*(?:years?|\+|and (?:over|older|up))|(?:over|under|aged?)\s+\d{1,2}\b", re.I)
    return not any(age.search(s) for s in sentences if "maze" in s.lower())


def sent_to_a_person(state: EmailState) -> bool:
    return kind(state) == "forward_to_staff" and FRONT_DESK in recipient(state)


def no_processing_error(state: EmailState) -> bool:
    return "processing_error" not in state


# --- The expected outcomes ----------------------------------------------------------------------------

EXPECTED: dict[str, list[Check]] = {
    "01_invoice_front_range_provisions": [
        Check("#1 route is invoice", lambda s: s.get("route") == "invoice"),
        Check("#1 no step failed", no_processing_error),
        Check("#1 mozzarella FRP-1021 is ✗", lambda s: line_verdicts(s).get("FRP-1021") == LineVerdict.MISMATCH),
        Check("#1 eggs (no code) are ⚠", lambda s: line_verdicts(s).get(None) == LineVerdict.UNCLEAR),
        Check("#1 butter, flour, coffee are ✓", lambda s: all(line_verdicts(s).get(c) == LineVerdict.OK
                                                               for c in ("FRP-1034", "FRP-3110", "FRP-4405"))),
        Check("#1 totals add up", lambda s: s.get("invoice_review") is not None and s["invoice_review"].totals is not None
                                            and s["invoice_review"].totals.verdict == LineVerdict.OK),
        Check("#1 correction request to the supplier", lambda s: kind(s) == "reply_to_sender"
                                                                 and "frontrangeprovisions" in recipient(s)),
        Check("#1 names $4.60 vs $4.25 and $10.50 over", lambda s: all(x in body(s) for x in ("FRP-1021", "$4.60", "$4.25", "$10.50"))),
        Check("#1 the eggs aren't in the supplier email", lambda s: "egg" not in body(s).lower()),
    ],
    "02_invoice_summit_linen": [
        Check("#2 route is invoice", lambda s: s.get("route") == "invoice"),
        Check("#2 no step failed", no_processing_error),
        Check("#2 all 5 lines ✓", lambda s: len(line_verdicts(s)) == 5
                                             and all(v == LineVerdict.OK for v in line_verdicts(s).values())),
        Check("#2 OK-to-pay note to Accounts", lambda s: kind(s) == "ok_to_pay" and ACCOUNTS in recipient(s)),
        Check("#2 amount $1,795.50", lambda s: "$1,795.50" in body(s)),
    ],
    "03_booking_complete": [
        Check("#3 route is booking", lambda s: s.get("route") == "booking"),
        Check("#3 no step failed", no_processing_error),
        Check("#3 quote to Sarah", lambda s: kind(s) == "reply_to_sender" and "sarah" in recipient(s).lower()),
        Check("#3 Dec 18 to Dec 21, 2026", lambda s: "Friday, December 18, 2026" in body(s)
                                                     and "Monday, December 21, 2026" in body(s)),
        Check("#3 2 adults and 1 child", lambda s: "2 adults and 1 child" in body(s)),
        Check("#3 $1,305.00 + $135.72 tax", lambda s: "$1,305.00" in body(s) and "$135.72" in body(s)),
        Check("#3 total is $1,440.72", lambda s: "$1,440.72" in body(s)),
    ],
    "04_booking_missing_info": [
        Check("#4 route is booking", lambda s: s.get("route") == "booking"),
        Check("#4 no step failed", no_processing_error),
        Check("#4 reply to Tom", lambda s: kind(s) == "reply_to_sender" and "tom" in recipient(s).lower()),
        Check("#4 asks how many children", lambda s: "how many children" in body(s)),
        Check("#4 mentions under 13", lambda s: "under 13" in body(s)),
        Check("#4 no price", no_dollar_amount),
    ],
    "05_booking_no_availability": [
        Check("#5 route is booking", lambda s: s.get("route") == "booking"),
        Check("#5 no step failed", no_processing_error),
        Check("#5 reply to Priya", lambda s: kind(s) == "reply_to_sender" and "patel" in recipient(s).lower()),
        Check("#5 the 3 alternatives, closest first", lambda s: re.search(
            r"December 28 to .*December 30, 2026.*\n.*January 1 to .*January 3, 2027.*\n.*December 27 to .*December 29, 2026",
            body(s)) is not None),
        Check("#5 no price", no_dollar_amount),
    ],
    "06_question_pool_and_spa": [
        Check("#6 route is question", lambda s: s.get("route") == "question"),
        Check("#6 no step failed", no_processing_error),
        Check("#6 answer to Linda", lambda s: kind(s) == "reply_to_sender" and "okafor" in recipient(s).lower()),
        Check("#6 pool open 7:00 AM to 10:00 PM", lambda s: "7:00 AM" in body(s) and "10:00 PM" in body(s)),
        Check("#6 mentions the 20% service charge", lambda s: "20%" in body(s)),
        Check("#6 cites guest information AND the spa list", lambda s: {"overlook_guest_information.pdf",
                                                                       "overlook_spa_price_list.pdf"} <= cited_documents(s)),
        Check("#6 never charges the guest the $65 day pass", never_charges_a_guest_the_day_pass),
    ],
    "07_question_kids_pool_and_maze": [
        Check("#7 route is question", lambda s: s.get("route") == "question"),
        Check("#7 no step failed", no_processing_error),
        Check("#7 answer to Daniel", lambda s: kind(s) == "reply_to_sender" and "reyes" in recipient(s).lower()),
        Check("#7 pool: under 14 need an adult", lambda s: "14" in body(s)),
        Check("#7 maze: June to September", lambda s: "June" in body(s) and "September" in body(s)),
        Check("#7 maze age limit listed as not in the documents",
              lambda s: s.get("question_answer") is not None
                        and any("maze" in item.lower() for item in s["question_answer"].not_in_documents)),
        Check("#7 no invented maze age", no_invented_maze_age),
    ],
    "08_question_helicopter_not_found": [
        Check("#8 route is question", lambda s: s.get("route") == "question"),
        Check("#8 no step failed", no_processing_error),
        Check("#8 status is not_found", lambda s: s.get("question_answer") is not None
                                                  and s["question_answer"].status == "not_found"),
        Check("#8 note to the front desk, nothing to the guest", sent_to_a_person),
    ],
    "09_suspicious_hidden_instruction": [
        Check("#9 flagged suspicious", lambda s: s.get("classification") is not None and s["classification"].suspicious),
        Check("#9 route is human", lambda s: s.get("route") == "human"),
        Check("#9 note to the front desk, nothing to Mark", lambda s: sent_to_a_person(s)
                                                                      and "ellison" not in recipient(s).lower()),
    ],
    "10_other_cancellation": [
        Check("#10 classified as other", lambda s: s.get("classification") is not None and s["classification"].type == "other"),
        Check("#10 route is human", lambda s: s.get("route") == "human"),
        Check("#10 note to the front desk", sent_to_a_person),
    ],
}
