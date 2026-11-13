"""The shapes of the API's responses (Pydantic: "Pydantic at the edges"). FastAPI uses them to turn
our objects into JSON and to describe each endpoint in the automatic docs at /docs.

The request body of the decision endpoint is our existing HumanDecision (graph/state.py): the same
form the approval node's interrupt() checks, so the browser and the graph agree on one shape.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
from datetime import datetime

# Pydantic:
from pydantic import BaseModel


class EmailSummary(BaseModel):
    """
    One row of the inbox (left column).
    Example: {"name": "03_booking_complete", "sender": "Sarah Mitchell <...>", "subject": "Room availability ...",
              "date": "2026-11-02T18:41:00-07:00", "status": "waiting", "thread_id": "31917ec5-..."}
    status: "new" (never processed), "waiting" (paused at approval), or the decision: "approve" / "edit" / "reject".
    """

    name: str
    sender: str
    subject: str
    date: datetime | None
    status: str
    thread_id: str | None


class AttachmentInfo(BaseModel):
    """
    One file attached to an email: its name only, not its content (the page fetches the file
    itself from /emails/{name}/attachments/{filename} when it wants to show it).
    Example (email #1): {"filename": "FRP-INV-2026-1184.pdf", "content_type": "application/pdf", "size": 41873}
    """

    filename: str
    content_type: str
    size: int                          # bytes


class EmailDetail(BaseModel):
    """
    One email as the person reads it (the email view, step 16.1).
    Example (email #6):
        {"name": "06_question_pool_and_spa", "sender": "Linda Okafor <l.okafor@mail.example>",
         "to": "The Overlook Hotel <info@overlook-hotel.example>", "subject": "Pool and spa question",
         "date": "2026-11-04T10:15:00-07:00", "body": "Hello,\\n\\nWe're staying with you later this month. ...",
         "attachments": []}
    """

    name: str
    sender: str
    to: str
    subject: str
    date: datetime | None
    body: str
    attachments: list[AttachmentInfo]


class RunView(BaseModel):
    """
    One run (right column): waiting for approval, or finished.
      waiting:  approval_request = the draft + evidence (what the approval node's interrupt() handed out)
      finished: decision + sent (the final outgoing message, None after a reject)
    """

    thread_id: str
    status: str                        # "waiting" or "finished"
    approval_request: dict | None = None
    decision: str | None = None
    sent: dict | None = None
    # Only in the answer to a decision (step 16.3): the steps the resumed run took, in the same shape
    # as the stream's step events, e.g. [{"step": "approval", "label": "Staff decision: approve", "detail": {...}},
    #                                    {"step": "action", "label": "Recorded: sent to ...", "detail": {...}}]
    steps: list[dict] = []


class SentItem(BaseModel):
    """One row of the Sent folder (the `actions` table)."""

    thread_id: str
    email_name: str
    decision: str
    kind: str
    outgoing_to: str
    outgoing_subject: str
    outgoing_body: str
    comment: str
    decided_at: datetime
