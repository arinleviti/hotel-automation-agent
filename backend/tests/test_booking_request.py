"""Tests for services/booking_request.py: the code rules applied to what the LLM read (no LLM, no database)."""

from datetime import date

from backoffice.services.booking_request import (MISSING_ADULTS, MISSING_CHILDREN, MISSING_DATES,
                                                 greeting_name, validate_booking_request)

NOV_2 = date(2026, 11, 2)          # when Sarah's email (#3) was written


def validate(**overrides):
    """Sarah's request (#3) as the LLM reads it, with some values changed by the test."""
    values = dict(check_in=date(2026, 12, 18), check_out=date(2026, 12, 21), adults=2, children=1,
                  children_ages=[8], email_date=NOV_2, child_under_age=13, guest_name="Sarah Mitchell")
    values.update(overrides)
    return validate_booking_request(**values)


# --- The 3 demo emails ------------------------------------------------------------------------

def test_email_3_sarah_is_complete():
    request = validate()

    assert request.is_complete
    assert (request.check_in, request.check_out, request.adults, request.children) == \
           (date(2026, 12, 18), date(2026, 12, 21), 2, 1)


def test_email_4_tom_asks_how_many_children_and_their_ages():
    request = validate(check_in=date(2027, 2, 12), check_out=date(2027, 2, 15), children=None,
                       children_ages=[], email_date=date(2026, 11, 3), guest_name="Tom")

    assert not request.is_complete
    assert request.missing == [MISSING_CHILDREN,
                               "the age of each child (children under 13 pay the child rate)"]
    assert request.check_in == date(2027, 2, 12)          # the dates are kept: they were fine


def test_email_5_priya_two_adults_no_children_is_complete():
    request = validate(check_in=date(2026, 12, 30), check_out=date(2027, 1, 1), children=0, children_ages=[],
                       email_date=date(2026, 11, 3))
    assert request.is_complete


# --- The rules ----------------------------------------------------------------------------------

def test_missing_dates_are_asked_for():
    assert MISSING_DATES in validate(check_in=None).missing
    assert MISSING_DATES in validate(check_out=None).missing


def test_impossible_dates_are_never_priced():
    request = validate(check_in=date(2026, 12, 21), check_out=date(2026, 12, 18))   # check-out before check-in

    assert MISSING_DATES in request.missing
    assert request.check_in is None and request.check_out is None


def test_a_stay_before_the_email_was_written_is_refused():
    assert MISSING_DATES in validate(check_in=date(2026, 10, 1), check_out=date(2026, 10, 3)).missing


def test_adults_must_be_stated_and_at_least_one():
    assert MISSING_ADULTS in validate(adults=None).missing
    assert MISSING_ADULTS in validate(adults=0).missing


def test_children_counted_but_ages_missing_asks_only_for_ages():
    request = validate(children=2, children_ages=[6])

    assert request.missing == ["the age of each child (children under 13 pay the child rate)"]


def test_a_child_aged_13_or_more_pays_the_adult_rate():
    request = validate(children=2, children_ages=[8, 14])

    assert request.is_complete
    assert (request.adults, request.children) == (3, 1)
    assert "aged 14 counted as adult" in request.notes[0]


# --- greeting_name ------------------------------------------------------------------------------

def test_the_signature_name_wins_and_gets_capitals_if_all_lowercase():
    assert greeting_name("tom", "...thanks\ntom", "Tom Becker <tom.b@mail.example>") == "Tom"
    assert greeting_name("Priya Patel", "Kind regards,\nPriya Patel", "p.patel@mail.example") == "Priya Patel"


def test_a_name_not_in_the_email_is_ignored():
    # A name the model made up can't reach the greeting.
    assert greeting_name("Mr. Ullman", "do you have a room?", "x@mail.example") == "guest"


def test_the_from_header_is_the_fallback_then_guest():
    assert greeting_name(None, "do you have a room?", "Sarah Mitchell <s.mitchell@mail.example>") == "Sarah Mitchell"
    assert greeting_name(None, "do you have a room?", "aleviti2@hotmail.example") == "guest"
