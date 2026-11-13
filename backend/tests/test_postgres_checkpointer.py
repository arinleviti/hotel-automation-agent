"""Tests for step 9.3: a paused run is saved in Postgres and can be resumed by a NEW program.

"A new program" is simulated by closing the first connection and graph, then opening a new
connection and building a new graph: nothing is shared between the two halves except Postgres.

Needs Postgres (docker compose up -d) with the checkpoint tables (uv run python -m backoffice.db.schema);
skipped otherwise. Claude is faked; the action node's write goes to the fake_actions_table fixture.
Each test deletes the run it saved (delete_thread), so the checkpoint tables are left as they were.
"""

from types import SimpleNamespace

import pytest

import backoffice.graph.nodes.classify as classify_module
from backoffice.graph.checkpointer import postgres_checkpointer
from backoffice.graph.main_graph import build_graph, process_email, resume_email
from backoffice.graph.state import Classification, Decision

SUSPICIOUS = Classification(type="booking", suspicious=True, suspicious_reason="Addresses the assistant.",
                            confidence=0.85, summary="Guest claims a free suite upgrade.")


@pytest.fixture
def fake_claude(monkeypatch):
    fake = SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=SUSPICIOUS,
                                                usage=SimpleNamespace(input_tokens=500, output_tokens=60))))
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: fake)


@pytest.fixture
def postgres_available():
    try:
        with postgres_checkpointer() as checkpointer:
            checkpointer.setup()           # make sure the checkpoint tables exist (safe to repeat)
    except Exception as e:   # database not running, or DATABASE_URL not set
        pytest.skip(f"Postgres not available ({type(e).__name__}): start it with `docker compose up -d`")


@pytest.mark.usefixtures("fake_claude", "fake_actions_table", "postgres_available")
def test_a_paused_run_survives_a_restart_and_is_resumed_by_a_new_program():
    # PROGRAM 1: run until approval, then close everything.
    with postgres_checkpointer() as checkpointer:
        paused = process_email("09_suspicious_hidden_instruction", build_graph(checkpointer))
    assert paused.waiting_for_human is not None

    # PROGRAM 2: a new connection and a new graph; the run is found in Postgres by its thread_id.
    with postgres_checkpointer() as checkpointer:
        graph = build_graph(checkpointer)
        try:
            resumed = resume_email(paused.thread_id, {"decision": "approve"}, graph)

            assert resumed.nodes_run == ["approval", "action"]
            assert resumed.state["final_human_decision"].decision == Decision.APPROVE
            assert resumed.state["outgoing_draft"] == paused.state["outgoing_draft"]   # loaded from Postgres
            assert resumed.waiting_for_human is None
        finally:
            # delete_thread (LangGraph): remove every checkpoint saved under this thread_id.
            checkpointer.delete_thread(paused.thread_id)


@pytest.mark.usefixtures("fake_claude", "fake_actions_table", "postgres_available")
def test_a_finished_run_cannot_be_answered_again():
    with postgres_checkpointer() as checkpointer:
        graph = build_graph(checkpointer)
        paused = process_email("09_suspicious_hidden_instruction", graph)
        try:
            resume_email(paused.thread_id, {"decision": "reject"}, graph)
            with pytest.raises(ValueError):
                resume_email(paused.thread_id, {"decision": "approve"}, graph)   # already finished
        finally:
            checkpointer.delete_thread(paused.thread_id)


def test_an_unknown_thread_id_is_refused():
    # In memory: no database needed to check the refusal.
    with pytest.raises(ValueError):
        resume_email("no-such-run", {"decision": "approve"}, build_graph())


def test_a_connection_closed_by_the_database_is_replaced(postgres_available, fake_claude, fake_actions_table):
    # Step 18: Neon (serverless) closes idle connections. Reproduced here: the database itself
    # kills the pool's connection (pg_terminate_backend), then a run saves its checkpoints. With one
    # fixed connection this failed with "OperationalError: the connection is closed"; the pool
    # notices the dead connection (check_connection) and opens a new one.
    from backoffice.db.connection import connect

    with postgres_checkpointer() as checkpointer:
        with checkpointer.conn.connection() as pooled:          # .conn = the pool; borrow its connection
            pid = pooled.info.backend_pid                       # Postgres's id for that connection
        with connect() as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", (pid,))   # the database closes it

        result = process_email("09_suspicious_hidden_instruction", build_graph(checkpointer))

        assert result.waiting_for_human is not None             # the run saved its checkpoints fine
        checkpointer.delete_thread(result.thread_id)
