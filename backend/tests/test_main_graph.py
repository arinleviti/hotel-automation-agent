"""Tests for the real graph in graph/main_graph.py (grows with each part of step 8)."""

from types import SimpleNamespace

import pytest

import backoffice.graph.nodes.classify as classify_module
from backoffice.graph.main_graph import build_graph, email_path_for, process_email
from backoffice.graph.state import Classification

FORM = Classification(type="booking", suspicious=False, suspicious_reason="", confidence=0.95,
                      summary="Guest asks for a quote for Dec 18-21.")


def test_graph_has_the_expected_nodes():
    # get_graph() describes the compiled graph; its nodes include LangGraph's __start__ and __end__.
    nodes = set(build_graph().get_graph().nodes)

    assert nodes == {"__start__", "read_email", "classify", "decide_route",
                     "invoice_branch", "booking_branch", "question_branch", "human_review", "__end__"}


def test_process_email_runs_read_then_classify(monkeypatch):
    # Fake Claude for classify (no cost): returns FORM whatever the email.
    fake = SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=FORM)))
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)

    state = process_email("03_booking_complete")

    # Shape of state: {"email_path": "...", "email": ParsedEmail(...), "classification": Classification(...), "route": "booking"}
    assert set(state) == {"email_path", "email", "classification", "route"}
    assert state["route"] == "booking"
    assert state["email"].subject == "Room availability December 18-21"
    assert state["classification"] == FORM


def test_only_demo_emails_can_be_opened():
    assert email_path_for("06_question_pool_and_spa.eml").name == "06_question_pool_and_spa.eml"
    with pytest.raises(ValueError):
        email_path_for("../../.env")             # a name that tries to escape data/emails/
    with pytest.raises(ValueError):
        email_path_for("99_does_not_exist")
