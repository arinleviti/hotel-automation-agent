"""conftest.py: pytest runs this file BEFORE the test files, so settings made here apply to all tests,
and the fixtures defined here can be used by any test file.

TRACING_ENABLED=false: the tests must not send fake traces to the real Langfuse project.
Our settings read environment variables BEFORE the .env file, so this wins over .env.
"""

import os
from contextlib import nullcontext

import pytest

os.environ["TRACING_ENABLED"] = "false"


@pytest.fixture
def fake_actions_table(monkeypatch):
    """
    Replace the action node's database write with a list in memory, so graph tests that reach the
    action node run without Postgres.

    monkeypatch.setattr(module, "name", replacement) = pytest swaps a name inside a module for the
    duration of one test, then puts the original back. The action node calls `connect()` and
    `save_action(...)` by those names, so we swap both:
      connect     -> nullcontext(): a do-nothing `with` block (no database connection)
      save_action -> appends the call's arguments to `saved` instead of inserting a row

    Shape of `saved` after one approved run of email #9:
        [{"thread_id": "6b9a9f43-...", "email_name": "09_suspicious_hidden_instruction",
          "decision": Decision.APPROVE, "message": OutgoingDraft(...), "comment": ""}]
    """
    import backoffice.graph.nodes.action as action_module

    saved: list[dict] = []

    def fake_save_action(conn, thread_id, email_name, decision, message, comment=""):
        saved.append({"thread_id": thread_id, "email_name": email_name, "decision": decision,
                      "message": message, "comment": comment})
        return True

    monkeypatch.setattr(action_module, "connect", lambda: nullcontext())
    monkeypatch.setattr(action_module, "save_action", fake_save_action)
    return saved
