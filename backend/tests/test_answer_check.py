"""Tests for services/answer_check.py: the code checks on the agent's answer (no LLM, no database)."""

from decimal import Decimal

from backoffice.services.answer_check import AnswerOutcome, check_answer, dollar_amounts

# Two retrieved chunks, as the agent's searches return them (shortened, real wording).
RETRIEVED = {
    25: "Access to spa facilities. Hotel guests have free access to the sauna, steam room and relaxation area. "
        "Non-guests: Spa Day Pass $65 per person.",
    27: "| Treatment | Duration | Price |\n| Swedish massage | 50 min | $145 |\n| Swedish massage | 80 min | $195 |",
}


def test_a_correct_answer_with_real_sources_and_amounts_is_sent():
    answer = "Hotel guests use the sauna for free. A 50-minute Swedish massage is $145; the day pass is $65.00."
    assert check_answer("answered", answer, [25, 27], RETRIEVED).outcome == AnswerOutcome.SEND_ANSWER


def test_not_found_goes_to_a_person():
    assert check_answer("not_found", "", [], RETRIEVED).outcome == AnswerOutcome.NOT_FOUND


def test_an_invented_price_is_held_back():
    check = check_answer("answered", "A Swedish massage is $140.", [27], RETRIEVED)

    assert check.outcome == AnswerOutcome.FAILED_CHECK
    assert check.problems == ["The answer mentions $140, which is not in any cited passage."]


def test_a_price_from_a_passage_not_cited_is_held_back():
    # $65 is in chunk 25, but the answer only cites chunk 27.
    check = check_answer("answered", "The day pass is $65.", [27], RETRIEVED)
    assert check.outcome == AnswerOutcome.FAILED_CHECK


def test_an_invented_citation_is_held_back():
    check = check_answer("answered", "The pool is open daily.", [4], RETRIEVED)
    assert "cites chunk(s) [4], which no search returned" in check.problems[0]


def test_an_empty_answer_or_no_sources_is_held_back():
    assert check_answer("answered", "  ", [25], RETRIEVED).outcome == AnswerOutcome.FAILED_CHECK
    assert check_answer("answered", "The sauna is free for guests.", [], RETRIEVED).outcome == AnswerOutcome.FAILED_CHECK


def test_dollar_amounts_are_compared_as_numbers():
    assert dollar_amounts("Total $1,440.72, pass $65.00, massage $ 145") == {
        Decimal("1440.72"), Decimal("65"), Decimal("145")}
