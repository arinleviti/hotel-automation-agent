"""Tests for the backend API (backoffice/api/): every endpoint, the SSE stream (labels + detail), a full
process -> decide -> sent cycle, and one private inbox per visitor (step 16.2). No cost, no database:
the graph uses the in-memory checkpointer, Claude is faked (email #10 takes the human route: no branch
LLM call), and the API's small database functions are swapped for dicts and lists in memory.

TestClient (FastAPI) sends requests to the app in the same program, without a real server.
`with TestClient(app) as client:` also runs the app's start/stop code (lifespan).
Every request carries the visitor id header, like the real page: headers={"X-Visitor-Id": ...}.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backoffice.api.app as api_module
import backoffice.graph.nodes.classify as classify_module
from backoffice.graph.main_graph import build_graph
from backoffice.graph.state import Classification

OTHER = Classification(type="other", suspicious=False, suspicious_reason="", confidence=0.95,
                       summary="Guest asks to cancel a booking.")

ALICE = {"X-Visitor-Id": "aaaaaaaa-1111-4000-8000-000000000001"}
BOB = {"X-Visitor-Id": "bbbbbbbb-2222-4000-8000-000000000002"}


@pytest.fixture
def client(monkeypatch, fake_actions_table, tmp_path):
    """An API client on an in-memory graph, with fake Claude and fake database functions."""
    # No built page in these tests, whatever is in frontend/dist on this machine (see the page test below).
    monkeypatch.setattr(api_module, "PAGE_DIR", tmp_path / "no-page")
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=OTHER,
                                                usage=SimpleNamespace(input_tokens=500, output_tokens=60)))))
    # The fake `runs` table. Shape: {thread_id: {"email_name": "10_other_cancellation", "visitor_id": "aaaa..."}}
    runs: dict[str, dict] = {}

    def save_run(thread_id, email_name, visitor_id):
        runs[thread_id] = {"email_name": email_name, "visitor_id": visitor_id}

    def latest_runs(visitor_id):
        # The decision comes from the fake actions table (written by the action node).
        decided = {row["thread_id"]: str(row["decision"]) for row in fake_actions_table}
        return {run["email_name"]: {"thread_id": thread_id, "started_at": None, "decision": decided.get(thread_id)}
                for thread_id, run in runs.items() if run["visitor_id"] == visitor_id}

    def actions(visitor_id):
        # The fake actions rows hold the OutgoingDraft as `message`; the Sent folder wants the table's columns.
        return [{"thread_id": row["thread_id"], "email_name": row["email_name"], "decision": str(row["decision"]),
                 "kind": str(row["message"].kind), "outgoing_to": row["message"].outgoing_to,
                 "outgoing_subject": row["message"].outgoing_subject, "outgoing_body": row["message"].outgoing_body,
                 "comment": row["comment"], "decided_at": "2026-11-13T12:00:00+00:00"}
                for row in fake_actions_table
                if row["message"] is not None and runs.get(row["thread_id"], {}).get("visitor_id") == visitor_id]

    monkeypatch.setattr(api_module, "db_save_run", save_run)
    monkeypatch.setattr(api_module, "db_latest_runs", latest_runs)
    monkeypatch.setattr(api_module, "db_actions", actions)
    monkeypatch.setattr(api_module, "db_run_visitor", lambda thread_id: runs.get(thread_id, {}).get("visitor_id"))
    monkeypatch.setattr(api_module, "db_delete_old_runs", lambda: [])
    # The spending limits count runs (step 18): (this visitor's, everyone's), all fake runs counted as recent.
    monkeypatch.setattr(api_module, "db_count_recent_runs", lambda visitor_id: (
        sum(1 for run in runs.values() if run["visitor_id"] == visitor_id), len(runs)))
    with TestClient(api_module.create_app(graph=build_graph())) as test_client:
        yield test_client


def read_events(response) -> list[tuple[str, dict]]:
    """
    Parse an SSE response into (event, data) pairs.
    Shape: [("start", {"thread_id": ...}), ("step", {"step": "read_email", "label": "...", "detail": {...}}), ...,
            ("done", {...})]
    """
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def process_10(client, visitor=ALICE) -> str:
    """Process email #10 as this visitor; return the run's thread_id."""
    events = read_events(client.post("/emails/10_other_cancellation/process", headers=visitor))
    return events[0][1]["thread_id"]


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_the_inbox_lists_the_ten_demo_emails_as_new(client):
    inbox = client.get("/emails", headers=ALICE).json()

    assert len(inbox) == 10
    assert inbox[0]["name"] == "01_invoice_front_range_provisions"
    assert inbox[2]["sender"].startswith("Sarah Mitchell")
    assert all(row["status"] == "new" for row in inbox)


