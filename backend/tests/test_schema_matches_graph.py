"""The page's "Show the schema" drawing (frontend/src/schema.json) must show the REAL graph.

The drawing is made by hand (for a clean layout), so it could drift from the code: a node added or
renamed in a branch, an edge changed. This test builds the real graphs and compares:
  - the node names: every node in the code is drawn, and every drawn node exists;
  - the edges: every arrow, and whether it is conditional (a routing function picks one).
If it fails after a change to the graph, update schema.json (and its position on the drawing).

How the real graph is read: compiled_graph.get_graph() (LangGraph) returns its nodes and edges;
each edge has .source, .target and .conditional. The main graph shows each branch as ONE node
("booking_branch"), so the three branch graphs are read on their own and their nodes prefixed
like the step log does ("booking_branch > price_stay").
"""

# Plain Python:
import json
from pathlib import Path

# OURS:
from backoffice.graph.branches.booking.subgraph import build_booking_graph
from backoffice.graph.branches.invoice.subgraph import build_invoice_graph
from backoffice.graph.branches.question.subgraph import build_question_graph
from backoffice.graph.main_graph import build_graph

SCHEMA = Path(__file__).resolve().parents[2] / "frontend" / "src" / "schema.json"
BRANCHES = {"invoice_branch": build_invoice_graph, "booking_branch": build_booking_graph,
            "question_branch": build_question_graph}


def is_internal(name: str) -> bool:
    """LangGraph's own nodes: __start__, __end__ and the error handlers (__error_handler__classify ...)."""
    return name.startswith("__")


def real_graph() -> tuple[set[str], set[tuple[str, str, bool]]]:
    """
    The nodes and edges of the compiled graphs, named as the drawing names them.
    Shape: ({"read_email", "booking_branch > price_stay", ...},
            {("read_email", "classify", False), ("decide_route", "booking_branch", True), ...})
    """
    nodes: set[str] = set()
    edges: set[tuple[str, str, bool]] = set()
    main = build_graph().get_graph()
    for name in main.nodes:
        if not is_internal(name) and name not in BRANCHES:
            nodes.add(name)
    for edge in main.edges:
        if not (is_internal(edge.source) or is_internal(edge.target)):
            edges.add((edge.source, edge.target, edge.conditional))
    for branch, build in BRANCHES.items():
        graph = build().get_graph()
        for name in graph.nodes:
            if not is_internal(name):
                nodes.add(f"{branch} > {name}")
        for edge in graph.edges:
            if not (is_internal(edge.source) or is_internal(edge.target)):
                edges.add((f"{branch} > {edge.source}", f"{branch} > {edge.target}", edge.conditional))
    return nodes, edges


def drawn_graph() -> tuple[set[str], set[tuple[str, str, bool]]]:
    """The nodes and edges in schema.json, in the same shape as real_graph()."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    nodes = {node["id"] for node in schema["nodes"]}
    edges = {(edge["from"], edge["to"], edge["conditional"]) for edge in schema["edges"]}
    return nodes, edges


def test_the_drawing_has_exactly_the_real_nodes():
    real_nodes, _ = real_graph()
    drawn_nodes, _ = drawn_graph()

    assert drawn_nodes - real_nodes == set(), "drawn but not in the code"
    assert real_nodes - drawn_nodes == set(), "in the code but not drawn"


def test_the_drawing_has_exactly_the_real_edges():
    _, real_edges = real_graph()
    _, drawn_edges = drawn_graph()

    assert drawn_edges - real_edges == set(), "arrows drawn that the code doesn't have"
    assert real_edges - drawn_edges == set(), "arrows in the code that aren't drawn"
