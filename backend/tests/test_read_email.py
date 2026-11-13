"""Tests for the read_email node, on the 10 real demo emails (no LLM, no cost)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.graph import END, START, StateGraph

from backoffice.graph.nodes.read_email import parse_eml, read_email
from backoffice.graph.state import EmailState, ParsedEmail

EMAILS_DIR = Path(__file__).resolve().parents[2] / "data" / "emails"


@pytest.fixture(scope="module")
def emails() -> dict[str, ParsedEmail]:
    """
    All 10 demo emails, read once for the whole file (the 2 invoices take seconds: Docling).
    Shape: {"01_invoice_front_range_provisions.eml": ParsedEmail(...), "02_invoice_summit_linen.eml": ..., ...}
    """
    return {p.name: parse_eml(p) for p in sorted(EMAILS_DIR.glob("*.eml"))}


def test_all_ten_emails_are_read(emails):
    assert len(emails) == 10
    assert all(e.subject and e.body and e.date for e in emails.values())


def test_headers_are_decoded(emails):
    pool = emails["06_question_pool_and_spa.eml"]

    assert pool.sender == "Linda Okafor <l.okafor@mail.example>"
    assert pool.subject == "Pool and spa question"
    assert pool.date.isoformat() == "2026-11-04T10:15:00-07:00"
    assert "Do you have an indoor pool" in pool.body


def test_invoice_pdf_becomes_markdown_with_its_table(emails):
    invoice = emails["01_invoice_front_range_provisions.eml"]

    assert [a.filename for a in invoice.attachments] == ["FRP-INV-2026-1184.pdf"]
    markdown = invoice.attachments[0].markdown
    assert "FRP-1021" in markdown and "4.60" in markdown and "504.50" in markdown
    assert "|" in markdown                                   # the line items came out as a Markdown table


def test_only_the_invoices_have_attachments(emails):
    with_attachments = sorted(name for name, e in emails.items() if e.attachments)

    assert with_attachments == ["01_invoice_front_range_provisions.eml", "02_invoice_summit_linen.eml"]


def test_reply_keeps_its_thread_information(emails):
    cancel = emails["10_other_cancellation.eml"]

    assert cancel.in_reply_to == "<OVR-58213.confirmation@overlook-hotel.example>"
    assert "-----Original Message-----" in cancel.body            # the quoted confirmation is kept


def test_node_inside_a_one_node_graph():
    # The smallest possible LangGraph: START -> read_email -> END. invoke() runs it and returns the
    # final state: the input key plus what the node added.
    builder = StateGraph(EmailState)
    builder.add_node("read_email", read_email)
    builder.add_edge(START, "read_email")
    builder.add_edge("read_email", END)
    graph = builder.compile()

    final_state = graph.invoke({"email_path": str(EMAILS_DIR / "04_booking_missing_info.eml")})

    # Shape of final_state: {"email_path": ".../04_booking_missing_info.eml", "email": ParsedEmail(subject="presidents day weekend", ...)}
    assert set(final_state) == {"email_path", "email"}
    assert final_state["email"].subject == "presidents day weekend"
    assert "Sent from my iPhone" in final_state["email"].body


# --- The PDF cache (step 18) ------------------------------------------------------------------------

def test_a_pdf_is_read_by_docling_once_then_comes_from_the_cache(monkeypatch):
    import backoffice.graph.nodes.read_email as read_email_module
    calls = []

    def fake_parse(filename, data):
        calls.append(filename)
        return SimpleNamespace(export_to_markdown=lambda: f"# {filename} ({len(data)} bytes)")

    monkeypatch.setattr(read_email_module, "parse_bytes", fake_parse)
    monkeypatch.setattr(read_email_module, "_PDF_TEXT_CACHE", {})

    first = read_email_module.pdf_to_markdown("a.pdf", b"%PDF same bytes")
    again = read_email_module.pdf_to_markdown("a.pdf", b"%PDF same bytes")
    other = read_email_module.pdf_to_markdown("b.pdf", b"%PDF different bytes")

    assert first == again == "# a.pdf (15 bytes)"
    assert other == "# b.pdf (20 bytes)"
    assert calls == ["a.pdf", "b.pdf"]           # Docling ran once per DIFFERENT file


def test_a_failed_read_is_not_cached(monkeypatch):
    import backoffice.graph.nodes.read_email as read_email_module
    calls = []

    def failing_parse(filename, data):
        calls.append(filename)
        raise RuntimeError("unreadable")

    monkeypatch.setattr(read_email_module, "parse_bytes", failing_parse)
    monkeypatch.setattr(read_email_module, "_PDF_TEXT_CACHE", {})

    for _ in range(2):
        with pytest.raises(RuntimeError):
            read_email_module.pdf_to_markdown("bad.pdf", b"not a pdf")

    assert calls == ["bad.pdf", "bad.pdf"]       # tried again each time
