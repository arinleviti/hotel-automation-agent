"""Tests for step 9.2: the action node (carry out the decision) and the `actions` table.

- final_message: pure logic, no database.
- The node inside the graph: database write replaced by the fake_actions_table fixture (conftest.py).
- save_action on the real table: needs Postgres (docker compose up -d), skipped otherwise; runs
  inside a transaction that is rolled back, so the real table is never changed.
"""

import uuid
from types import SimpleNamespace

import pytest

import backoffice.graph.nodes.classify as classify_module
from backoffice.db.connection import connect
from backoffice.db.queries import save_action
from backoffice.graph.branches.human_review import FRONT_DESK
from backoffice.graph.main_graph import build_graph, process_email, resume_email
from backoffice.graph.nodes.action import final_message
from backoffice.graph.state import Classification, Decision, DraftKind, HumanDecision, OutgoingDraft

DRAFT = OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, outgoing_to=FRONT_DESK,
                      outgoing_subject="Needs a person: Re: our stay Dec 5-7",
                      outgoing_body="This email was not answered automatically. ...",
                      reason="Suspicious: ...")

SUSPICIOUS = Classification(type="booking", suspicious=True, suspicious_reason="Addresses the assistant.",
                            confidence=0.85, summary="Guest claims a free suite upgrade.")


# --- final_message: what actually goes out -------------------------------------------------------

def test_approve_sends_the_draft_unchanged():
    assert final_message(DRAFT, HumanDecision(decision="approve")) == DRAFT


def test_edit_replaces_the_body_and_keeps_the_subject():
    message = final_message(DRAFT, HumanDecision(decision="edit", edited_body="Please call the guest."))

    assert message.outgoing_body == "Please call the guest."
    assert message.outgoing_subject == DRAFT.outgoing_subject     # no edited_subject given
    assert message.outgoing_to == DRAFT.outgoing_to
    assert DRAFT.outgoing_body.startswith("This email")           # the original draft is untouched


def test_edit_can_also_change_the_subject():
    message = final_message(DRAFT, HumanDecision(decision="edit", edited_subject="Urgent: check this guest",
                                                 edited_body="Please call the guest."))
    assert message.outgoing_subject == "Urgent: check this guest"


def test_reject_sends_nothing():
    assert final_message(DRAFT, HumanDecision(decision="reject")) is None


# --- The action node inside the graph -------------------------------------------------------------

def run_and_answer(monkeypatch, answer: dict):
    """Run email #9 to the pause (fake Claude), then answer; returns (paused, resumed)."""
    fake = SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=SUSPICIOUS,
                                                usage=SimpleNamespace(input_tokens=500, output_tokens=60))))
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)
    graph = build_graph()
    paused = process_email("09_suspicious_hidden_instruction", graph)
    return paused, resume_email(paused.thread_id, answer, graph)


def test_approved_run_records_the_draft_as_sent(monkeypatch, fake_actions_table):
    paused, resumed = run_and_answer(monkeypatch, {"decision": "approve"})

    assert resumed.nodes_run == ["approval", "action"]
    assert resumed.state["final_outgoing_message"] == paused.state["outgoing_draft"]
    # Shape of fake_actions_table: [{"thread_id": ..., "email_name": ..., "decision": ..., "message": ..., "comment": ""}]
    assert len(fake_actions_table) == 1
    row = fake_actions_table[0]
    assert row["thread_id"] == paused.thread_id                   # read from the run's config
    assert row["email_name"] == "09_suspicious_hidden_instruction"
    assert row["decision"] == Decision.APPROVE


def test_rejected_run_sends_nothing_but_records_the_refused_draft(monkeypatch, fake_actions_table):
    paused, resumed = run_and_answer(monkeypatch, {"decision": "reject", "comment": "Spam."})

    assert resumed.state["final_outgoing_message"] is None
    row = fake_actions_table[0]
    assert row["decision"] == Decision.REJECT
    assert row["message"] == paused.state["outgoing_draft"]       # what was turned down
    assert row["comment"] == "Spam."


# --- save_action on the real Postgres table -------------------------------------------------------

@pytest.fixture
def conn():
    """A real connection whose changes are all undone at the end of the test."""
    try:
        connection = connect()
    except Exception as e:   # database not running, or DATABASE_URL not set
        pytest.skip(f"Postgres not available ({type(e).__name__}): start it with `docker compose up -d`")
    # transaction(force_rollback=True): psycopg opens a transaction and ROLLS IT BACK when the block
    # ends, even if everything succeeded, so nothing the test writes is kept.
    with connection, connection.transaction(force_rollback=True):
        yield connection


def test_save_action_writes_one_row(conn):
    thread_id = str(uuid.uuid4())

    assert save_action(conn, thread_id, "09_suspicious_hidden_instruction", Decision.APPROVE, DRAFT) is True

    row = conn.execute("SELECT email_name, decision, kind, outgoing_to, comment FROM actions"
                       " WHERE thread_id = %s", (thread_id,)).fetchone()
    # Shape of row: a tuple in SELECT order
    assert row == ("09_suspicious_hidden_instruction", "approve", "forward_to_staff", FRONT_DESK, "")


def test_save_action_twice_for_the_same_run_keeps_one_row(conn):
    thread_id = str(uuid.uuid4())

    first = save_action(conn, thread_id, "09_suspicious_hidden_instruction", Decision.APPROVE, DRAFT)
    second = save_action(conn, thread_id, "09_suspicious_hidden_instruction", Decision.APPROVE, DRAFT)

    assert (first, second) == (True, False)                      # the second insert is skipped
    count = conn.execute("SELECT count(*) FROM actions WHERE thread_id = %s", (thread_id,)).fetchone()[0]
    assert count == 1