def test_processing_streams_every_step_then_the_approval_request(client):
    response = client.post("/emails/10_other_cancellation/process", headers=ALICE)

    assert response.headers["content-type"].startswith("text/event-stream")
    events = read_events(response)
    kinds = [kind for kind, _ in events]
    assert kinds == ["start", "step", "step", "step", "step", "done"]
    steps = [data for kind, data in events if kind == "step"]
    assert [s["step"] for s in steps] == ["read_email", "classify", "decide_route", "human_review"]
    assert steps[0]["label"].startswith("Read the email from Karen Liu")
    assert steps[1]["label"] == "Claude classified it: other (confidence 0.95)"
    assert steps[2]["label"].startswith("Route chosen in code: human")
    done = events[-1][1]
    assert done["waiting_for_human"]["outgoing_draft"]["kind"] == "forward_to_staff"
    assert done["waiting_for_human"]["suspicious"] is False          # #10 is "other", not suspicious


def test_each_step_carries_what_the_node_added(client):
    events = read_events(client.post("/emails/10_other_cancellation/process", headers=ALICE))
    detail = {data["step"]: data["detail"] for kind, data in events if kind == "step"}

    assert detail["read_email"]["email"]["sender"].startswith("Karen Liu")
    assert detail["classify"]["classification"] == {
        "type": "other", "suspicious": False, "suspicious_reason": "", "confidence": 0.95,
        "summary": "Guest asks to cancel a booking."}
    assert detail["decide_route"]["route"] == "human"
    assert detail["human_review"]["outgoing_draft"]["kind"] == "forward_to_staff"    # an enum -> its text


def test_a_full_cycle_process_then_decide(client):
    thread_id = process_10(client)

    waiting = client.get(f"/runs/{thread_id}", headers=ALICE).json()
    assert waiting["status"] == "waiting"
    assert client.get("/emails", headers=ALICE).json()[9]["status"] == "waiting"

    finished = client.post(f"/runs/{thread_id}/decision", json={"decision": "approve"}, headers=ALICE).json()

    assert finished == {"thread_id": thread_id, "status": "finished", "approval_request": None,
                        "decision": "approve", "sent": finished["sent"], "steps": finished["steps"]}
    # The second half's steps, for the page's log: approval, then action.
    assert [(s["step"], s["label"]) for s in finished["steps"]] == [
        ("approval", "Staff decision: approve"),
        ("action", "Recorded: sent to Front desk <frontdesk@overlook-hotel.example>")]
    assert finished["steps"][0]["detail"]["final_human_decision"]["decision"] == "approve"
    assert finished["sent"]["outgoing_subject"].startswith("Needs a person:")
    assert client.get("/emails", headers=ALICE).json()[9]["status"] == "approve"
    assert [row["thread_id"] for row in client.get("/sent", headers=ALICE).json()] == [thread_id]


def test_each_visitor_sees_only_their_own_inbox_and_runs(client):
    thread_id = process_10(client, ALICE)
    client.post(f"/runs/{thread_id}/decision", json={"decision": "approve"}, headers=ALICE)

    # Bob opens the page: a clean inbox and an empty Sent folder.
    assert all(row["status"] == "new" for row in client.get("/emails", headers=BOB).json())
    assert client.get("/sent", headers=BOB).json() == []
    # ... and he can't open or decide Alice's run (same answer as for a run that doesn't exist).
    assert client.get(f"/runs/{thread_id}", headers=BOB).status_code == 404
    assert client.post(f"/runs/{thread_id}/decision", json={"decision": "reject"}, headers=BOB).status_code == 404
    # Alice still sees her decision.
    assert client.get("/emails", headers=ALICE).json()[9]["status"] == "approve"


def test_a_missing_or_strange_visitor_id_is_refused(client):
    assert client.get("/emails").status_code == 422
    assert client.get("/emails", headers={"X-Visitor-Id": "x"}).status_code == 422
    assert client.get("/emails", headers={"X-Visitor-Id": "'; DROP TABLE runs; --"}).status_code == 422


def test_old_runs_are_forgotten_with_their_saved_state(client, monkeypatch):
    thread_id = process_10(client)
    # Pretend this run is now older than 2 hours: the cleanup returns it.
    monkeypatch.setattr(api_module, "db_delete_old_runs", lambda: [thread_id])

    client.get("/emails", headers=ALICE)

    snapshot = client.app.state.graph.get_state({"configurable": {"thread_id": thread_id}})
    assert snapshot.values == {}                     # its checkpoints are gone too


