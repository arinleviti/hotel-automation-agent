"""Tests for step_detail (api/steps.py): what each node added, as plain JSON for the page's step log."""

import json
from datetime import date
from decimal import Decimal

from backoffice.api.steps import step_detail
from backoffice.graph.state import Attachment, Classification, DraftKind, OutgoingDraft
from backoffice.services.pricing import StayPrice


def test_our_objects_become_plain_json():
    price = StayPrice(nights=3, subtotal=Decimal("1305.00"), tax=Decimal("135.72"), total_price=Decimal("1440.72"))
    draft = OutgoingDraft(kind=DraftKind.OK_TO_PAY, outgoing_to="Accounts <accounts@overlook-hotel.example>",
                          outgoing_subject="OK to pay", outgoing_body="...", reason="All lines match.")

    detail = step_detail({"stay_price": price, "outgoing_draft": draft, "night": date(2026, 12, 18)})

    assert detail["stay_price"]["total_price"] == "1440.72"           # money stays exact, as text
    assert detail["outgoing_draft"]["kind"] == "ok_to_pay"           # an enum -> its value
    assert detail["night"] == "2026-12-18"
    json.dumps(detail)                                                # and the whole thing is valid JSON


def test_llm_forms_and_scores():
    c = Classification(type="booking", suspicious=False, suspicious_reason="", confidence=0.97, summary="Room request.")

    detail = step_detail({"classification": c, "score": 0.7905674576759338})

    assert detail["classification"]["type"] == "booking"
    assert detail["score"] == 0.7906


def test_long_attachment_text_and_the_agent_conversation_are_shortened():
    pdf = Attachment(filename="FRP-INV-2026-1184.pdf", content_type="application/pdf", markdown="x" * 5000)

    detail = step_detail({"attachments": [pdf], "agent_messages": [{"role": "user"}] * 5})

    assert detail["attachments"][0]["markdown"].endswith("(5,000 characters in total)")
    assert len(detail["attachments"][0]["markdown"]) < 400
    assert detail["agent_messages"].startswith("(5 messages")
