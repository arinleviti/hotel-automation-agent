"""The action node: CARRY OUT the staff member's decision (a CODE-ONLY node: no LLM).

In:   state["outgoing_draft"]        the message the branch prepared
      state["final_human_decision"]  what the staff member decided (written by approval)
Out:  {"final_outgoing_message": OutgoingDraft(...) or None}

Where it sits:   branch -> approval -> action -> END

  approval  COLLECTS the decision (it pauses with interrupt(); on resume it returns the answer);
  action    CARRIES IT OUT: records the message as sent, or records the rejection.
They are separate nodes because approval re-runs from its first line on resume (see approval.py),
so anything that must happen only once, like saving to a table, can't live there.

What "carry out" means per decision (phase 1: no real email is sent; "sent" = a row in `actions`):
    approve -> the draft, unchanged, recorded as sent
    edit    -> the staff member's version (edited_body; edited_subject or the draft's subject), recorded as sent
    reject  -> nothing sent; the refused draft is recorded with decision 'reject' (audit trail)
"""

from dataclasses import replace
from pathlib import Path

from langgraph.config import get_config

from backoffice.db.connection import connect
from backoffice.db.queries import save_action
from backoffice.graph.state import Decision, EmailState, HumanDecision, OutgoingDraft


def final_message(draft: OutgoingDraft, decision: HumanDecision) -> OutgoingDraft | None:
    """
    The message that actually goes out, or None if nothing goes out. Pure logic, no database.

    Examples (email #9's draft to the front desk):
        approve                                        -> the draft, unchanged
        edit, edited_body="Please call the guest."     -> the draft with outgoing_body="Please call the guest."
                                                          (subject unchanged, since no edited_subject was given)
        reject                                         -> None

    dataclasses.replace(obj, field=value) = Python's standard way to make a COPY of a dataclass with
    some fields changed; the original draft stays as it was (it is still in the state, for the record).
    """
    if decision.decision == Decision.REJECT:
        return None
    if decision.decision == Decision.EDIT:
        return replace(
            draft,
            outgoing_subject=decision.edited_subject or draft.outgoing_subject,
            outgoing_body=decision.edited_body or draft.outgoing_body,
        )
    return draft


def action(state: EmailState) -> dict:
    """
    THE NODE. Works out the final message, records the outcome in the `actions` table, and puts
    the final message into the state.

    Example (email #9, approved):
        in:  {..., "email_path": ".../09_suspicious_hidden_instruction.eml",
                   "outgoing_draft": OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, ...),
                   "final_human_decision": HumanDecision(decision=Decision.APPROVE, ...)}
        writes the row:  thread_id=..., email_name="09_suspicious_hidden_instruction", decision="approve", ...
        out: {"final_outgoing_message": OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, ...)}   # same as the draft
    """
    draft = state["outgoing_draft"]
    decision = state["final_human_decision"]
    message = final_message(draft, decision)

    # Which run this is: read from the run's config (see current_thread_id below).
    thread_id = current_thread_id()
    email_name = Path(state["email_path"]).stem        # ".../09_suspicious_hidden_instruction.eml" -> "09_suspicious_hidden_instruction"

    # `with connect() as conn:` opens a connection, COMMITS when the block ends normally (or rolls
    # back on an error), then closes it. One short connection per action: actions are rare.
    with connect() as conn:
        save_action(conn, thread_id, email_name, decision.decision,
                    message if message is not None else draft,     # after reject: record the refused draft
                    decision.comment)

    return {"final_outgoing_message": message}


def current_thread_id() -> str:
    """
    The current run's thread_id.

    get_config() is a LangGraph function: called from inside a node while the graph is running, it
    returns the `config` the run was started with, e.g.
        {"configurable": {"thread_id": "6b9a9f43-2c3b-4c13-b22d-1c29be760742", ...}, "callbacks": [...], ...}
    (main_graph.run_config builds it). The thread_id isn't in our state: it belongs to the run, not
    to the email, so we read it from there instead of copying it into the state.
    """
    return get_config()["configurable"]["thread_id"]
