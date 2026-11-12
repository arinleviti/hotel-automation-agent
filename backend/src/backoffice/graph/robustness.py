"""Robustness (step 13): when a step fails, the email goes to a person instead of the run crashing.

Two LangGraph features, set on every node except approval and action (see main_graph.py and the
three subgraphs):

  RETRY_ONCE   LangGraph's RetryPolicy: a node that fails with a TEMPORARY problem (network drop,
               server error, timeout, rate limit, an answer in the wrong format) is run once more.
               Anything else (a refusal, an unreadable PDF, our own "rule broken" errors) is not
               retried: retrying wouldn't change it.

  error handler  LangGraph calls it when a node still fails (after the retry, if any). Ours writes
               a note to the front desk saying which step failed and why, and sends the run on to
               approval, where a staff member sees it like any other email.
                 - in the main graph:  send_to_human_after_error   -> jumps to "approval"
                 - inside a subgraph:  end_branch_after_error      -> ends the subgraph; the main
                                       graph's normal arrow then leads to approval

  Not on approval and action: if THOSE fail, the run stops with the error (saved by the
  checkpointer, so it can be resumed once the cause is fixed) instead of looping back to approval.

Timeouts: set on the clients (Anthropic 60 s, Voyage 30 s, Postgres connect 5 s): a hanging call
raises a timeout error, which RETRY_ONCE retries once, then the error handler sends to a person.
LangGraph's own per-node `timeout` needs async nodes; it comes with the async backend in step 15.

Example (#1's PDF corrupted):
    extract_invoice raises  ->  not temporary, no retry  ->  end_branch_after_error writes:
        processing_error = {"step": "invoice_branch > extract_invoice", "error": "RuntimeError: ..."}
        outgoing_draft   = OutgoingDraft(kind=FORWARD_TO_STAFF, outgoing_to="Front desk <...>",
                                         outgoing_subject="Needs a person: Invoice FRP-INV-2026-1184 - ...", ...)
    ->  the subgraph ends  ->  approval shows it to a staff member
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
from pathlib import Path                       # Path: a file path you can join with /

# Libraries whose errors count as TEMPORARY:
import anthropic                               # Anthropic SDK errors (network, timeout, 5xx, rate limit)
import psycopg                                 # psycopg.OperationalError: the database couldn't be reached
import voyageai.error                          # Voyage errors (network, timeout, 5xx, rate limit)
from pydantic import ValidationError           # an answer that doesn't match its form

# LangGraph:
from langgraph.errors import NodeError         # what LangGraph hands the error handler: .node (name) + .error (the exception)
from langgraph.graph import END                # the end of a (sub)graph
from langgraph.types import Command, RetryPolicy   # Command: "update the state AND go to this node"

# OURS:
from backoffice.graph.branches.human_review import FRONT_DESK
from backoffice.graph.branches.templates import render
from backoffice.graph.state import DraftKind, EmailState, OutgoingDraft

# The exception types worth one more try: they describe a passing problem, not a wrong input.
TEMPORARY_ERRORS = (
    anthropic.APIConnectionError,              # network drop or timeout (APITimeoutError is a subclass)
    anthropic.RateLimitError,
    anthropic.InternalServerError,             # Anthropic's servers: 5xx
    voyageai.error.APIConnectionError,
    voyageai.error.Timeout,
    voyageai.error.RateLimitError,
    voyageai.error.ServerError,
    voyageai.error.ServiceUnavailableError,
    psycopg.OperationalError,                  # Postgres unreachable for a moment
    TimeoutError,
    ConnectionError,
    ValidationError,                           # "wrong format": CLAUDE.md says retry once, then a person
)

# RetryPolicy (LangGraph): max_attempts=2 = the first try + ONE retry; initial_interval = seconds to
# wait before the retry; retry_on = which exceptions to retry (here: only the temporary ones).
RETRY_ONCE = RetryPolicy(max_attempts=2, initial_interval=2.0, retry_on=TEMPORARY_ERRORS)


def describe_error(error: BaseException) -> str:
    """'RuntimeError: Invoice extraction failed: stop_reason=refusal' (at most 300 characters)."""
    return f"{type(error).__name__}: {error}"[:300]


def error_update(state: EmailState, step: str, error: BaseException) -> dict:
    """
    What the error handlers write into the state: the error, why a person is needed, and a note to
    the front desk. Works even if the email itself couldn't be read (state["email"] missing).

    Shape returned (#1 with a corrupted PDF):
        {"processing_error": {"step": "invoice_branch > extract_invoice", "error": "RuntimeError: ..."},
         "reason_for_human_review": "Not processed automatically: invoice_branch > extract_invoice failed (RuntimeError: ...)",
         "outgoing_draft": OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, outgoing_to="Front desk <...>", ...)}
    """
    error_text = describe_error(error)
    email = state.get("email")
    if email is not None:
        original = f"From: {email.sender}\nSubject: {email.subject}\n\n{email.body}"
        subject = email.subject
    else:
        original = f"(the email file could not be read: {state.get('email_path', 'unknown')})"
        subject = Path(state.get("email_path", "email")).stem
    reason = f"Not processed automatically: {step} failed ({error_text})"
    body = render("processing_error", {"step": step, "error": error_text, "original": original})
    return {
        "processing_error": {"step": step, "error": error_text},
        "reason_for_human_review": reason,
        "outgoing_draft": OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, outgoing_to=FRONT_DESK,
                                        outgoing_subject=f"Needs a person: {subject}",
                                        outgoing_body=body, reason=reason),
    }


def send_to_human_after_error(state: EmailState, error: NodeError) -> Command:
    """
    ERROR HANDLER for the MAIN graph's nodes (read_email, classify, decide_route, human_review).
    LangGraph calls it with the state and a NodeError (error.node = the failed node's name,
    error.error = the exception). Command(update=..., goto="approval") = add these keys to the
    state, then run the approval node next.
    """
    return Command(update=error_update(state, error.node, error.error), goto="approval")


def end_branch_after_error(branch: str):
    """
    Build the ERROR HANDLER for one SUBGRAPH's nodes. goto=END ends the subgraph; the main graph's
    normal arrow (branch -> approval) then shows the note to a staff member.

    Example: end_branch_after_error("invoice_branch") -> a handler that records the step as
             "invoice_branch > extract_invoice" when extract_invoice fails.
    """
    def handler(state: EmailState, error: NodeError) -> Command:
        return Command(update=error_update(state, f"{branch} > {error.node}", error.error), goto=END)
    return handler
