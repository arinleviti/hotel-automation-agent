"""The approval node: PAUSE the graph until a staff member approves, edits or rejects the draft.

In:   state["outgoing_draft"]   the OutgoingDraft the branch prepared (+ email, route, reason_for_human_review, for context)
Out:  {"final_human_decision": HumanDecision(...)}

Every email reaches this node, whatever branch it took: "a human approves every outgoing message".

=================================================================================================
HOW interrupt() WORKS (LangGraph), with email #9
=================================================================================================
interrupt(value, response_schema=HumanDecision) is a LangGraph function you call INSIDE a node.

FIRST RUN, the graph reaches this node:
  1. interrupt(...) does NOT return. It stops the run (internally it raises a special exception
     that LangGraph catches), after the checkpointer has SAVED the state.
  2. `value` (our approval request: the draft + context) is handed to whoever started the run:
         graph.stream(...) yields  {"__interrupt__": (Interrupt(value={...the request...}, ...),)}
         graph.get_state(config).interrupts  ->  the same request, readable later
     The run is now PAUSED, waiting. In the UI (step 16) that's the draft with Approve/Edit/Reject.

LATER, a staff member answers:
  3. Someone resumes the same run (same thread_id) with LangGraph's Command:
         graph.stream(Command(resume={"decision": "approve"}), config)
  4. LangGraph checks the answer against response_schema (our HumanDecision, Pydantic). A wrong
     answer, e.g. {"decision": "edit"} with no text, raises a ValidationError and NOTHING is saved,
     so the same request can be answered again.
  5. LangGraph runs this node AGAIN FROM ITS FIRST LINE. This time interrupt(...) finds the answer
     and RETURNS it, as a HumanDecision object. The node returns it and the graph goes on.

Interview point, from step 5: the node is re-run from the start on resume. So nothing that must
happen only once (sending an email, saving to a table) may go BEFORE interrupt() in this node.
That's why the sending lives in a separate node after this one (the action node, step 9.2).

Why a checkpointer is required: the run stops completely between step 2 and step 3 (minutes or
days later, possibly after a restart), so the state must be saved somewhere. For now an in-memory
one (main_graph.py); Postgres from step 9.3, so a paused email survives a restart.
"""

from dataclasses import asdict

from langgraph.types import interrupt

from backoffice.graph.branches.booking.replies import booking_evidence     # ours (step 10.5)
from backoffice.graph.branches.invoice.replies import invoice_evidence     # ours (step 11.4)
from backoffice.graph.branches.question.replies import question_evidence   # ours (step 12.3)
from backoffice.graph.state import EmailState, HumanDecision

# Per route: the function that summarises what the branch read and decided, for the approver.
# (The "human" route has none: its draft already says why and quotes the original.)
EVIDENCE_FOR_ROUTE = {
    "booking": booking_evidence,
    "invoice": invoice_evidence,
    "question": question_evidence,
}


def approval_request(state: EmailState) -> dict:
    """
    What the staff member is shown: the draft, plus enough context to judge it. A plain dict of
    strings so it can be saved by the checkpointer and sent to the UI as JSON (step 15).

    Shape returned (email #9, texts shortened):
        {"incoming": {"sender": "Mark Ellison <...>", "subject": "Re: our stay Dec 5-7"},
         "route": "human",
         "reason_for_human_review": "Suspicious: Contains instructions addressed to the automated assistant ...",
         "evidence": {},
         "outgoing_draft": {"kind": "forward_to_staff",
                   "outgoing_to": "Front desk <frontdesk@overlook-hotel.example>",
                   "outgoing_subject": "Needs a person: Re: our stay Dec 5-7",
                   "outgoing_body": "This email was not answered automatically. ...",
                   "reason": "Suspicious: ..."}}
    For a booking (#3), "evidence" shows what the model read and what code decided:
         "evidence": {"read_as": "Friday, December 18 to Monday, December 21, 2026; 2 adults and 1 child",
                      "missing": [], "notes": [], "unclear": ""}
    """
    # Step 13: after a FAILED step the state can be partial (no email if read_email failed, no route
    # if classify failed, half a branch's keys), so everything is read with .get, and the evidence
    # becomes the error itself instead of the branch's own (which could miss what it needs).
    #   failed: "evidence": {"failed_step": "invoice_branch > extract_invoice", "error": "RuntimeError: ..."}
    email = state.get("email")
    route = state.get("route", "not routed")
    error = state.get("processing_error")
    if error:
        evidence = {"failed_step": error["step"], "error": error["error"]}
    else:
        make_evidence = EVIDENCE_FOR_ROUTE.get(route)      # None for routes with no evidence (human)
        evidence = make_evidence(state) if make_evidence else {}
    return {
        "incoming": {"sender": email.sender if email else "(unreadable email)",
                     "subject": email.subject if email else state.get("email_path", "")},
        "route": route,
        "reason_for_human_review": state.get("reason_for_human_review", ""),
        "evidence": evidence,
        # asdict(...) = Python's standard way to turn a dataclass into a dict of its fields.
        "outgoing_draft": asdict(state["outgoing_draft"]),
    }


def approval(state: EmailState) -> dict:
    """
    THE NODE. First run: pauses (interrupt). On resume: returns the staff member's decision.

    Example (on resume):
        in:  {..., "outgoing_draft": OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, ...)}
        out: {"final_human_decision": HumanDecision(decision=Decision.APPROVE, edited_subject=None, edited_body=None, comment="")}
    """
    # Nothing before this line may have side effects: the node re-runs from here on resume.
    # 1st value, approval_request(state): what goes OUT when the run stops.
    # 2nd value, response_schema=HumanDecision: what must come IN to resume.
    decision = interrupt(approval_request(state), response_schema=HumanDecision)
    return {"final_human_decision": decision}
