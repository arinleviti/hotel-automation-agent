"""The booking branch as ONE LangGraph subgraph (step 10.5): the nodes of 10.2-10.4, connected.

    START
      │
    extract_request                 (LLM reads, code validates)              extract.py
      │  after_extract (code)
      ├─ "ask_for_missing_info" → ask_for_missing_info ──────────────────┐   replies.py
      └─ "check_availability"   → check_availability                     │   checks.py
            │  after_availability (code)                                 │
            ├─ "price_stay"        → price_stay        → quote_reply ────┤
            ├─ "find_alternatives" → find_alternatives → full_reply ─────┤
            └─ "no_data_reply"     → no_data_reply ──────────────────────┤
                                                                        END
Every path ends by writing state["outgoing_draft"]; the main graph then goes on to approval.

What a SUBGRAPH is (LangGraph): a graph built and compiled exactly like the main one, then given
to the main graph AS A NODE:
    builder.add_node("booking_branch", build_booking_graph())        (in main_graph.py)
From outside it's one box; when the main graph reaches it, LangGraph runs the whole inner graph
and then follows the main graph's arrow out of "booking_branch" (to approval).

  - Same state: it's built on EmailState, so its nodes read and write the main state directly
    (they read state["email"], they write booking_request, stay_price, outgoing_draft ...).
  - No checkpointer of its own: compile() without one means LangGraph uses the PARENT's, so the
    inner steps are saved too (in Postgres when run from the command line).
  - Why a subgraph and not 8 more nodes in the main graph: the main graph stays readable (one box
    per branch), and the branch can be built, drawn and tested on its own.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# LangGraph:
from langgraph.graph import END, START, StateGraph                  # the graph builder + its entry/exit points
from langgraph.graph.state import CompiledStateGraph                # the type of a built, runnable graph

# OURS:
from backoffice.graph.branches.booking.checks import (after_availability, after_extract, check_availability,
                                                      find_alternatives, price_stay)
from backoffice.graph.branches.booking.extract import extract_request
from backoffice.graph.branches.booking.replies import (ask_for_missing_info, full_reply, no_data_reply,
                                                       quote_reply)
from backoffice.graph.state import EmailState


def build_booking_graph() -> CompiledStateGraph:
    """Build and compile the booking subgraph (see the drawing at the top of this file)."""
    builder = StateGraph(EmailState)

    # Reading the request (the only LLM call in the branch).
    builder.add_node("extract_request", extract_request)
    # The checks (code + database).
    builder.add_node("check_availability", check_availability)
    builder.add_node("price_stay", price_stay)
    builder.add_node("find_alternatives", find_alternatives)
    # The replies (templates filled by code).
    builder.add_node("ask_for_missing_info", ask_for_missing_info)
    builder.add_node("quote_reply", quote_reply)
    builder.add_node("full_reply", full_reply)
    builder.add_node("no_data_reply", no_data_reply)

    builder.add_edge(START, "extract_request")

    # Fork 1, after reading: complete -> check; incomplete -> ask the guest.
    # after_extract (code, checks.py) returns one of the two names in the list.
    builder.add_conditional_edges("extract_request", after_extract,
                                  ["check_availability", "ask_for_missing_info"])

    # Fork 2, after checking: available -> price; full -> alternatives; no data -> front desk.
    builder.add_conditional_edges("check_availability", after_availability,
                                  ["price_stay", "find_alternatives", "no_data_reply"])

    builder.add_edge("price_stay", "quote_reply")
    builder.add_edge("find_alternatives", "full_reply")

    # Every reply ends the subgraph (the main graph then continues to approval).
    for reply in ("ask_for_missing_info", "quote_reply", "full_reply", "no_data_reply"):
        builder.add_edge(reply, END)

    return builder.compile()     # no checkpointer: the parent graph's is used
