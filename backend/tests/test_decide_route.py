"""Tests for the routing rules (decide_route) and the fork in the graph. No LLM, no cost."""

from types import SimpleNamespace

import pytest

import backoffice.graph.nodes.classify as classify_module
from backoffice.graph.main_graph import process_email_step_by_step
from backoffice.graph.nodes.decide_route import route_for
from backoffice.graph.state import Classification


def form(type_="question", suspicious=False, confidence=0.95) -> Classification:
    """A Classification with sensible defaults, e.g. form(type_="booking", confidence=0.6)."""
    return Classification(type=type_, suspicious=suspicious,
                          suspicious_reason="Instructions addressed to the assistant." if suspicious else "",
                          confidence=confidence, summary="test")


@pytest.mark.parametrize("type_", ["invoice", "booking", "question"])
def test_confident_clean_email_goes_to_its_branch(type_):
    assert route_for(form(type_=type_)) == {"route": type_}


def test_suspicious_goes_to_a_human_even_if_confident():
    decision = route_for(form(type_="booking", suspicious=True, confidence=0.99))

    assert decision["route"] == "human"
    assert decision["human_reason"] == "Suspicious: Instructions addressed to the assistant."


def test_other_goes_to_a_human():
    assert route_for(form(type_="other"))["route"] == "human"


def test_low_confidence_goes_to_a_human():
    decision = route_for(form(type_="booking", confidence=0.6))

    assert decision["route"] == "human"
    assert "0.60" in decision["human_reason"]


def test_confidence_exactly_at_the_threshold_is_accepted():
    assert route_for(form(type_="invoice", confidence=0.7)) == {"route": "invoice"}


@pytest.mark.parametrize(
    "classification, expected_branch",
    [
        (form(type_="question"), "question_branch"),
        (form(type_="invoice"), "invoice_branch"),
        (form(type_="booking", suspicious=True), "human_review"),
    ],
)
def test_graph_runs_the_trunk_then_exactly_one_branch(monkeypatch, classification, expected_branch):
    # Fake Claude: classify returns the given form whatever the email.
    fake = SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=classification)))
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)

    _state, nodes_run = process_email_step_by_step("06_question_pool_and_spa")

    assert nodes_run == ["read_email", "classify", "decide_route", expected_branch]
