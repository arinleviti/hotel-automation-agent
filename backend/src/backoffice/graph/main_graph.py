"""THE GRAPH: where the nodes are connected and run. Start reading the project's flow here.

The graph now (step 10):

    START
      |
    read_email        (code)   .eml -> ParsedEmail                       (the INCOMING email)
      |
    classify          (LLM)    ParsedEmail -> Classification (the model fills in a form)
      |
    decide_route      (code)   Classification -> route (+ reason_for_human_review): the RULES
      |
      +-- route = "invoice"  --> invoice_branch    (real: a SUBGRAPH, branches/invoice/subgraph.py)
      +-- route = "booking"  --> booking_branch    (real: a SUBGRAPH, branches/booking/subgraph.py)
      +-- route = "question" --> question_branch   (real: the AGENT loop subgraph, branches/question/subgraph.py)
      +-- route = "human"    --> human_review      (real: forward to the front desk)
      |                              every branch writes state["outgoing_draft"]: the OUTGOING message
    approval          (interrupt)  PAUSES the run until a staff member approves / edits / rejects
      |                              on resume: writes state["final_human_decision"]
    action            (code)       CARRIES OUT the decision: a row in the `actions` table
      |                              ("sent", or "rejected"); writes state["final_outgoing_message"]
     END

A run now happens in TWO HALVES, because of the pause:
    1. process_email("09_suspicious_hidden_instruction")
         runs START ... approval, then STOPS. Returns a RunResult with:
           thread_id          "3f2a9c1e-..."   the run's ID, needed to resume it
           waiting_for_human  the approval request: the draft + context (what the UI will show)
    2. resume_email(thread_id, {"decision": "approve"}, graph)
         continues the SAME run: approval returns the decision, action records it, then END.
Between the two, the state is kept by the CHECKPOINTER (graph/checkpointer.py):
    - in Postgres (the command line below; the backend API from step 15): the two halves can run
      in two DIFFERENT programs, minutes or days apart, even after a restart;
    - in memory (the tests): both halves must use the same `graph` object, inside one program.

thread_id: LangGraph's name for "one run". Every checkpoint is saved under it, and passing the
same thread_id is how you say "continue THAT run". We create a new random one (uuid4) per run, so
processing the same email twice gives two separate runs.

Who starts the graph, and where the first state comes from:
    - today: the command at the bottom of this file (you choose the email);
    - from step 15: the backend API, when someone clicks an email in the UI. The browser sends only
      the email's NAME (e.g. "06_question_pool_and_spa"); the API turns it into a path inside
      data/emails/ with email_path_for(), so a client can never make the server open any other file;
    - in a real deployment: a mailbox reader that saves each new email and starts the graph for it.

Run one email (from backend/), as TWO separate programs, like the UI will (open, then click):
    uv run python -m backoffice.graph.main_graph process 09_suspicious_hidden_instruction
        -> runs until approval, prints the draft and the thread_id, and the program ENDS
    uv run python -m backoffice.graph.main_graph resume <thread_id> approve
    uv run python -m backoffice.graph.main_graph resume <thread_id> reject
    uv run python -m backoffice.graph.main_graph resume <thread_id> edit "Please call the guest."
        -> a NEW program loads the paused run from Postgres, answers it, approval -> action -> END
(Postgres must be running: docker compose up -d; tables created by: uv run python -m backoffice.db.schema)

=================================================================================================
WHAT HAPPENS WHEN YOU RUN THOSE COMMANDS, in order
  [ours] = a function in our project   [LangGraph] / [Langfuse] / [Anthropic] = from that library
=================================================================================================
PROGRAM 1:  ... main_graph process 09_suspicious_hidden_instruction
 1. Python runs the block at the bottom of this file:  if __name__ == "__main__":
 2. with postgres_checkpointer() as checkpointer:   open a Postgres connection    [ours, checkpointer.py]
 3.   graph = build_graph(checkpointer)                                             [ours, below]
        init_tracing()                         create the Langfuse client          [ours, tracing.py]
        StateGraph(EmailState)                 an empty graph                      [LangGraph]
        builder.add_node(...) x 9              register our node functions         [LangGraph]
        builder.add_edge(...), add_conditional_edges(...)   the arrows             [LangGraph]
        builder.compile(checkpointer=...)      -> the runnable graph, saving state [LangGraph]
 4.   process_email(name, graph)                                                    [ours, below]
        thread_id = new random ID; email_path_for(name)                            [ours]
        with propagate_attributes(trace_name=..., session_id=thread_id):          [Langfuse]
          graph.stream(starting_state, config)                                     [LangGraph]
          ^ LangGraph runs OUR nodes one after the other, following the arrows, and SAVES the
            state in Postgres after each one:
            read_email -> classify -> decide_route -> follow_route -> a branch -> approval
            approval calls interrupt(...): LangGraph saves the state and STOPS the run.
        graph.get_state(config)  -> the saved state + the waiting approval request [LangGraph]
 5.   print the draft and the thread_id; the program ENDS. The run now exists only in Postgres.

PROGRAM 2 (any time later):  ... main_graph resume <thread_id> approve
 1. if __name__ == "__main__":  ->  with postgres_checkpointer() ...  ->  build_graph(checkpointer)
 2.   resume_email(thread_id, {"decision": "approve"}, graph)                       [ours, below]
        graph.stream(Command(resume=...), config)                                  [LangGraph]
        LangGraph LOADS the run from Postgres (by thread_id), checks the answer against
        HumanDecision, re-runs approval, which now returns it; then action records the outcome
        in the `actions` table, and the run reaches END.
 3.   print the result, then flush_traces()  send the trace                       [ours, tracing.py]
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python (the standard library, comes with Python):
import sys                                     # sys.argv: the words typed on the command line (bottom of the file)
import uuid                                    # uuid.uuid4(): a new random ID, used as the thread_id
from dataclasses import dataclass, field       # @dataclass: a class that just holds fields (RunResult)
from pathlib import Path                       # Path: a file path you can join with /
from typing import Any                         # Any: "any type", only for the editor

# Langfuse (tracing library):
from langfuse import propagate_attributes      # names the trace of a run (observability only)

# LangGraph (the graph library):
from langgraph.checkpoint.base import BaseCheckpointSaver   # the common type of all checkpointers
from langgraph.graph import END, START, StateGraph          # the graph builder + its entry/exit points
from langgraph.graph.state import CompiledStateGraph        # the type of a built, runnable graph
from langgraph.types import Command                         # Command(resume=...): the answer to an interrupt

# Pydantic (data validation):
from pydantic import ValidationError                        # the error raised when an answer has the wrong shape

# OURS (files in this project):
from backoffice.graph.branches.booking.subgraph import build_booking_graph                 # branch "booking" (a subgraph)
from backoffice.graph.branches.human_review import human_review                           # branch "human"
from backoffice.graph.branches.invoice.subgraph import build_invoice_graph                 # branch "invoice" (a subgraph)
from backoffice.graph.branches.question.subgraph import build_question_graph               # branch "question" (the agent)
from backoffice.graph.checkpointer import memory_checkpointer, postgres_checkpointer      # where runs are saved
from backoffice.graph.nodes.action import action                                          # node: record the decision
from backoffice.graph.nodes.approval import approval                                      # node: pause for a human
from backoffice.graph.nodes.classify import classify                                      # node: Claude sorts the email
from backoffice.graph.nodes.decide_route import decide_route                              # node: the routing rules
from backoffice.graph.nodes.read_email import read_email                                  # node: read the .eml
from backoffice.graph.robustness import RETRY_ONCE, send_to_human_after_error            # step 13: retry + error handler
from backoffice.graph.state import EmailState                                             # the state's shape
from backoffice.tracing import flush_traces, graph_callbacks, init_tracing                # Langfuse setup

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


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """
    Build the graph: register the nodes, connect them with edges, compile.

    StateGraph(EmailState) = an empty graph whose state has the shape of EmailState.
    add_node(name, function)  = a box: LangGraph will call `function(state)` when it reaches `name`.
    add_edge(a, b)            = an arrow: after `a` finishes, ALWAYS run `b`.
    add_conditional_edges(a, choose, [options])
                              = a fork: after `a`, call `choose(state)`; it returns the name of the
                                next node, which must be one of `options`.
    START, END                = LangGraph's built-in entry and exit points.
    compile(checkpointer=...) = check the blueprint (every node reachable, no dangling arrow) and
                                turn it into a runnable object with .stream(...) / .get_state(...).
                                The checkpointer is where it saves the state after every node;
                                required by interrupt() (the approval node).

    checkpointer: BaseCheckpointSaver is LangGraph's base class for all checkpointers (in memory,
    Postgres ...). None = a new in-memory one (what the tests use: no database needed). The command
    line (and later the API) passes postgres_checkpointer(), so paused runs survive a restart.
    """
    init_tracing()     # create the Langfuse client before the graph runs (see tracing.py)
    builder = StateGraph(EmailState)

    # Robustness (step 13, see graph/robustness.py), on every node of the trunk and human_review:
    #   retry_policy=RETRY_ONCE   a temporary failure (network, timeout, 5xx, wrong format) is retried once
    #   error_handler=...         if it still fails: a note to the front desk, then straight to approval
    # (The subgraphs set the same two things inside themselves. approval and action get neither:
    #  if they fail, the run stops with the error rather than looping back to approval.)
    safe = {"retry_policy": RETRY_ONCE, "error_handler": send_to_human_after_error}
    # **safe (plain Python) = pass the dict's entries as keyword arguments: retry_policy=..., error_handler=...

    # The trunk: every email goes through these three.
    builder.add_node("read_email", read_email, **safe)        # code: .eml -> ParsedEmail
    builder.add_node("classify", classify, **safe)            # LLM:  ParsedEmail -> Classification
    builder.add_node("decide_route", decide_route, **safe)    # code: Classification -> route

    # The branches: each one writes state["outgoing_draft"], the outgoing message.
    builder.add_node("invoice_branch", build_invoice_graph())     # a subgraph, like booking
    # A compiled GRAPH used as a node: LangGraph runs the whole booking subgraph here, then follows
    # the arrow out of "booking_branch" (to approval). See branches/booking/subgraph.py.
    builder.add_node("booking_branch", build_booking_graph())
    builder.add_node("question_branch", build_question_graph())   # a subgraph: the agent loop
    builder.add_node("human_review", human_review, **safe)

    # The human step: every draft waits here for a staff member.
    builder.add_node("approval", approval)
    # Then the decision is carried out: recorded as sent, or as rejected.
    builder.add_node("action", action)

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

    # Every branch leads to approval: no outgoing message skips the human.
    for branch in BRANCH_FOR_ROUTE.values():
        builder.add_edge(branch, "approval")
    builder.add_edge("approval", "action")
    builder.add_edge("action", END)

    return builder.compile(checkpointer=checkpointer if checkpointer is not None else memory_checkpointer())


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


@dataclass
class RunResult:
    """
    Where a run stands after process_email or resume_email.

    Example (email #9, right after process_email: paused at approval):
        RunResult(thread_id="3f2a9c1e-5b7d-4e8a-9c0f-1d2e3f4a5b6c",
                  state={"email_path": "...", "email": ParsedEmail(...), "classification": ...,
                         "route": "human", "reason_for_human_review": "Suspicious: ...", "outgoing_draft": OutgoingDraft(...)},
                  nodes_run=["read_email", "classify", "decide_route", "human_review"],
                  waiting_for_human={"incoming": {...}, "route": "human", "reason_for_human_review": "...", "outgoing_draft": {...}})
    After resume_email: nodes_run=["approval", "action"], state gains "final_human_decision" and
    "final_outgoing_message", waiting_for_human=None.
    """

    thread_id: str
    state: EmailState
    nodes_run: list[str] = field(default_factory=list)   # the nodes that ran in THIS half, in order
    waiting_for_human: dict | None = None                 # the approval request if paused, else None


def run_config(thread_id: str) -> dict[str, Any]:
    """
    The `config` given to every LangGraph call for one run.

    Shape: {"configurable": {"thread_id": "3f2a9c1e-..."},   # which run: where checkpoints are saved/read
            "callbacks": [CallbackHandler(...)]}             # Langfuse records every node (tracing.py)
    """
    return {"configurable": {"thread_id": thread_id}, "callbacks": graph_callbacks()}


def run_until_pause_or_end(graph: CompiledStateGraph, graph_input: Any, thread_id: str) -> RunResult:
    """
    Run the graph (a new run, or a resumed one) until it pauses at approval or reaches END.

    graph.stream(..., stream_mode="updates", subgraphs=True) hands back each node's result as soon
    as that node finishes (that's what the UI will use in step 15 to show the steps appearing one
    by one). subgraphs=True (LangGraph): also report the nodes INSIDE a subgraph. Each item is a
    pair (namespace, update): namespace () = the main graph; ("booking_branch:<id>",) = inside the
    booking subgraph. Real items for email #3:
        ((), {"read_email": {"email": ParsedEmail(...)}})
        ((), {"classify": {"classification": Classification(...)}})
        ((), {"decide_route": {"route": "booking"}})
        (("booking_branch:4f2c...",), {"extract_request": {"booking_extraction": ..., "booking_request": ...}})
        (("booking_branch:4f2c...",), {"check_availability": {"availability_result": ...}})
        (("booking_branch:4f2c...",), {"price_stay": {"stay_price": ...}})
        (("booking_branch:4f2c...",), {"quote_reply": {"outgoing_draft": OutgoingDraft(...)}})
        ((), {"booking_branch": {... everything the subgraph added ...}})   <- the box as a whole: skipped
        ((), {"__interrupt__": (Interrupt(value={...the approval request...}, ...),)})   <- the pause
    "__interrupt__" is not a node: it's LangGraph telling us the run stopped at an interrupt().
    nodes_run for #3:
        ["read_email", "classify", "decide_route", "booking_branch > extract_request",
         "booking_branch > check_availability", "booking_branch > price_stay", "booking_branch > quote_reply"]

    Then graph.get_state(config) reads the run's latest checkpoint (a StateSnapshot):
        snapshot.values      the whole state so far, e.g. {"email_path": ..., "email": ..., "outgoing_draft": ...}
        snapshot.interrupts  the waiting interrupts, e.g. (Interrupt(value={...request...}),); () if none
    """
    config = run_config(thread_id)
    nodes_run: list[str] = []
    subgraphs_seen: set[str] = set()          # boxes whose inner steps we already listed
    for namespace, update in graph.stream(graph_input, config, stream_mode="updates", subgraphs=True):
        for name in update:
            if name == "__interrupt__":
                continue
            # Step 13: LangGraph gives the error handler an internal name such as
            # "__default_error_handler__"; shown as "error_handler" (e.g. "invoice_branch > error_handler").
            if "error_handler" in name:
                name = "error_handler"
            if namespace:
                # Inside a subgraph: "booking_branch:4f2c..." -> "booking_branch"
                box = namespace[0].split(":")[0]
                subgraphs_seen.add(box)
                nodes_run.append(f"{box} > {name}")
            elif name not in subgraphs_seen:
                nodes_run.append(name)
            # else: the subgraph reported as a whole, after its inner steps: already listed

    snapshot = graph.get_state(config)
    waiting = snapshot.interrupts[0].value if snapshot.interrupts else None
    return RunResult(thread_id=thread_id, state=snapshot.values, nodes_run=nodes_run, waiting_for_human=waiting)


def process_email(name: str, graph: CompiledStateGraph | None = None) -> RunResult:
    """
    FIRST HALF: start a new run for one demo email; it stops at approval.

    graph: pass one in to resume later with the same object (needed while the checkpointer is in
    memory); None = build a new one.
    """
    graph = graph if graph is not None else build_graph()
    thread_id = str(uuid.uuid4())         # a new random ID: this run's thread
    # propagate_attributes(...): Langfuse's way to name the trace and tag it; everything recorded
    # inside the `with` block belongs to this trace. session_id=thread_id groups the two halves
    # (start + resume) of the same run together in Langfuse.
    with propagate_attributes(trace_name=f"email {name}", session_id=thread_id, tags=["demo-email"]):
        return run_until_pause_or_end(graph, {"email_path": str(email_path_for(name))}, thread_id)


def resume_email(thread_id: str, decision: dict, graph: CompiledStateGraph) -> RunResult:
    """
    SECOND HALF: give the staff member's answer to a paused run and let it continue.

    decision: the raw answer, e.g. {"decision": "approve"} or {"decision": "edit", "edited_body": "..."}.
    Command(resume=decision) is LangGraph's way to say "this is the answer to the waiting interrupt()".
    LangGraph validates it against HumanDecision; a wrong answer raises pydantic.ValidationError and
    leaves the run paused, so it can be answered again.
    """
    # Refuse an answer for a run that isn't waiting: an unknown thread_id, or a run already finished.
    # graph.get_state(config).interrupts (LangGraph) = the questions the run is waiting on; () = none.
    if not graph.get_state(run_config(thread_id)).interrupts:
        raise ValueError(f"No run waiting for approval with thread_id {thread_id!r}")
    with propagate_attributes(trace_name="approval decision", session_id=thread_id, tags=["demo-email"]):
        return run_until_pause_or_end(graph, Command(resume=decision), thread_id)


def show_paused_run(result: RunResult) -> None:
    """Print where a run stopped: what the UI's right-hand column will show (the draft to approve)."""
    state = result.state
    # print(f"...{x}...") = plain Python: show a line of text on screen; the f"..." ("f-string")
    # puts the value of whatever is inside {} into the text.
    print(f"thread_id  : {result.thread_id}")
    # " -> ".join([...]) = plain Python: glue a list of strings together with " -> " between them:
    #   ["read_email", "classify"] -> "read_email -> classify"
    print(f"nodes run  : {' -> '.join(result.nodes_run)}")
    # Read from the approval request, not the state: after a failed step (step 13) the state may
    # have no email or route, and the request already handles that.
    if result.waiting_for_human:
        incoming = result.waiting_for_human["incoming"]
        print(f"from       : {incoming['sender']}")
        print(f"subject    : {incoming['subject']}")
        print(f"route      : {result.waiting_for_human['route']}")

    # state.get("key") = plain Python dict method: the value, or None if the key isn't there
    # (only route "human" has a reason_for_human_review).
    reason = state.get("reason_for_human_review")
    if reason:
        print(f"why human  : {reason}")

    # The approval request (approval_request() in nodes/approval.py): what the UI will display.
    if result.waiting_for_human:
        # The evidence: what the branch read and decided (e.g. a booking's dates and guests).
        # .items() (plain Python) = the dict's (key, value) pairs: ("read_as", "Friday, ..."), ...
        evidence = result.waiting_for_human["evidence"]
        for key, value in evidence.items():
            if not value:                               # skip empty ones ([] or "")
                continue
            # isinstance(value, list) (plain Python): is it a list? A list (e.g. an invoice's lines)
            # is printed one item per line; anything else on one line.
            if isinstance(value, list):
                print(f"{key}:")
                for item in value:
                    print(f"  {item}")
            else:
                print(f"{key:<11}: {value}")            # {key:<11} = the key padded to 11 characters
        draft = result.waiting_for_human["outgoing_draft"]
        print("\n--- WAITING FOR APPROVAL: the outgoing draft ---")     # "\n" = an empty line first
        print(f"kind       : {draft['kind']}")
        print(f"to         : {draft['outgoing_to']}")
        print(f"subject    : {draft['outgoing_subject']}")
        print(f"body       :\n{draft['outgoing_body']}\n")
        print("To answer, run (a new program):")
        print(f"  uv run python -m backoffice.graph.main_graph resume {result.thread_id} approve")


def show_finished_run(result: RunResult) -> None:
    """Print how a resumed run ended: the decision and what was sent (the UI's Sent folder)."""
    print(f"thread_id  : {result.thread_id}")
    print(f"resumed    : {' -> '.join(result.nodes_run)}")
    email = result.state.get("email")                 # missing if the email file couldn't be read
    print(f"email      : {email.subject if email else result.state.get('email_path')}")
    print(f"decision   : {result.state['final_human_decision'].decision}")
    sent = result.state["final_outgoing_message"]       # None after a reject
    if sent:
        print(f"sent       : to {sent.outgoing_to}: {sent.outgoing_subject}")
    else:
        print("sent       : nothing (rejected)")
    print("recorded   : one row in the `actions` table, under this thread_id")


# =================================================================================================
# THE COMMAND LINE: a stand-in for the front end, until steps 15-16 exist.
# =================================================================================================
# Two commands, run as two SEPARATE programs, like the UI will do them:
#     process <email name>                       = "open the email"  (runs until approval, then ENDS)
#     resume <thread_id> approve|reject          = "click a button"  (a new program finishes the run)
#     resume <thread_id> edit "<new text>"       = "edit, then send"
# Between the two, nothing runs: the paused run exists only in Postgres (postgres_checkpointer).
# When the front end exists, this block is no longer needed for the demo (it stays as a quick test).
#
# `if __name__ == "__main__":`  (plain Python, nothing to do with LangGraph)
#   Python gives every file a hidden variable, __name__:
#     - when you RUN the file as a program (uv run python -m backoffice.graph.main_graph ...),
#       __name__ is the text "__main__", so the block below runs;
#     - when another file IMPORTS this one (the tests do: from backoffice.graph.main_graph import ...),
#       __name__ is "backoffice.graph.main_graph", so the block is SKIPPED.
#   That's how one file can be both a library (functions others import) and a runnable program.
if __name__ == "__main__":
    # sys.argv  (plain Python, from the `sys` module imported at the top)
    #   The words you typed on the command line, as a list of strings. For
    #       uv run python -m backoffice.graph.main_graph resume 6b9a9f43-... edit "Please call the guest."
    #   sys.argv is
    #       ["...main_graph.py", "resume", "6b9a9f43-...", "edit", "Please call the guest."]
    #        [0] the program      [1]       [2]             [3]     [4]
    #   sys.argv[1:] = everything except [0], i.e. only the words YOU typed.
    #   (Words in "quotes" stay together as one item, even with spaces inside.)
    words = sys.argv[1:]

    # `with postgres_checkpointer() as checkpointer:` (ours, checkpointer.py): opens ONE Postgres
    # connection for this program; LangGraph saves/loads runs through it. Closed when the block ends.
    with postgres_checkpointer() as checkpointer:
        graph = build_graph(checkpointer)          # ours (above): the graph, saving into Postgres

        # --- process <email name>: "open the email" ------------------------------------------------
        if len(words) == 2 and words[0] == "process":
            show_paused_run(process_email(words[1], graph))

        # --- resume <thread_id> <approve|reject|edit> ["new text"]: "click a button" ---------------
        elif len(words) >= 3 and words[0] == "resume":
            thread_id, decision = words[1], words[2]
            answer = {"decision": decision}            # the shape HumanDecision expects (state.py)
            if decision == "edit" and len(words) >= 4:
                answer["edited_body"] = words[3]       # the staff member's new text
            # try/except (plain Python): run the block; if it raises one of the listed errors, run
            # the `except` part instead of crashing with a long error report.
            #   ValueError      (ours, resume_email): no run is waiting under this thread_id
            #   ValidationError (Pydantic, raised by LangGraph's check against HumanDecision): the
            #                   answer has the wrong shape, e.g. "aprove", or "edit" without a text.
            #                   The run stays paused, so it can be answered again.
            try:
                show_finished_run(resume_email(thread_id, answer, graph))
            except (ValueError, ValidationError) as error:
                print(f"Not accepted: {error}")

        # --- anything else: show how to use it ------------------------------------------------------
        else:
            print("Usage:")
            print("  uv run python -m backoffice.graph.main_graph process <email name>")
            print("  uv run python -m backoffice.graph.main_graph resume <thread_id> approve|reject")
            print('  uv run python -m backoffice.graph.main_graph resume <thread_id> edit "<new text>"')

    flush_traces()     # ours (tracing.py): send the Langfuse trace before the program exits
