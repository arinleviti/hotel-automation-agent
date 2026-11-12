"""The question branch as a LangGraph subgraph: the agent loop, then code checks, then the reply.

    START
      │
    agent ◄──────────────┐        (LLM: search again, or answer?)            agent.py
      │  after_agent     │
      ├─ "search_step" → search_step   (code: your step-7 search)            agent.py
      └─ "check_agent_answer" ↓
    check_agent_answer             (code: sources real? amounts real?)       checks.py
      │  after_answer_check
      ├─ "answer_reply"      → answer_reply ──────┐   (#6, #7 → the guest)   replies.py
      ├─ "not_found_note"    → not_found_note ────┤   (#8 → the front desk)
      └─ "check_failed_note" → check_failed_note ─┤   (held back → the front desk)
                                                 END

A LOOP in a graph: the arrow from search_step goes BACK to agent. LangGraph runs agent, then
search_step, then agent again ... until after_agent returns "check_agent_answer" (the turn in which
Claude calls give_final_answer, so the agent node writes pending_search = None). The loop is bounded twice in
code: MAX_SEARCHES in agent.py, and LangGraph's own recursion limit (25 steps by default), which
raises an error rather than looping forever.

Run it on demo emails (from backend/; Postgres running; real Claude + Voyage calls):
    uv run python -m backoffice.graph.branches.question.subgraph 06_question_pool_and_spa 07_question_kids_pool_and_maze 08_question_helicopter_not_found
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import sys                                     # sys.argv: the words typed on the command line

# LangGraph:
from langgraph.graph import END, START, StateGraph                  # the graph builder + its entry/exit points
from langgraph.graph.state import CompiledStateGraph                # the type of a built, runnable graph

# OURS:
from backoffice.graph.branches.question.agent import after_agent, agent, search_step
from backoffice.graph.branches.question.checks import REPLY_FOR_OUTCOME, after_answer_check, check_agent_answer
from backoffice.graph.branches.question.replies import answer_reply, check_failed_note, not_found_note
from backoffice.graph.robustness import RETRY_ONCE, end_branch_after_error   # step 13
from backoffice.graph.state import EmailState


def build_question_graph() -> CompiledStateGraph:
    """Build and compile the question subgraph (see the drawing at the top of this file)."""
    builder = StateGraph(EmailState)
    # Robustness (step 13, graph/robustness.py), for EVERY node of this subgraph: a temporary
    # failure is retried once; if a node still fails, the handler writes a note to the front desk
    # and ends the subgraph, so the main graph goes on to approval as usual.
    builder.set_node_defaults(retry_policy=RETRY_ONCE, error_handler=end_branch_after_error("question_branch"))
    builder.add_node("agent", agent)
    builder.add_node("search_step", search_step)
    builder.add_node("check_agent_answer", check_agent_answer)
    builder.add_node("answer_reply", answer_reply)
    builder.add_node("not_found_note", not_found_note)
    builder.add_node("check_failed_note", check_failed_note)

    builder.add_edge(START, "agent")
    # The fork after each agent turn: after_agent returns the name of the next node, one of these two
    # (same pattern as the booking and invoice subgraphs).
    # add_conditional_edges(source, path, path_map):
    #   source   "agent"        the fork comes right after the agent node (and ONLY after it)
    #   path     after_agent    the function LangGraph calls to decide; it returns a node name
    #   path_map [...]          the node names it may return (checked when the graph is compiled)
    builder.add_conditional_edges("agent", after_agent, ["search_step", "check_agent_answer"])
    # After search_step there is ALWAYS another agent call: a fixed arrow, no decision in between.
    # This arrow back is what makes the loop.
    builder.add_edge("search_step", "agent")

    # The fork after the checks: one of the 3 reply nodes.
    builder.add_conditional_edges("check_agent_answer", after_answer_check, list(REPLY_FOR_OUTCOME.values()))
    for reply in REPLY_FOR_OUTCOME.values():
        builder.add_edge(reply, END)

    return builder.compile()     # no checkpointer: the parent graph's is used


# Command line (plain Python; see main_graph.py for `if __name__ == "__main__":` and sys.argv):
# run the branch on demo emails and print every search, the check and the draft.
if __name__ == "__main__":
    from backoffice.graph.main_graph import email_path_for
    from backoffice.graph.nodes.read_email import parse_eml
    from backoffice.tracing import flush_traces

    graph = build_question_graph()
    for name in sys.argv[1:] or ["07_question_kids_pool_and_maze"]:
        state = graph.invoke({"email": parse_eml(email_path_for(name))})
        print(f"=================== {name}")
        for number, search in enumerate(state.get("searches", []), start=1):
            # enumerate(..., start=1) (plain Python): (1, first search), (2, second search), ...
            found = ", ".join(f"[{r.chunk_id}] {' > '.join(r.headings) or r.document} {r.rerank_score:.2f}"
                              for r in search.results)
            print(f"search {number}: {search.query!r}\n          -> {found}")
        answer, check, draft = state["question_answer"], state["answer_check"], state["outgoing_draft"]
        print(f"status   : {answer.status}   sources {answer.sources}   not in documents {answer.not_in_documents}")
        print(f"check    : {check.outcome}  {check.problems}")
        print(f"draft    : {draft.kind} to {draft.outgoing_to}  subject {draft.outgoing_subject!r}")
        print(f"\n{draft.outgoing_body}\n")
    flush_traces()
