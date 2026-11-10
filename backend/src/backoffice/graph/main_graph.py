"""THE GRAPH: where the nodes are connected and run. Start reading the project's flow here.

The graph grows step by step; now (step 8.3) the whole trunk is wired:
    8.1  START -> read_email -> END
    8.2  START -> read_email -> classify -> END
    8.3  START -> read_email -> classify -> decide_route -> one of 4 branches -> END        <- now

    START
      |
    read_email        (code)   .eml -> ParsedEmail
      |
    classify          (LLM)    ParsedEmail -> Classification (the model fills in a form)
      |
    decide_route      (code)   Classification -> route (+ human_reason): the RULES
      |
      +-- route = "invoice"  --> invoice_branch    (placeholder; step 11)
      +-- route = "booking"  --> booking_branch    (placeholder; step 10)
      +-- route = "question" --> question_branch   (placeholder; step 12)
      +-- route = "human"    --> human_review      (placeholder; step 9)
      |
     END

Who starts the graph, and where the first state comes from:
    graph.invoke({"email_path": ".../data/emails/06_question_pool_and_spa.eml"})
    - today: the command at the bottom of this file (you choose the email);
    - from step 15: the backend API, when someone clicks an email in the UI. The browser sends only
      the email's NAME (e.g. "06_question_pool_and_spa"); the API turns it into a path inside
      data/emails/ with email_path_for(), so a client can never make the server open any other file;
    - in a real deployment: a mailbox reader that saves each new email and starts the graph for it.

Run one email (from backend/):
    uv run python -m backoffice.graph.main_graph 06_question_pool_and_spa
"""

import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backoffice.graph.branches.placeholders import booking_branch, human_review, invoice_branch, question_branch
from backoffice.graph.nodes.classify import classify
from backoffice.graph.nodes.decide_route import decide_route
from backoffice.graph.nodes.read_email import read_email
from backoffice.graph.state import EmailState

# main_graph.py is at backend/src/backoffice/graph/ -> four levels up is the repo root.
EMAILS_DIR = Path(__file__).resolve().parents[4] / "data" / "emails"

# route value (written by decide_route) -> the node that handles it
BRANCH_FOR_ROUTE = {
    "invoice": "invoice_branch",
    "booking": "booking_branch",
    "question": "question_branch",
    "human": "human_review",
}


def follow_route(state: EmailState) -> str:
    """
    The CONDITIONAL EDGE: after decide_route, which node runs next?

    It only READS the decision decide_route already saved in the state (the rules live there, in
    plain tested code). Returns the NAME of the next node, e.g. state["route"] = "question" ->
    "question_branch".
    """
    return BRANCH_FOR_ROUTE[state["route"]]


def build_graph() -> CompiledStateGraph:
    """
    Build the graph: register the nodes, connect them with edges, compile.

    StateGraph(EmailState) = an empty graph whose state has the shape of EmailState.
    add_node(name, function)  = a box: LangGraph will call `function(state)` when it reaches `name`.
    add_edge(a, b)            = an arrow: after `a` finishes, ALWAYS run `b`.
    add_conditional_edges(a, choose, [options])
                              = a fork: after `a`, call `choose(state)`; it returns the name of the
                                next node, which must be one of `options`.
    START, END                = LangGraph's built-in entry and exit points.
    compile()                 = check the blueprint (every node reachable, no dangling arrow) and
                                turn it into a runnable object with .invoke(...) / .stream(...).
    """
    builder = StateGraph(EmailState)

    # The trunk: every email goes through these three.
    builder.add_node("read_email", read_email)        # code: .eml -> ParsedEmail
    builder.add_node("classify", classify)            # LLM:  ParsedEmail -> Classification
    builder.add_node("decide_route", decide_route)    # code: Classification -> route

    # The branches (placeholders for now).
    builder.add_node("invoice_branch", invoice_branch)
    builder.add_node("booking_branch", booking_branch)
    builder.add_node("question_branch", question_branch)
    builder.add_node("human_review", human_review)

    builder.add_edge(START, "read_email")
    builder.add_edge("read_email", "classify")
    builder.add_edge("classify", "decide_route")

    # The fork. A conditional edge means: after this node there is more than one possible path.
    #   1. decide_route has already updated the state with the route (e.g. state["route"] = "question").
    #   2. Then LangGraph runs follow_route, which reads that route in code and returns the name of
    #      the node to run next (e.g. "question_branch").
    #   3. The last argument is the list of possible destinations: a safety check. compile() verifies
    #      they all exist, an unexpected name makes the run fail with a clear error, and LangGraph can
    #      draw all four arrows.
    #      list(BRANCH_FOR_ROUTE.values()) = ["invoice_branch", "booking_branch", "question_branch", "human_review"]
    builder.add_conditional_edges("decide_route", follow_route, list(BRANCH_FOR_ROUTE.values()))

    # Every branch ends the run (for now; from step 9 they will lead to human approval first).
    for branch in BRANCH_FOR_ROUTE.values():
        builder.add_edge(branch, END)

    return builder.compile()


