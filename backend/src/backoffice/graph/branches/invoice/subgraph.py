"""The invoice branch as ONE LangGraph subgraph (step 11.4): the nodes of 11.1-11.3, connected.

    START
      │
    extract_invoice        (LLM copies the invoice, as printed)                  extract.py
      │
    check_invoice          (code: supplier, every line ✓/⚠/✗, totals, outcome)   checks.py
      │  after_check (code)
      ├─ "ok_to_pay_note"        → ok_to_pay_note ─────────┐   (#2)             replies.py
      ├─ "correction_request"    → correction_request ─────┤   (#1)
      ├─ "needs_check_note"      → needs_check_note ───────┤
      └─ "unknown_supplier_note" → unknown_supplier_note ──┤
                                                          END
Every path ends by writing state["outgoing_draft"]; the main graph then goes on to approval.

Built exactly like the booking subgraph (see branches/booking/subgraph.py for what a subgraph is):
same EmailState, no checkpointer of its own (the parent's is used), plugged into main_graph.py as
    builder.add_node("invoice_branch", build_invoice_graph())
"""

# --- Where every name used in this file comes from ------------------------------------------------
# LangGraph:
from langgraph.graph import END, START, StateGraph                  # the graph builder + its entry/exit points
from langgraph.graph.state import CompiledStateGraph                # the type of a built, runnable graph

# OURS:
from backoffice.graph.branches.invoice.checks import REPLY_FOR_OUTCOME, after_check, check_invoice
from backoffice.graph.branches.invoice.extract import extract_invoice
from backoffice.graph.branches.invoice.replies import (correction_request, needs_check_note, ok_to_pay_note,
                                                       unknown_supplier_note)
from backoffice.graph.robustness import RETRY_ONCE, end_branch_after_error   # step 13
from backoffice.graph.state import EmailState


def build_invoice_graph() -> CompiledStateGraph:
    """Build and compile the invoice subgraph (see the drawing at the top of this file)."""
    builder = StateGraph(EmailState)
    # Robustness (step 13, graph/robustness.py), for EVERY node of this subgraph: a temporary
    # failure is retried once; if a node still fails, the handler writes a note to the front desk
    # and ends the subgraph, so the main graph goes on to approval as usual.
    builder.set_node_defaults(retry_policy=RETRY_ONCE, error_handler=end_branch_after_error("invoice_branch"))

    builder.add_node("extract_invoice", extract_invoice)      # the only LLM call in the branch
    builder.add_node("check_invoice", check_invoice)          # code + database
    builder.add_node("ok_to_pay_note", ok_to_pay_note)        # the replies: templates filled by code
    builder.add_node("correction_request", correction_request)
    builder.add_node("needs_check_note", needs_check_note)
    builder.add_node("unknown_supplier_note", unknown_supplier_note)

    builder.add_edge(START, "extract_invoice")
    builder.add_edge("extract_invoice", "check_invoice")

    # The fork: after_check (code, checks.py) returns one of the 4 reply node names.
    # list(REPLY_FOR_OUTCOME.values()) = ["ok_to_pay_note", "correction_request", "needs_check_note",
    #                                     "unknown_supplier_note"]
    builder.add_conditional_edges("check_invoice", after_check, list(REPLY_FOR_OUTCOME.values()))

    for reply in REPLY_FOR_OUTCOME.values():
        builder.add_edge(reply, END)

    return builder.compile()     # no checkpointer: the parent graph's is used