def test_unknown_email_and_unknown_run_are_refused(client):
    assert client.post("/emails/../../.env/process", headers=ALICE).status_code == 404
    assert client.post("/emails/99_nothing/process", headers=ALICE).status_code == 404
    assert client.get("/runs/no-such-run", headers=ALICE).status_code == 404
    assert client.post("/runs/no-such-run/decision", json={"decision": "approve"}, headers=ALICE).status_code == 404


def test_a_second_decision_is_refused(client):
    thread_id = process_10(client)
    client.post(f"/runs/{thread_id}/decision", json={"decision": "approve"}, headers=ALICE)

    again = client.post(f"/runs/{thread_id}/decision", json={"decision": "reject"}, headers=ALICE)

    assert again.status_code == 409                       # the run is no longer waiting


def test_a_wrong_decision_shape_is_refused_before_the_graph(client):
    thread_id = process_10(client)

    response = client.post(f"/runs/{thread_id}/decision", json={"decision": "edit"}, headers=ALICE)   # no text

    assert response.status_code == 422                       # Pydantic (HumanDecision) said no
    assert client.get(f"/runs/{thread_id}", headers=ALICE).json()["status"] == "waiting"     # still waiting


def test_reading_an_email_gives_its_body_and_attachment_names(client):
    email = client.get("/emails/01_invoice_front_range_provisions").json()

    assert email["sender"] == "Front Range Provisions <billing@frontrangeprovisions.example>"
    assert email["subject"].startswith("Invoice FRP-INV-2026-1184")
    assert "attached" in email["body"].lower()
    assert [a["filename"] for a in email["attachments"]] == ["FRP-INV-2026-1184.pdf"]
    assert email["attachments"][0]["content_type"] == "application/pdf"


def test_an_attached_pdf_comes_back_as_the_original_file(client):
    response = client.get("/emails/01_invoice_front_range_provisions/attachments/FRP-INV-2026-1184.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    # Byte-identical to the invoice in data/invoices/ (the .eml was built from it).
    original = api_module.EMAILS_DIR.parent / "invoices" / "FRP-INV-2026-1184.pdf"
    assert response.content == original.read_bytes()


def test_only_real_attachments_of_demo_emails_can_be_fetched(client):
    assert client.get("/emails/99_nothing").status_code == 404
    assert client.get("/emails/06_question_pool_and_spa/attachments/FRP-INV-2026-1184.pdf").status_code == 404
    assert client.get("/emails/01_invoice_front_range_provisions/attachments/..%2F..%2F.env").status_code == 404


# --- Spending limits and the built page (step 18) ----------------------------------------------------

def test_a_visitor_over_the_limit_is_refused_with_a_message(client, monkeypatch):
    monkeypatch.setenv("RUN_LIMIT_PER_VISITOR", "1")        # read by get_settings() on every request
    process_10(client, ALICE)

    refused = client.post("/emails/10_other_cancellation/process", headers=ALICE)

    assert refused.status_code == 429
    assert "limit per visitor" in refused.json()["detail"]
    # Another visitor can still use the demo.
    assert client.post("/emails/10_other_cancellation/process", headers=BOB).status_code == 200


def test_the_whole_site_has_an_hourly_limit(client, monkeypatch):
    monkeypatch.setenv("RUN_LIMIT_PER_HOUR", "2")
    process_10(client, ALICE)
    process_10(client, BOB)

    refused = client.post("/emails/10_other_cancellation/process", headers={"X-Visitor-Id": "cccccccc-3333"})

    assert refused.status_code == 429
    assert "very busy" in refused.json()["detail"]


def test_the_built_page_is_served_from_the_same_address(monkeypatch, tmp_path, fake_actions_table):
    # A stand-in for frontend/dist (what `npm run build` makes).
    (tmp_path / "index.html").write_text("<!doctype html><title>The Overlook</title>", encoding="utf-8")
    monkeypatch.setattr(api_module, "PAGE_DIR", tmp_path)
    monkeypatch.setattr(api_module, "db_latest_runs", lambda visitor_id: {})
    monkeypatch.setattr(api_module, "db_delete_old_runs", lambda: [])

    with TestClient(api_module.create_app(graph=build_graph())) as page_client:
        assert "The Overlook" in page_client.get("/").text                      # the page
        assert page_client.get("/health").json() == {"ok": True}               # the API still answers
        assert len(page_client.get("/emails", headers=ALICE).json()) == 10
        # Only files INSIDE the page folder can come back: no climbing up to the .env next to it.
        assert page_client.get("/../.env").status_code == 404
        assert page_client.get("/%2e%2e/.env").status_code == 404
