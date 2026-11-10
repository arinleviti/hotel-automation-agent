"""TEMPORARY placeholder branches (step 8.3). Each one will be replaced by the real thing:

    invoice_branch   -> step 11: a subgraph (extract lines -> look up prices -> compare -> draft)
    booking_branch   -> step 10: a subgraph (extract request -> availability -> price -> draft)
    question_branch  -> step 12: the agent (search the documents -> answer with sources)
    human_review     -> step 9:  interrupt() and wait for a person (approve / edit / reject)

For now they do nothing: they exist so the routing can be wired and tested end to end. Which one
ran is visible when the graph is streamed (see main_graph.py), so nothing is added to the state.
A node may return an empty dict: "I add nothing".
"""

from backoffice.graph.state import EmailState


def invoice_branch(state: EmailState) -> dict:
    return {}


def booking_branch(state: EmailState) -> dict:
    return {}


def question_branch(state: EmailState) -> dict:
    return {}


def human_review(state: EmailState) -> dict:
    return {}
