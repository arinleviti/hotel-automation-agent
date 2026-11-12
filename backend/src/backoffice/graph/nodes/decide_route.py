"""Node 3 of the graph: decide where the email goes (a CODE-ONLY node: the rules, no LLM).

In:   state["classification"]   the form filled in by classify
Out:  {"route": "invoice" | "booking" | "question" | "human", "reason_for_human_review": "..." (only for "human")}

The model filled in the form; THIS code decides. The rules, checked in this order:
    1. suspicious                 -> human   (never let a possibly malicious email reach a branch)
    2. type "other"               -> human   (no branch for it in phase 1, e.g. cancellations)
    3. confidence below 0.7       -> human   (the model isn't sure what the email is)
    4. otherwise                  -> the branch for its type

Why a NODE that writes the route into the state, plus a tiny conditional edge that just reads it
(see main_graph.py), instead of putting the rules inside the edge function itself:
  - the decision and its reason are SAVED in the state, so the UI (and the human reviewer) can
    show "sent to a human because: suspicious ..." and the evals can check the route;
  - the rules are a plain function, tested on their own without running the graph.
"""

from backoffice.graph.state import Classification, EmailState

MIN_CONFIDENCE = 0.7


def route_for(classification: Classification) -> dict:
    """
    Apply the rules to one classification.

    Shape returned, e.g.:
        {"route": "question"}                                                   # email #6
        {"route": "human", "reason_for_human_review": "Suspicious: Contains instructions addressed to the automated assistant ..."}   # email #9
        {"route": "human", "reason_for_human_review": "No automated process for this kind of email (type 'other')."}             # email #10
    """
    c = classification
    if c.suspicious:
        return {"route": "human", "reason_for_human_review": f"Suspicious: {c.suspicious_reason}"}
    if c.type == "other":
        return {"route": "human", "reason_for_human_review": "No automated process for this kind of email (type 'other')."}
    if c.confidence < MIN_CONFIDENCE:
        return {"route": "human",
                "reason_for_human_review": f"Not sure what this email is: classified as '{c.type}' with confidence {c.confidence:.2f}."}
    return {"route": c.type}


def decide_route(state: EmailState) -> dict:
    """
    THE NODE: reads the classification, returns the route (and the reason, for a human).

    Tracing: no @observe needed. Every NODE is recorded in Langfuse automatically by the
    CallbackHandler main_graph.py gives to LangGraph; the trace shows decide_route with its
    output, e.g. {"route": "human", "reason_for_human_review": "Suspicious: ..."}.
    """
    return route_for(state["classification"])
