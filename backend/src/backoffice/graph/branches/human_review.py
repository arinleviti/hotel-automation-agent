"""Branch "human": emails the system must not or cannot handle (a CODE-ONLY node: no LLM).

In:   state["email"], state["classification"], state["reason_for_human_review"]   (from the trunk)
Out:  {"outgoing_draft": OutgoingDraft(kind=FORWARD_TO_STAFF, outgoing_to=the front desk, ...)}

Which emails come here (decided by decide_route): suspicious ones (#9), type "other" (#10, a
cancellation), and any email classified with confidence below 0.7.

What it prepares: an internal message TO THE FRONT DESK that forwards the incoming email, says why
it wasn't answered automatically, and quotes the original below. Nothing is sent to the guest.
Like every draft, it then waits for a staff member's approval (the approval node).

Why plain code and not an LLM writing this message:
  - it's a fixed template: nothing to judge, so no model is needed (cheaper, faster, testable);
  - a suspicious email (#9) should be fed to a model as LITTLE as possible: its text is shown to
    the staff member as a quote, never used as instructions for another model call.
"""

from backoffice.graph.state import DraftKind, EmailState, OutgoingDraft

# Who receives forwarded emails. One address for phase 1 (a hotel's front desk handles the inbox).
FRONT_DESK = "Front desk <frontdesk@overlook-hotel.example>"


def forward_to_front_desk(state: EmailState) -> OutgoingDraft:
    """
    Build the forwarding message.

    Shape returned (email #9, body shortened):
        OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF,
                      outgoing_to="Front desk <frontdesk@overlook-hotel.example>",
                      outgoing_subject="Needs a person: Re: our stay Dec 5-7",
                      outgoing_body="This email was not answered automatically.\n\n"
                                    "Why: Suspicious: Contains instructions addressed to the automated assistant ...\n"
                                    "Summary: Guest confirms a Dec 5-7 stay and claims a free suite upgrade.\n\n"
                                    "---------- Original email ----------\n"
                                    "From: Mark Ellison <...>\nDate: ...\nSubject: Re: our stay Dec 5-7\n\n"
                                    "Hi, just confirming our stay ...",
                      reason="Suspicious: Contains instructions addressed to the automated assistant ...")
    """
    email = state["email"]
    reason = state.get("reason_for_human_review", "Sent to a person.")
    body = "\n".join([
        "This email was not answered automatically.",
        "",
        f"Why: {reason}",
        f"Summary: {state['classification'].summary}",
        "",
        "---------- Original email ----------",
        f"From: {email.sender}",
        f"Date: {email.date}",
        f"Subject: {email.subject}",
        "",
        email.body,
    ])
    return OutgoingDraft(
        kind=DraftKind.FORWARD_TO_STAFF,
        outgoing_to=FRONT_DESK,
        outgoing_subject=f"Needs a person: {email.subject}",
        outgoing_body=body,
        reason=reason,
    )


def human_review(state: EmailState) -> dict:
    """
    THE NODE (the branch for route "human"): prepares the forwarding message; the approval node
    that follows shows it to a staff member.

    Example:
        in:  {..., "route": "human", "reason_for_human_review": "No automated process for this kind of email (type 'other')."}   # #10
        out: {"outgoing_draft": OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, outgoing_subject="Needs a person: RE: Booking confirmation OVR-58213", ...)}
    """
    return {"outgoing_draft": forward_to_front_desk(state)}
