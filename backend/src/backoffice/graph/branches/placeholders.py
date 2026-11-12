"""TEMPORARY placeholder branches. Each one will be replaced by the real thing:

    invoice_branch   -> step 11: a subgraph (extract lines -> look up prices -> compare -> draft)
    question_branch  -> step 12: the agent (search the documents -> answer with sources)

(Real since step 9: human_review, branches/human_review.py. Real since step 10: the booking
branch, branches/booking/subgraph.py.)

Since step 9 every branch must end with an OutgoingDraft in the state, because the approval node
that follows shows it to a staff member. So each placeholder writes a STUB draft saying the branch
isn't built yet; that lets every demo email go through approval already.
"""

from backoffice.graph.state import DraftKind, EmailState, OutgoingDraft


def placeholder_draft(state: EmailState, branch: str, step: int) -> dict:
    """
    Shape returned (email #6, question):
        {"outgoing_draft": OutgoingDraft(kind=DraftKind.REPLY_TO_SENDER,
                                outgoing_to="Linda Okafor <...>",
                                outgoing_subject="Re: Pool and spa question",
                                outgoing_body="(placeholder: the question branch is built in step 12)",
                                reason="Placeholder draft: the question branch is not built yet.")}
    """
    email = state["email"]
    return {"outgoing_draft": OutgoingDraft(
        kind=DraftKind.REPLY_TO_SENDER,
        outgoing_to=email.sender,
        outgoing_subject=f"Re: {email.subject}",
        outgoing_body=f"(placeholder: the {branch} branch is built in step {step})",
        reason=f"Placeholder draft: the {branch} branch is not built yet.",
    )}


def invoice_branch(state: EmailState) -> dict:
    return placeholder_draft(state, "invoice", 11)


def question_branch(state: EmailState) -> dict:
    return placeholder_draft(state, "question", 12)
