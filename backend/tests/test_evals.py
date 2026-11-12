"""Tests for the eval machinery (backoffice/evals/): the checks themselves, on hand-made states.
Free: no LLM, no database. (The evals proper cost money and are run by hand, not by pytest.)"""

from datetime import datetime, timezone
from decimal import Decimal

from backoffice.evals.cases import EXPECTED, never_charges_a_guest_the_day_pass, no_invented_maze_age
from backoffice.evals.run_evals import build_report
from backoffice.graph.main_graph import EMAILS_DIR
from backoffice.graph.state import Classification, DraftKind, OutgoingDraft, ParsedEmail


def state_with_body(text: str, **extra) -> dict:
    draft = OutgoingDraft(kind=DraftKind.REPLY_TO_SENDER, outgoing_to="Guest <g@mail.example>",
                          outgoing_subject="Re: ...", outgoing_body=text, reason="")
    return {"outgoing_draft": draft, **extra}


def check(name: str):
    """Find one check by its name, across all emails."""
    return next(c for checks in EXPECTED.values() for c in checks if c.name == name)


def test_every_demo_email_has_checks_and_every_check_has_a_unique_name():
    assert set(EXPECTED) == {p.stem for p in EMAILS_DIR.glob("*.eml")}
    names = [c.name for checks in EXPECTED.values() for c in checks]
    assert len(names) == len(set(names))


def test_a_check_reads_the_state():
    assert check("#3 total is $1,440.72").holds(state_with_body("Total: $1,440.72"))
    assert not check("#3 total is $1,440.72").holds(state_with_body("Total: $1,440.00"))


def test_checks_never_raise_on_an_empty_state():
    # A run that crashed gives an empty state: every check must simply fail, not raise.
    for checks in EXPECTED.values():
        for c in checks:
            try:
                c.holds({})
            except Exception as error:      # pragma: no cover - the test fails with the check's name
                raise AssertionError(f"{c.name} raised {error!r} on an empty state")


def test_the_day_pass_check():
    assert never_charges_a_guest_the_day_pass(state_with_body("The spa is free for hotel guests."))
    assert never_charges_a_guest_the_day_pass(state_with_body("For non-guests a Spa Day Pass is $65."))
    assert not never_charges_a_guest_the_day_pass(state_with_body("The spa costs $65 per person."))


def test_the_invented_maze_age_check():
    assert no_invented_maze_age(state_with_body("The maze is open 9 AM to sunset. Our documents don't mention an age rule."))
    assert not no_invented_maze_age(state_with_body("Children over 12 may enter the maze alone."))


def test_a_suspicious_email_check():
    email = ParsedEmail(sender="Mark Ellison <m@mail.example>", to="", subject="", date=datetime.now(timezone.utc), body="")
    flagged = Classification(type="booking", suspicious=True, suspicious_reason="...", confidence=0.9, summary="")
    draft = OutgoingDraft(kind=DraftKind.FORWARD_TO_STAFF, outgoing_to="Front desk <frontdesk@overlook-hotel.example>",
                          outgoing_subject="", outgoing_body="", reason="")
    state = {"email": email, "classification": flagged, "route": "human", "outgoing_draft": draft}

    assert all(c.holds(state) for c in EXPECTED["09_suspicious_hidden_instruction"])


def test_the_report_gives_pass_rates_and_lists_failures():
    names = ["10_other_cancellation"]
    passed = {"#10 classified as other": 3, "#10 route is human": 3, "#10 note to the front desk": 2}
    failures = {"#10 note to the front desk": ["run 2 (thread abc)"]}

    report = build_report(names, 3, passed, failures, [], 0.5)

    assert "**8/9 checks passed (88.9%)**" in report
    assert "| #10 note to the front desk | 2/3 | ⚠ |" in report
    assert "- **#10 note to the front desk**: run 2 (thread abc)" in report
