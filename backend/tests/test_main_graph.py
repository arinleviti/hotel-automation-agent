"""Tests for the real graph in graph/main_graph.py."""

from types import SimpleNamespace

import pytest

import backoffice.graph.nodes.classify as classify_module
from backoffice.graph.main_graph import build_graph, email_path_for, process_email
from backoffice.graph.state import Classification

# A question: its branch is still a placeholder, so this tests the trunk + approval only
# (the booking branch has its own end-to-end tests in test_booking_graph.py).
FORM = Classification(type="question", suspicious=False, suspicious_reason="", confidence=0.95,
                      summary="Guest asks about the pool and spa.")


def test_graph_has_the_expected_nodes():
    # get_graph() describes the compiled graph; its nodes include LangGraph's __start__ and __end__.
    # (The booking subgraph counts as ONE node here; its inside is tested in test_booking_graph.py.)
    nodes = set(build_graph().get_graph().nodes)

    assert nodes == {"__start__", "read_email", "classify", "decide_route",
                     "invoice_branch", "booking_branch", "question_branch", "human_review",
                     "approval", "action", "__end__"}


def test_process_email_runs_the_trunk_and_pauses_at_approval(monkeypatch):
    # Fake Claude for classify (no cost): returns FORM whatever the email.
    fake = SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=FORM,
                                                usage=SimpleNamespace(input_tokens=500, output_tokens=60))))
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)

    result = process_email("06_question_pool_and_spa")

    # Shape of result.state: {"email_path": ..., "email": ..., "classification": ..., "route": "question", "outgoing_draft": ...}
    assert set(result.state) == {"email_path", "email", "classification", "route", "outgoing_draft"}
    assert result.state["route"] == "question"
    assert result.state["email"].subject == "Pool and spa question"
    assert result.state["classification"] == FORM
    assert result.nodes_run == ["read_email", "classify", "decide_route", "question_branch"]
    assert result.waiting_for_human is not None          # paused: the approval request is waiting
    assert len(result.thread_id) == 36                   # a uuid4, e.g. "3f2a9c1e-5b7d-4e8a-9c0f-1d2e3f4a5b6c"


def test_only_demo_emails_can_be_opened():
    assert email_path_for("06_question_pool_and_spa.eml").name == "06_question_pool_and_spa.eml"
    with pytest.raises(ValueError):
        email_path_for("../../.env")             # a name that tries to escape data/emails/
    with pytest.raises(ValueError):
        email_path_for("99_does_not_exist")
