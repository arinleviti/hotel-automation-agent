"""Check the question agent's answer before anyone sees it (step 12.2). Pure code, no LLM.

The agent (graph/branches/question/agent.py) is the one place where an LLM WRITES text for a guest.
So code checks what it can check, and anything that fails goes to a person, never to the guest:

    1. not_found                          -> NOT_FOUND     (a person answers; decided 2026-11-12)
    2. "answered" but the answer is empty -> FAILED_CHECK
    3. no sources cited                   -> FAILED_CHECK  (every answer must show its evidence)
    4. a cited chunk was never retrieved  -> FAILED_CHECK  (an invented citation)
    5. a dollar amount in the answer that -> FAILED_CHECK  (an invented or changed price; "$65" and
       isn't in any CITED chunk                              "$65.00" count as the same amount)
    all good                              -> SEND_ANSWER

What no code can check: a non-numeric claim the documents don't make ("the spa is free for
children"). That's covered by the prompt's rules and, finally, by the human approval.

Like every service: no database, no LLM; the data comes in as arguments.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import re                                      # regular expressions: find "$145", "$1,440.72" in a text
from dataclasses import dataclass, field       # @dataclass: a class that just holds fields
from decimal import Decimal                    # exact amounts, so "$65" == "$65.00"
from enum import StrEnum                       # a closed list of named text values

# A dollar amount in text: "$", optional space, digits with optional thousands commas, optional cents.
#   matches "$65", "$1,440.72", "$ 145"; re.findall returns the parts in brackets: "65", "1,440.72", "145"
DOLLAR_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")


class AnswerOutcome(StrEnum):
    SEND_ANSWER = "send_answer"      # the answer passed every check: draft it for the guest
    NOT_FOUND = "not_found"          # the documents don't cover the request: the front desk answers
    FAILED_CHECK = "failed_check"    # the answer broke a rule: the front desk sees it and why


@dataclass
class AnswerCheck:
    """
    The result of checking one answer.

    Examples:
        #6 -> AnswerCheck(outcome=AnswerOutcome.SEND_ANSWER, problems=[])
        #8 -> AnswerCheck(outcome=AnswerOutcome.NOT_FOUND, problems=[])
        an answer quoting "$40" that no cited chunk contains ->
              AnswerCheck(outcome=AnswerOutcome.FAILED_CHECK,
                          problems=["The answer mentions $40, which is not in any cited passage."])
    """

    outcome: AnswerOutcome
    problems: list[str] = field(default_factory=list)


def dollar_amounts(text: str) -> set[Decimal]:
    """
    Every dollar amount in a text, as exact numbers.
        "A Swedish massage is $145; a Spa Day Pass is $65.00" -> {Decimal("145"), Decimal("65.00")}
    Decimal("65") == Decimal("65.00") is True, so the same amount written two ways matches.
    """
    return {Decimal(amount.replace(",", "")) for amount in DOLLAR_AMOUNT.findall(text)}


def check_answer(status: str, answer: str, sources: list[int], retrieved: dict[int, str]) -> AnswerCheck:
    """
    Apply the rules (see the top of this file) to one answer.

    retrieved: every chunk the agent's searches returned in THIS run, chunk id -> its text.
    Shape (#6, 2 of 8):
        {4: "Indoor pool. Our heated indoor pool is open daily from 7:00 AM to 10:00 PM ...",
         27: "| Treatment | Duration | Price |\\n| Swedish massage | 50 min | $145 | ...",
         ...}
    """
    if status == "not_found":
        return AnswerCheck(outcome=AnswerOutcome.NOT_FOUND)

    problems: list[str] = []
    if not answer.strip():
        problems.append("The answer is empty although the status is 'answered'.")
    if not sources:
        problems.append("The answer cites no source.")

    invented = [chunk_id for chunk_id in sources if chunk_id not in retrieved]
    if invented:
        problems.append(f"The answer cites chunk(s) {invented}, which no search returned.")

    # Amounts must come from the passages the answer says it used.
    cited_text = " ".join(retrieved[chunk_id] for chunk_id in sources if chunk_id in retrieved)
    allowed = dollar_amounts(cited_text)
    for amount in sorted(dollar_amounts(answer) - allowed):
        # set - set (plain Python): the amounts in the answer that are NOT among the allowed ones
        problems.append(f"The answer mentions ${amount}, which is not in any cited passage.")

    if problems:
        return AnswerCheck(outcome=AnswerOutcome.FAILED_CHECK, problems=problems)
    return AnswerCheck(outcome=AnswerOutcome.SEND_ANSWER)