def email_path_for(name: str) -> Path:
    """
    Turn an email's name into its file path, accepting only the demo emails in data/emails/.

    Example: "06_question_pool_and_spa"      -> Path(".../data/emails/06_question_pool_and_spa.eml")
             "../../../.env" (a malicious name) -> ValueError
    """
    path = (EMAILS_DIR / f"{name.removesuffix('.eml')}.eml").resolve()
    if path.parent != EMAILS_DIR or not path.is_file():
        raise ValueError(f"No demo email called {name!r} in {EMAILS_DIR}")
    return path


def process_email(name: str) -> EmailState:
    """
    Run one email through the graph and return the final state.

    Shape returned (email #6):
        {"email_path": "C:/.../data/emails/06_question_pool_and_spa.eml",
         "email": ParsedEmail(sender="Linda Okafor <l.okafor@mail.example>", subject="Pool and spa question", ...),
         "classification": Classification(type="question", suspicious=False, confidence=0.97, ...),
         "route": "question"}
    """
    graph = build_graph()
    # invoke(starting_state) runs the graph from START to END and returns the final state.
    return graph.invoke({"email_path": str(email_path_for(name))})


def process_email_step_by_step(name: str) -> tuple[EmailState, list[str]]:
    """
    Same as process_email, but also returns WHICH NODES RAN, in order.

    graph.stream(..., stream_mode="updates") runs the same graph but hands back each node's result
    as soon as that node finishes, one at a time:
        {"read_email": {"email": ParsedEmail(...)}}
        {"classify": {"classification": Classification(...)}}
        {"decide_route": {"route": "question"}}
        {"question_branch": {}}
    That's what the UI will use in step 15 to show the steps appearing one by one.
    Here we collect the node names and merge the updates into the final state ourselves.

    Shape returned:
        ({"email_path": "...", "email": ParsedEmail(...), "classification": ..., "route": "question"},
         ["read_email", "classify", "decide_route", "question_branch"])
    """
    graph = build_graph()
    state: dict = {"email_path": str(email_path_for(name))}
    nodes_run: list[str] = []
    for update in graph.stream(state, stream_mode="updates"):
        for node_name, added in update.items():      # one node per update in this graph
            nodes_run.append(node_name)
            state.update(added or {})                 # merge what the node added
    return state, nodes_run


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "06_question_pool_and_spa"
    state, nodes_run = process_email_step_by_step(name)
    email, c = state["email"], state["classification"]
    print(f"nodes run  : {' -> '.join(nodes_run)}")
    print(f"state keys : {list(state)}")
    print(f"from       : {email.sender}")
    print(f"subject    : {email.subject}")
    print(f"classified : type={c.type} suspicious={c.suspicious} confidence={c.confidence}")
    print(f"summary    : {c.summary}")
    print(f"route      : {state['route']}")
    if state.get("human_reason"):
        print(f"why human  : {state['human_reason']}")
